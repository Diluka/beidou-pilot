// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <string>

namespace BeiDouBridge {
namespace NativeChatQueue {

enum class Channel { Public, Party, Whisper };

// Queues one chat line for delivery through the client's native send routine.
//
// Callers never deal with the server throttle: the queue drains in FIFO order
// with a safe gap between packets, because the server drops a second chat
// packet that arrives within 200 ms of the previous one. Texts are CP936, the
// packet string encoding used by the server.
//
// whisperTarget is the recipient name in CP936 and is only used for Channel::Whisper.
// Returns false when the text is too long or the queue is full.
bool Enqueue(Channel channel, const std::string& cp936Text, const std::string& cp936WhisperTarget = {});

// Drains at most one queued line per call when the throttle window has passed.
// Must be called from the game update thread.
void Tick();

} // namespace NativeChatQueue
} // namespace BeiDouBridge
