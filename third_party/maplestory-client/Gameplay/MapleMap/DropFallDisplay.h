// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <algorithm>
#include <cstdint>

namespace ms
{
// V17 drop falling display (docs/V17_EXTENDED_MOTION_RULES.md §9, state1/state2):
// m is the drop's 30ms-stepped millisecond counter; D is the state1 duration.
// The GUI lifecycle evidence (2026-11-17, 15 drops) showed landed at 1.009-1.06s
// after spawn regardless of item type, so D is treated as the fixed 1000ms.
// Static formula: u=min(0.002*m,1); w=0 (m<=500) or min((m-500)/(D-500),1);
// x = x0 + (xd-x0)*(u+w)/2; y = y0 - v*t + 400*t*t. The v selection uses
// drop+0x2C == 3 (0x504C66); that field is written from the DropLoot packet's
// pickuptype byte at 0x5059E1 (read byte 0x4065F3 -> [edi+0x2C], after
// mode/oid/byte/int/int in 0x50592D-0x5059EB), i.e. v=720 for pickuptype 3.
constexpr int32_t DropFallDurationMs = 1000;
constexpr double DropFallVelocity = 400.0;
constexpr double DropFallVelocityPickupTypeThree = 720.0;

inline double DropFallVelocityForPickupType(int8_t pickuptype) {
    return pickuptype == 3 ? DropFallVelocityPickupTypeThree : DropFallVelocity;
}

inline double DropFallX(double startX, double anchorX, int32_t m) {
    const double ms = static_cast<double>(m);
    const double u = std::min(0.002 * ms, 1.0);
    const double w = m <= 500 ? 0.0 : std::min((ms - 500.0) / (DropFallDurationMs - 500.0), 1.0);
    return startX + (anchorX - startX) * (u + w) / 2.0;
}

inline double DropFallY(double startY, int32_t m, double velocity) {
    const double t = static_cast<double>(m) / 1000.0;
    return startY - velocity * t + 400.0 * t * t;
}

// state2: after D the display descends from the start point at constant v.
inline double DropDescendY(double startY, int32_t m, double velocity) {
    const double t = static_cast<double>(m) / 1000.0;
    return startY + velocity * t;
}

inline bool DropFallNeedsDescent(double startY, double anchorY) {
    return startY < anchorY;
}
}
