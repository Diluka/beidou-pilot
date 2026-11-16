// SPDX-License-Identifier: AGPL-3.0-or-later
// V17 MovePlayer fragment velocity word contract (#259).
#include "Character/MovePlayerFragment.h"

#include <cstdlib>
#include <iostream>

namespace {
void Check(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}
}

int main() {
    Check(ms::MovePlayerFragmentVelocity(0.0) == 0, "zero");
    Check(ms::MovePlayerFragmentVelocity(125.0) == 125, "walk_speed");
    Check(ms::MovePlayerFragmentVelocity(-555.0) == -555, "jump_velocity");
    Check(ms::MovePlayerFragmentVelocity(124.6) == 125, "round_half_up");
    Check(ms::MovePlayerFragmentVelocity(-124.6) == -125, "round_half_up_negative");
    Check(ms::MovePlayerFragmentVelocity(1e9) == 32767, "clamp_high");
    Check(ms::MovePlayerFragmentVelocity(-1e9) == -32768, "clamp_low");
    std::cout << "ok\n";
    return 0;
}
