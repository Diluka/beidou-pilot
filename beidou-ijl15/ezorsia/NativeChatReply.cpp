// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Native whisper location reply.
//
// The client dispatches every decoded channel packet through one routine. The
// whisper opcode is part of the field packet set, so an incoming whisper passes
// that routine before the field handler. This module only reads the packet,
// recognizes the whisper-receive form, and answers a location question through
// the client's own send packet routine. It never changes the packet or the
// client's dispatch order.
#include "stdafx.h"
#include "NativeChatReply.h"
#include "AgentBridge.h"

#include "../../shared/img/ImgResources.h"

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace BeiDouBridge {
namespace NativeChatReply {
namespace {

// Decoded packet view matching the client's CInPacket layout used by the
// existing receive hook. The decoded buffer starts with a four-byte channel
// frame header; the two-byte opcode follows it and the payload starts at
// Data + 6.
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

// Client V17 addresses verified by the existing receive and send hooks.
constexpr std::uint32_t kClientSocketAddress = 0x00BE7914;
constexpr std::uint32_t kSendPacketAddress = 0x0049637B;

constexpr unsigned short kWhisperReceiveOpcode = 0x0087;
constexpr unsigned short kWhisperSendOpcode = 0x0078;
constexpr unsigned char kWhisperReceiveFlag = 0x02 | 0x10; // whisper | receive
constexpr unsigned char kWhisperSendFlag = 0x02 | 0x04;    // whisper | request

constexpr std::uint32_t kMinimumReplyIntervalMilliseconds = 1500;
constexpr std::size_t kLogLimitBytes = 1024 * 1024;

SendPacketFn sendPacket = reinterpret_cast<SendPacketFn>(kSendPacketAddress);
std::uint32_t lastReplyAt = 0;
bool repliedOnce = false;

std::string DataRoot() {
    std::array<char, MAX_PATH> value{};
    const DWORD length = GetEnvironmentVariableA("MAPLE_DATA_ROOT", value.data(), static_cast<DWORD>(value.size()));
    if (length == 0 || length >= value.size()) return {};
    return std::string(value.data(), length);
}

std::string BridgeDirectory() {
    std::array<char, MAX_PATH> value{};
    const DWORD length = GetEnvironmentVariableA("MAPLE_BRIDGE_DIR", value.data(), static_cast<DWORD>(value.size()));
    if (length == 0 || length >= value.size()) return {};
    return std::string(value.data(), length);
}

std::string GbkToUtf8(const std::string& text) {
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

std::string Utf8ToGbk(const std::string& text) {
    if (text.empty()) return {};
    const int wideCount =
        MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (wideCount <= 0) return {};
    std::wstring wide(wideCount, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), &wide[0], wideCount);
    const int gbkCount = WideCharToMultiByte(936, 0, wide.data(), wideCount, nullptr, 0, nullptr, nullptr);
    if (gbkCount <= 0) return {};
    std::string result(gbkCount, '\0');
    WideCharToMultiByte(936, 0, wide.data(), wideCount, &result[0], gbkCount, nullptr, nullptr);
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

struct MapNames {
    std::string mapName;
    std::string streetName;
};

// Reads mapName/streetName from the local String/Map resource. The IMG decoder
// returns UTF-8 text. A missing resource, id or property yields an empty name
// and the caller falls back to the map id.
MapNames ReadMapNames(std::uint32_t mapId) {
    MapNames result;
    const std::string root = DataRoot();
    if (root.empty() || mapId == 0) return result;
    const std::string path = root + "\\String\\Map.img";
    std::array<char, 512> message{};
    BeidouImgDirectory* opened = nullptr;
    if (!beidou_img_file_open(path.c_str(), &opened, message.data(), message.size())) return result;
    const std::unique_ptr<BeidouImgDirectory, decltype(&beidou_img_directory_close)> image(opened,
                                                                                           beidou_img_directory_close);
    BeidouImgNodeInfo imageRoot{};
    if (!beidou_img_directory_node(image.get(), 0, &imageRoot)) return result;
    const std::string key = std::to_string(mapId);
    for (std::uint32_t index = imageRoot.children; index < imageRoot.children + imageRoot.child_count; ++index) {
        BeidouImgNodeInfo node{};
        if (!beidou_img_directory_node(image.get(), index, &node)) continue;
        std::size_t nameLength = 0;
        const char* name = beidou_img_directory_string(image.get(), node.name_string_id, &nameLength);
        if (name == nullptr || std::string(name, nameLength) != key) continue;
        for (std::uint32_t child = node.children; child < node.children + node.child_count; ++child) {
            BeidouImgNodeInfo property{};
            if (!beidou_img_directory_node(image.get(), child, &property)) continue;
            if (property.type != BEIDOU_IMG_NODE_STRING) continue;
            std::size_t propertyNameLength = 0;
            const char* propertyName =
                beidou_img_directory_string(image.get(), property.name_string_id, &propertyNameLength);
            std::size_t valueLength = 0;
            const char* value = beidou_img_directory_string(image.get(), property.value_string_id, &valueLength);
            if (propertyName == nullptr || value == nullptr) continue;
            const std::string propertyString(propertyName, propertyNameLength);
            if (propertyString == "mapName")
                result.mapName.assign(value, valueLength);
            else if (propertyString == "streetName")
                result.streetName.assign(value, valueLength);
        }
        break;
    }
    return result;
}

std::string MapDescription(std::uint32_t mapId) {
    static std::unordered_map<std::uint32_t, std::string> cache;
    const auto cached = cache.find(mapId);
    if (cached != cache.end()) return cached->second;
    const MapNames names = ReadMapNames(mapId);
    std::string description;
    if (!names.mapName.empty() && !names.streetName.empty() && names.streetName != names.mapName)
        description = names.mapName + " (" + names.streetName + ")";
    else if (!names.mapName.empty())
        description = names.mapName;
    else if (!names.streetName.empty())
        description = names.streetName;
    else
        description = "map " + std::to_string(mapId);
    cache[mapId] = description;
    return description;
}

bool ContainsKeyword(const std::string& text, const char* keyword) {
    return text.find(keyword) != std::string::npos;
}

// Answers only questions about the local character's location. The bridge is
// built with /execution-charset:.936, so the Chinese keywords below are CP936
// bytes; match them against the raw CP936 message body instead of its UTF-8
// projection. ASCII matching ignores case so the keyword list stays small.
bool AsksLocation(const std::string& cp936) {
    static const char* const keywords[] = {"在哪", "哪里", "哪儿",  "什么地方", "什么图",    "哪张图",  "哪个图",
                                           "位置", "坐标", "where", "location", "which map", "what map"};
    std::string lowered = cp936;
    for (char& character : lowered)
        if (character >= 'A' && character <= 'Z') character = static_cast<char>(character - 'A' + 'a');
    for (const char* keyword : keywords) {
        std::string loweredKeyword(keyword);
        for (char& character : loweredKeyword)
            if (character >= 'A' && character <= 'Z') character = static_cast<char>(character - 'A' + 'a');
        if (ContainsKeyword(lowered, loweredKeyword.c_str())) return true;
    }
    return false;
}

bool ReadString(const unsigned char* data, std::size_t size, std::size_t& offset, std::string& value) {
    if (offset + 2 > size) return false;
    const std::size_t length =
        static_cast<std::size_t>(data[offset]) | (static_cast<std::size_t>(data[offset + 1]) << 8);
    offset += 2;
    if (offset + length > size) return false;
    value.assign(reinterpret_cast<const char*>(data + offset), length);
    offset += length;
    return true;
}

bool AppendString(std::vector<unsigned char>& payload, const std::string& value) {
    if (value.size() > 0xFFFF) return false;
    payload.reserve(payload.size() + 2 + value.size());
    payload.push_back(static_cast<unsigned char>(value.size() & 0xFF));
    payload.push_back(static_cast<unsigned char>((value.size() >> 8) & 0xFF));
    payload.insert(payload.end(), value.begin(), value.end());
    return true;
}

bool SendWhisper(const std::string& target, const std::string& message) {
    if (target.empty() || message.empty()) return false;
    const auto socket = *reinterpret_cast<const std::uint32_t*>(kClientSocketAddress);
    if (socket == 0) return false;
    std::vector<unsigned char> payload;
    payload.push_back(static_cast<unsigned char>(kWhisperSendOpcode & 0xFF));
    payload.push_back(static_cast<unsigned char>((kWhisperSendOpcode >> 8) & 0xFF));
    payload.push_back(kWhisperSendFlag);
    if (!AppendString(payload, target) || !AppendString(payload, message)) return false;
    OutPacket packet{};
    packet.loopback = 0;
    packet.data = payload.data();
    packet.size = static_cast<unsigned long>(payload.size());
    packet.offset = 0;
    packet.encryptedByShanda = 0;
    sendPacket(reinterpret_cast<void*>(socket), nullptr, &packet);
    return true;
}

void HandleReceiveWhisper(const unsigned char* data, std::size_t size) {
    std::size_t offset = 6;
    if (offset >= size) return;
    const unsigned char flag = data[offset];
    offset += 1;
    if (flag != kWhisperReceiveFlag) return;
    std::string sender;
    if (!ReadString(data, size, offset, sender)) return;
    if (offset + 2 > size) return;
    offset += 2; // channel and admin flag; not needed for the reply
    std::string message;
    if (!ReadString(data, size, offset, message)) return;
    const std::string senderUtf8 = GbkToUtf8(sender);
    const std::string messageUtf8 = GbkToUtf8(message);
    AppendLog(Timestamp() + " whisper from " + (senderUtf8.empty() ? sender : senderUtf8) + ": " + messageUtf8);
    if (!AsksLocation(message)) return;
    const std::uint32_t mapId = AgentBridge::CurrentMapId();
    if (mapId == 0) {
        AppendLog(Timestamp() + " location reply skipped: current map unknown");
        return;
    }
    const std::uint32_t now = static_cast<std::uint32_t>(GetTickCount());
    if (repliedOnce && now - lastReplyAt < kMinimumReplyIntervalMilliseconds) {
        AppendLog(Timestamp() + " location reply skipped: rate limited");
        return;
    }
    // The literal prefix is CP936 at build time; the map text from the IMG
    // decoder is UTF-8, so convert that half and concatenate CP936 bytes.
    const std::string description = Utf8ToGbk(MapDescription(mapId));
    if (description.empty()) {
        AppendLog(Timestamp() + " location reply skipped: map name encoding failed");
        return;
    }
    const std::string replyGbk = "我在" + description;
    if (!SendWhisper(sender, replyGbk)) {
        AppendLog(Timestamp() + " location reply skipped: send failed");
        return;
    }
    lastReplyAt = now;
    repliedOnce = true;
    AppendLog(Timestamp() + " location reply sent to " + senderUtf8 + ": " + GbkToUtf8(replyGbk) + " [map "
              + std::to_string(mapId) + "]");
}

} // namespace

void OnPacket(void* packet) {
    if (packet == nullptr) return;
    const auto* incoming = static_cast<const InPacket*>(packet);
    if (incoming->data == nullptr || incoming->size < 8) return;
    const auto* data = static_cast<const unsigned char*>(incoming->data);
    unsigned short opcode = 0;
    std::memcpy(&opcode, data + 4, sizeof(opcode));
    if (opcode != kWhisperReceiveOpcode) return;
    __try {
        HandleReceiveWhisper(data, static_cast<std::size_t>(incoming->size));
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return;
    }
}

} // namespace NativeChatReply
} // namespace BeiDouBridge
