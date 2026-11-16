// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace ms
{
// V17 MovePlayer fragment 0 velocity words (docs/V17_EXTENDED_MOTION_RULES.md §10:
// the words headless calls lastx/lasty are the endpoint vx/vy in px/s; creator
// 0x9B108A reads the VecCtrl x/y/vx/vy secure doubles and integerizes them).
inline int16_t MovePlayerFragmentVelocity(double pixelsPerSecond) {
    const double rounded = std::round(pixelsPerSecond);
    const double clamped = std::clamp(rounded, -32768.0, 32767.0);
    return static_cast<int16_t>(clamped);
}
}
