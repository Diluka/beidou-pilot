// SPDX-License-Identifier: AGPL-3.0-or-later
// V17 MOVE_PLAYER tail bounding box contract (#259).
#include "Character/MovePlayerBounds.h"

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
    const auto forward = ms::MovePlayerPathBounds(ms::Point<int16_t>(10, 20), ms::Point<int16_t>(30, 5));
    Check(forward.minX == 10 && forward.maxX == 30, "forward_x");
    Check(forward.minY == 5 && forward.maxY == 20, "forward_y");

    const auto backward = ms::MovePlayerPathBounds(ms::Point<int16_t>(-4, 8), ms::Point<int16_t>(-9, 3));
    Check(backward.minX == -9 && backward.maxX == -4, "backward_x");
    Check(backward.minY == 3 && backward.maxY == 8, "backward_y");

    const auto still = ms::MovePlayerPathBounds(ms::Point<int16_t>(7, 7), ms::Point<int16_t>(7, 7));
    Check(still.minX == still.maxX && still.minY == still.maxY, "stationary");
    std::cout << "ok\n";
    return 0;
}
