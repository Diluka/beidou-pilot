// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

namespace BeiDouBridge {
namespace NativeChatBroadcast {

// Tracks party membership from party packets so broadcasts can use the party
// channel only while the character is in a party. Read-only.
void OnPacket(void* packet);

// Called from the game update hook. Polls the bot state file at a low
// frequency and broadcasts one chat line when the strategy mode changes.
void Tick();

} // namespace NativeChatBroadcast
} // namespace BeiDouBridge
