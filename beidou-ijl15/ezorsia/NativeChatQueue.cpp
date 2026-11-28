// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Outgoing chat queue.
//
// Chats go through the client's own send routine. The server drops a second
// chat packet that arrives within 200 ms of the previous one, so callers only
// enqueue and this queue paces delivery. The gap also keeps unrelated replies
// (whispers, announcements) from cancelling each other under the server
// throttle.
#include "stdafx.h"
#include "NativeChatQueue.h"

#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <string>
#include <utility>
#include <vector>

namespace BeiDouBridge {
namespace NativeChatQueue {
namespace {

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

// Client-to-server chat opcodes from the server packet handlers.
constexpr unsigned short kGeneralChatOpcode = 0x0031;
constexpr unsigned short kMultiChatOpcode = 0x0077;
constexpr unsigned short kWhisperSendOpcode = 0x0078;
constexpr unsigned char kWhisperSendFlag = 0x02 | 0x04; // whisper | request

// The server validates string length in characters; at two bytes per CJK
// character this byte cap stays well below its 127-character limit.
constexpr std::size_t kMaxTextBytes = 120;
constexpr std::size_t kMaxQueueLength = 64;
// Safety margin above the server's 200 ms chat throttle.
constexpr std::uint64_t kSendIntervalMs = 250;

SendPacketFn sendPacket = reinterpret_cast<SendPacketFn>(kSendPacketAddress);

struct Entry {
    Channel channel = Channel::Public;
    std::string text;
    std::string target;
};

std::deque<Entry> queue;
std::uint64_t lastSendAt = 0;

void AppendU16(std::vector<unsigned char>& payload, std::size_t value) {
    payload.push_back(static_cast<unsigned char>(value & 0xFF));
    payload.push_back(static_cast<unsigned char>((value >> 8) & 0xFF));
}

void AppendBytes(std::vector<unsigned char>& payload, const std::string& value) {
    payload.insert(payload.end(), value.begin(), value.end());
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

// Server handlers read one string then a style byte (public chat), a recipient
// list (party chat) or a target string (whisper). The party variant sends an
// empty recipient list: the server still broadcasts to every party member.
bool SendEntry(const Entry& entry) {
    std::vector<unsigned char> payload;
    switch (entry.channel) {
    case Channel::Public:
        payload.push_back(static_cast<unsigned char>(kGeneralChatOpcode & 0xFF));
        payload.push_back(static_cast<unsigned char>((kGeneralChatOpcode >> 8) & 0xFF));
        AppendU16(payload, entry.text.size());
        AppendBytes(payload, entry.text);
        payload.push_back(0); // chat style
        break;
    case Channel::Party:
        payload.push_back(static_cast<unsigned char>(kMultiChatOpcode & 0xFF));
        payload.push_back(static_cast<unsigned char>((kMultiChatOpcode >> 8) & 0xFF));
        payload.push_back(1); // type 1 = party
        payload.push_back(0); // recipient count: server broadcasts to the whole party
        AppendU16(payload, entry.text.size());
        AppendBytes(payload, entry.text);
        break;
    case Channel::Whisper:
        payload.push_back(static_cast<unsigned char>(kWhisperSendOpcode & 0xFF));
        payload.push_back(static_cast<unsigned char>((kWhisperSendOpcode >> 8) & 0xFF));
        payload.push_back(kWhisperSendFlag);
        AppendU16(payload, entry.target.size());
        AppendBytes(payload, entry.target);
        AppendU16(payload, entry.text.size());
        AppendBytes(payload, entry.text);
        break;
    }
    return SendPayload(payload);
}

} // namespace

bool Enqueue(Channel channel, const std::string& cp936Text, const std::string& cp936WhisperTarget) {
    if (cp936Text.empty() || cp936Text.size() > kMaxTextBytes) return false;
    if (channel == Channel::Whisper && cp936WhisperTarget.empty()) return false;
    if (queue.size() >= kMaxQueueLength) return false;
    Entry entry;
    entry.channel = channel;
    entry.text = cp936Text;
    entry.target = cp936WhisperTarget;
    queue.push_back(std::move(entry));
    return true;
}

void Tick() {
    if (queue.empty()) return;
    const auto now = static_cast<std::uint64_t>(GetTickCount64());
    if (lastSendAt != 0 && now - lastSendAt < kSendIntervalMs) return;
    Entry entry = std::move(queue.front());
    queue.pop_front();
    if (SendEntry(entry)) lastSendAt = now;
}

} // namespace NativeChatQueue
} // namespace BeiDouBridge
