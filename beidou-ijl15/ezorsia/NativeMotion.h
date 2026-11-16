// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"

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

// One whole local-character physics sample and the local user it was recorded
// from. The position, velocity and grounding of one record always come from the
// same verified VecCtrl and the same native update.
struct LocalPhysics {
    std::uintptr_t user = 0;
    MapleControl::PhysicsPose pose;
};

// Reads the physical position (VecCtrl +0x20/+0x38), world velocity
// (+0x50/+0x68) and grounding (+0x110) from the same verified primary vector.
// While the ladder/rope association (+0x124, 0x9CC0F5) is non-zero the velocity
// stays unknown: the original climb branch moves only y and the grab path clears
// the world velocity fields.
// Positions are not rounded or interpolated. Recoverable read failures leave the
// affected fact unknown; an unreadable primary vector leaves the whole record
// unknown. updateId is the real character-update identity of the sample and the
// fixed V17 logic step is the sample's integration time, not a publish interval.
MapleControl::PhysicsPose CapturePhysics(std::uintptr_t user, std::uint64_t updateId);

// Samples one whole physics record after a real native character update. Later
// host render frames and CLI reads reuse this record instead of re-reading pose
// fields at another point in time.
void RecordLocalPhysics(std::uintptr_t user, std::uint64_t updateId);

// Last recorded sample. Callers match user against the current local user; the
// record's updateId was captured together with its fields.
const LocalPhysics& CachedLocalPhysics();

}
