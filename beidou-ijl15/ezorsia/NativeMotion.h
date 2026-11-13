// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Runtime.h"

#include <cstdint>
#include <string>
#include <vector>

namespace NativeMotion {

struct Observation {
    MapleControl::MotionVector velocity;
    MapleControl::MovementReference movement;
    MapleControl::Fact onGround = MapleControl::Fact::Unknown;
    std::vector<std::string> unavailable;
};

// Only kinds with a proved object -> primary COM -> CVecCtrl chain belong here.
// Drop anchors and external Shape2D projectile vectors do not share this layout.
enum class EntityKind { LocalUser, RemoteUser, Mob, Npc };

// Pure reads of this entity's current world velocity in pixels/second. Invalid
// object/vector types or unreadable secure fields yield unknown, never zero.
// This does not read character ability attributes or grounding for other kinds.
MapleControl::MotionVector CaptureVelocity(EntityKind kind, std::uintptr_t object);

// Local-character-only fact groups remain independent on read failures. The
// movement reference is an ordinary stationary-flat-ground continuous model,
// not the current terrain's attainable speed or an observed collision-free jump.
Observation Capture(std::uintptr_t user);

}
