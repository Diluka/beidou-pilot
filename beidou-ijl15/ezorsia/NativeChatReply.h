// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

namespace BeiDouBridge {
namespace NativeChatReply {

// Reads one decoded incoming packet before the client dispatches it. When the
// packet is an incoming whisper that asks for the local character's location,
// replies to the sender with the current map name through the client's own
// send packet routine. The packet is only read; the caller keeps ownership and
// still dispatches it.
void OnPacket(void* packet);

} // namespace NativeChatReply
} // namespace BeiDouBridge
