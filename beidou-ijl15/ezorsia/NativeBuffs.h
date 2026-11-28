// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"

#include <cstdint>
#include <string>

namespace BeiDouBridge {
namespace NativeBuffs {

// Reads one decoded packet before the client dispatches it. Tracks the local
// character's temporary stats from the server's GIVE_BUFF / CANCEL_BUFF
// packets; the packet is only read, the caller still dispatches it.
void OnPacket(void* packet);

// Current buffs as an observation value (array of objects). Remaining time is
// derived from the server-sent duration.
MapleControl::Value Snapshot();

// GBK summary for chat replies, e.g. "2 个：攻击/移动速度", or "0 个".
std::string Summary();

} // namespace NativeBuffs
} // namespace BeiDouBridge
