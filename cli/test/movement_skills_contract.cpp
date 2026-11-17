// SPDX-License-Identifier: AGPL-3.0-or-later
// V17 movement-skill impulse contract (docs/V17_EXTENDED_MOTION_RULES.md §5).
#include "Gameplay/MovementSkills.h"

#include <cmath>
#include <cstdlib>
#include <iostream>

namespace {
void Near(double actual, double expected, const char* message) {
    if (std::fabs(actual - expected) > 1e-9) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}

void CheckZero(const ms::FlashJumpImpulse& impulse, const char* message) {
    if (impulse.vx != 0.0 || impulse.vy != 0.0) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}
}

int main() {
    // q = trunc(level/4); ix = ±(350+40q), iy = -(250+20q).
    const auto level20Right = ms::FlashJumpImpulseForLevel(20, 1);
    Near(level20Right.vx, 550.0, "level20_right_vx");
    Near(level20Right.vy, -350.0, "level20_right_vy");

    const auto level20Left = ms::FlashJumpImpulseForLevel(20, -1);
    Near(level20Left.vx, -550.0, "level20_left_vx");
    Near(level20Left.vy, -350.0, "level20_left_vy");

    const auto level3 = ms::FlashJumpImpulseForLevel(3, 1); // q=0
    Near(level3.vx, 350.0, "level3_vx");
    Near(level3.vy, -250.0, "level3_vy");

    const auto level4 = ms::FlashJumpImpulseForLevel(4, 1); // q=1
    Near(level4.vx, 390.0, "level4_vx");
    Near(level4.vy, -270.0, "level4_vy");

    CheckZero(ms::FlashJumpImpulseForLevel(0, 1), "level_zero_is_invalid");
    CheckZero(ms::FlashJumpImpulseForLevel(20, 0), "no_direction_is_invalid");

    // Teleport target uses the skill level `range` value (2101002 level 15 = 140).
    Near(ms::TeleportTargetX(100.0, 1, 140), 240.0, "teleport_right_range");
    Near(ms::TeleportTargetX(100.0, -1, 140), -40.0, "teleport_left_range");
    Near(ms::TeleportTargetX(100.0, 1, 0), 100.0, "teleport_zero_range_keeps_position");
    Near(ms::TeleportTargetX(100.0, 0, 140), 100.0, "teleport_no_direction_keeps_position");

    std::cout << "ok\n";
    return 0;
}
