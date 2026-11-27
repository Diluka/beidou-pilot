// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Strategy-change chat announcement and party membership tracking.
//
// The companion bot publishes its current strategy mode in /work/bot/state.json
// (container path; Z:\work\bot\state.json for the client process). This module
// polls that file at a low frequency and, when the mode changes, sends one chat
// line through the client's own send packet routine: to the party channel when
// the character is in a party, otherwise to everyone on the map.
//
// Party membership is tracked from party packets the client already receives;
// the module only reads them and never changes their dispatch.
#include "stdafx.h"
#include "NativeChatBroadcast.h"
#include "AgentBridge.h"

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace BeiDouBridge {
namespace NativeChatBroadcast {
namespace {

struct InPacket {
    bool loopback;
    int state;
    void* data;
    unsigned long size;
    unsigned short rawSeq;
    unsigned short dataLen;
    unsigned short unknown;
    unsigned int offset;
    void* unknownTail;
};

struct OutPacket {
    int loopback;

    union {
        unsigned char* data;
        void* unknown;
        unsigned short* header;
    };

    unsigned long size;
    unsigned int offset;
    int encryptedByShanda;
};

using SendPacketFn = void(__fastcall*)(void* socket, void* unused, OutPacket* packet);

// Client V17 addresses verified by the existing receive/send hooks.
constexpr std::uint32_t kClientSocketAddress = 0x00BE7914;
constexpr std::uint32_t kSendPacketAddress = 0x0049637B;

// Client-to-server opcodes from the server packet handlers.
constexpr unsigned short kGeneralChatOpcode = 0x0031;
constexpr unsigned short kMultiChatOpcode = 0x0077;
constexpr unsigned short kPartyOperationOpcode = 0x003E;
constexpr unsigned short kPartyMemberHpOpcode = 0x00C9;

constexpr unsigned char kPartyOperationCreated = 0x08;
constexpr unsigned char kPartyOperationInvite = 0x04;
constexpr unsigned char kPartyOperationJoin = 0x0F;
constexpr unsigned char kPartyOperationUpdate = 0x07; // silent update / log on-off
constexpr unsigned char kPartyOperationLeave = 0x0C;  // disband / leave / expel
constexpr unsigned char kPartyOperationLeader = 0x1B;

constexpr std::size_t kPartySlotCount = 6;
constexpr std::uint32_t kPollIntervalMs = 1000;
constexpr std::uint32_t kAnnounceIntervalMs = 2000;
constexpr std::size_t kMaxChatBytes = 120;
constexpr std::size_t kLogLimitBytes = 1024 * 1024;

SendPacketFn sendPacket = reinterpret_cast<SendPacketFn>(kSendPacketAddress);
bool partyActive = false;
std::string lastMode;
std::uint64_t lastPollAt = 0;
std::uint64_t lastAnnounceAt = 0;
bool announcedOnce = false;

std::string BridgeDirectory() {
    std::array<char, MAX_PATH> value{};
    const DWORD length = GetEnvironmentVariableA("MAPLE_BRIDGE_DIR", value.data(), static_cast<DWORD>(value.size()));
    if (length == 0 || length >= value.size()) return {};
    return std::string(value.data(), length);
}

// Announcement literals are CP936 for the chat packet; the log file is UTF-8
// like the rest of the bridge logs.
std::string Cp936ToUtf8(const std::string& text) {
    if (text.empty()) return {};
    const int wideCount =
        MultiByteToWideChar(936, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (wideCount <= 0) return {};
    std::wstring wide(wideCount, L'\0');
    MultiByteToWideChar(936, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), &wide[0], wideCount);
    const int utf8Count = WideCharToMultiByte(CP_UTF8, 0, wide.data(), wideCount, nullptr, 0, nullptr, nullptr);
    if (utf8Count <= 0) return {};
    std::string result(utf8Count, '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide.data(), wideCount, &result[0], utf8Count, nullptr, nullptr);
    return result;
}

std::string Timestamp() {
    SYSTEMTIME now{};
    GetLocalTime(&now);
    std::array<char, 64> text{};
    sprintf_s(text.data(), text.size(), "%04d-%02d-%02d %02d:%02d:%02d.%03d", static_cast<int>(now.wYear),
              static_cast<int>(now.wMonth), static_cast<int>(now.wDay), static_cast<int>(now.wHour),
              static_cast<int>(now.wMinute), static_cast<int>(now.wSecond), static_cast<int>(now.wMilliseconds));
    return std::string(text.data());
}

void AppendLog(const std::string& line) {
    const std::string directory = BridgeDirectory();
    if (directory.empty()) return;
    const std::string path = directory + "\\chat.log";
    WIN32_FILE_ATTRIBUTE_DATA attributes{};
    if (GetFileAttributesExA(path.c_str(), GetFileExInfoStandard, &attributes) && attributes.nFileSizeHigh == 0
        && attributes.nFileSizeLow > kLogLimitBytes) {
        DeleteFileA(path.c_str());
    }
    HANDLE file = CreateFileA(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    const std::string record = line + "\r\n";
    DWORD written = 0;
    WriteFile(file, record.data(), static_cast<DWORD>(record.size()), &written, nullptr);
    CloseHandle(file);
}

std::uint32_t ReadAt(const unsigned char* data, std::size_t size, std::size_t offset) {
    std::uint32_t value = 0;
    if (offset + sizeof(value) > size) return 0;
    std::memcpy(&value, data + offset, sizeof(value));
    return value;
}

bool SendPayload(const std::vector<unsigned char>& payload) {
    const auto socket = *reinterpret_cast<const std::uint32_t*>(kClientSocketAddress);
    if (socket == 0) return false;
    OutPacket packet{};
    packet.loopback = 0;
    packet.data = const_cast<unsigned char*>(payload.data());
    packet.size = static_cast<unsigned long>(payload.size());
    packet.offset = 0;
    packet.encryptedByShanda = 0;
    sendPacket(reinterpret_cast<void*>(socket), nullptr, &packet);
    return true;
}

void AppendU16(std::vector<unsigned char>& payload, std::size_t value) {
    payload.push_back(static_cast<unsigned char>(value & 0xFF));
    payload.push_back(static_cast<unsigned char>((value >> 8) & 0xFF));
}

void AppendBytes(std::vector<unsigned char>& payload, const std::string& value) {
    payload.insert(payload.end(), value.begin(), value.end());
}

// Server handlers read one string then (public chat) one style byte, or
// (multi chat) a recipient list. The party variant sends an empty recipient
// list: the server still broadcasts the text to every party member.
bool SendPublicChat(const std::string& cp936) {
    std::vector<unsigned char> payload;
    payload.push_back(static_cast<unsigned char>(kGeneralChatOpcode & 0xFF));
    payload.push_back(static_cast<unsigned char>((kGeneralChatOpcode >> 8) & 0xFF));
    AppendU16(payload, cp936.size());
    AppendBytes(payload, cp936);
    payload.push_back(0); // chat style
    return SendPayload(payload);
}

bool SendPartyChat(const std::string& cp936) {
    std::vector<unsigned char> payload;
    payload.push_back(static_cast<unsigned char>(kMultiChatOpcode & 0xFF));
    payload.push_back(static_cast<unsigned char>((kMultiChatOpcode >> 8) & 0xFF));
    payload.push_back(1); // type 1 = party
    payload.push_back(0); // recipient count: server broadcasts to the whole party
    AppendU16(payload, cp936.size());
    AppendBytes(payload, cp936);
    return SendPayload(payload);
}

// Reads the mode field from the bot state projection. The bot writes compact
// JSON with fixed key order; only this one value is needed.
std::string ReadBotMode() {
    HANDLE file =
        CreateFileA("Z:\\work\\bot\\state.json", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return {};
    std::array<char, 8192> buffer{};
    DWORD read = 0;
    const bool complete = ReadFile(file, buffer.data(), static_cast<DWORD>(buffer.size() - 1), &read, nullptr) != 0;
    CloseHandle(file);
    if (!complete) return {};
    buffer[read] = '\0';
    static const char* const key = "\"mode\":\"";
    const char* start = std::strstr(buffer.data(), key);
    if (start == nullptr) return {};
    start += std::strlen(key);
    const char* end = std::strchr(start, '"');
    if (end == nullptr) return {};
    return std::string(start, static_cast<std::size_t>(end - start));
}

// CP936 literals: the bridge is built with /execution-charset:.936, and the
// chat packet body is CP936 to match the server string decoder.
std::string ModeAnnouncement(const std::string& mode) {
    if (mode == "recover") return "策略切换：恢复中";
    if (mode == "idle") return "策略切换：待机";
    if (mode == "follow") return "策略切换：跟随中";
    if (mode == "hunt") return "策略切换：开始狩猎";
    if (mode == "dead") return "策略切换：死亡等待复活";
    return {};
}

bool Broadcast(const std::string& cp936) {
    if (cp936.empty() || cp936.size() > kMaxChatBytes) return false;
    return partyActive ? SendPartyChat(cp936) : SendPublicChat(cp936);
}

// Parses the six party slot CIDs that follow the packet header and checks
// whether the local character is still a member.
bool SelfInPartySlots(const unsigned char* data, std::size_t size, std::size_t offset) {
    const std::uint32_t self = AgentBridge::CurrentCharacterId();
    if (self == 0) return true;
    for (std::size_t slot = 0; slot < kPartySlotCount; ++slot) {
        if (offset + (slot + 1) * sizeof(std::uint32_t) > size) return true;
        if (ReadAt(data, size, offset + slot * sizeof(std::uint32_t)) == self) return true;
    }
    return false;
}

void HandlePartyOperation(const unsigned char* data, std::size_t size) {
    if (size < 7) return;
    const unsigned char type = data[6];
    switch (type) {
    case kPartyOperationCreated:
        partyActive = true;
        break;
    case kPartyOperationJoin: {
        // type, party id, joining name string, then six slot CIDs.
        std::size_t offset = 11;
        if (offset + 2 > size) return;
        const std::size_t nameLength =
            static_cast<std::size_t>(data[offset]) | (static_cast<std::size_t>(data[offset + 1]) << 8);
        offset += 2 + nameLength;
        partyActive = SelfInPartySlots(data, size, offset);
        break;
    }
    case kPartyOperationUpdate:
        // type, party id, then six slot CIDs.
        partyActive = SelfInPartySlots(data, size, 11);
        break;
    case kPartyOperationLeave: {
        // type, party id, target id, mode byte; mode 0 disbands the party.
        if (size < 16) return;
        if (data[15] == 0) {
            partyActive = false;
            break;
        }
        // mode 1: expel flag, target name string, then six slot CIDs.
        std::size_t offset = 17;
        if (offset + 2 > size) return;
        const std::size_t nameLength =
            static_cast<std::size_t>(data[offset]) | (static_cast<std::size_t>(data[offset + 1]) << 8);
        offset += 2 + nameLength;
        partyActive = SelfInPartySlots(data, size, offset);
        break;
    }
    case kPartyOperationLeader:
    case kPartyOperationInvite:
        break;
    default:
        break;
    }
}

void HandlePartyMemberHp(const unsigned char* data, std::size_t size) {
    if (size < 10) return;
    const std::uint32_t member = ReadAt(data, size, 6);
    if (member != 0 && member != AgentBridge::CurrentCharacterId()) partyActive = true;
}

} // namespace

void OnPacket(void* packet) {
    if (packet == nullptr) return;
    const auto* incoming = static_cast<const InPacket*>(packet);
    if (incoming->data == nullptr || incoming->size < 7) return;
    const auto* data = static_cast<const unsigned char*>(incoming->data);
    unsigned short opcode = 0;
    std::memcpy(&opcode, data + 4, sizeof(opcode));
    if (opcode != kPartyOperationOpcode && opcode != kPartyMemberHpOpcode) return;
    __try {
        const auto size = static_cast<std::size_t>(incoming->size);
        if (opcode == kPartyOperationOpcode)
            HandlePartyOperation(data, size);
        else
            HandlePartyMemberHp(data, size);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return;
    }
}

void Tick() {
    const auto now = static_cast<std::uint64_t>(GetTickCount64());
    if (lastPollAt != 0 && now - lastPollAt < kPollIntervalMs) return;
    lastPollAt = now;
    const std::string mode = ReadBotMode();
    if (mode.empty()) return;
    if (lastMode.empty()) {
        lastMode = mode;
        return;
    }
    if (mode == lastMode) return;
    lastMode = mode;
    if (announcedOnce && now - lastAnnounceAt < kAnnounceIntervalMs) return;
    const std::string announcement = ModeAnnouncement(mode);
    if (announcement.empty()) return;
    if (!Broadcast(announcement)) {
        AppendLog(Timestamp() + " strategy announcement skipped: send failed for mode " + mode);
        return;
    }
    lastAnnounceAt = now;
    announcedOnce = true;
    AppendLog(Timestamp() + " strategy announced: " + Cp936ToUtf8(announcement) + " [mode " + mode + ", party "
              + (partyActive ? "yes]" : "no]"));
}

} // namespace NativeChatBroadcast
} // namespace BeiDouBridge
