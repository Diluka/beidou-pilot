// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

namespace ms
{
// V17 Flash Jump impulse (docs/V17_EXTENDED_MOTION_RULES.md §5):
// 0x96BF52-0x96C04D builds ix = ±(350 + 40*q), iy = -250 - 20*q with
// q = trunc(skillLevel / 4) and queues it through the same 0x7A6353 impulse path
// as hurt knockback. The direction sign comes from the character facing/held
// direction; the native GUI rejected casts without a held left/right direction.
struct FlashJumpImpulse
{
    double vx = 0.0;
    double vy = 0.0;
};

// #254 Teleport: original 0x957B74 reads the skill-level `range` value from the
// skill data as its displacement distance; the GUI probe (2101002 level 15,
// range=140) moved +140px in the held direction. The 120ms pending state and
// platform/portal checks are not modeled here.
inline double TeleportTargetX(double currentX, int direction, int range)
{
    if (direction == 0 || range <= 0) return currentX;
    return currentX + static_cast<double>(direction * range);
}

inline FlashJumpImpulse FlashJumpImpulseForLevel(int skillLevel, int direction)
{
    if (skillLevel <= 0 || direction == 0) return {};
    const int q = skillLevel / 4;
    return {static_cast<double>(direction) * (350.0 + 40.0 * q), -250.0 - 20.0 * q};
}
}
