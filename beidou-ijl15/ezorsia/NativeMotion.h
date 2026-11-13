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

// Pure reads of the V17 VecCtrl state; call after the native character update.
// The movement result is an ordinary stationary-flat-ground continuous model,
// not the current terrain's attainable speed or an observed collision-free jump.
Observation Capture(std::uintptr_t user);

}
