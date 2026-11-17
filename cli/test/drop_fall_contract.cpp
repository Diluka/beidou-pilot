// SPDX-License-Identifier: AGPL-3.0-or-later
// V17 drop falling display contract (docs/V17_EXTENDED_MOTION_RULES.md §9).
#include "Gameplay/MapleMap/DropFallDisplay.h"

#include <cmath>
#include <cstdlib>
#include <iostream>

namespace {
constexpr double V400 = ms::DropFallVelocity;
constexpr double V720 = ms::DropFallVelocityPickupTypeThree;

void Near(double actual, double expected, const char* message) {
    if (std::fabs(actual - expected) > 1e-6) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}
}

int main() {
    // Static formula: u=min(0.002*m,1); w=0 (m<=500) or (m-500)/500; x follows
    // (u+w)/2; y = y0 - v*t + 400t^2; D=1000 (dynamic landed latency evidence).
    Near(ms::DropFallX(0.0, 100.0, 0), 0.0, "x_at_0");
    Near(ms::DropFallX(0.0, 100.0, 250), 25.0, "x_at_250");
    Near(ms::DropFallX(0.0, 100.0, 500), 50.0, "x_at_500");
    Near(ms::DropFallX(0.0, 100.0, 1000), 100.0, "x_at_duration");
    // D from 0x5064FF: 1000ms normally, 1800ms when pickuptype==3 (v=720 branch).
    Near(ms::DropFallDurationForPickupType(3), 1800.0, "pickup_type_three_duration_1800");
    Near(ms::DropFallDurationForPickupType(0), 1000.0, "pickup_type_zero_duration_1000");
    Near(ms::DropFallDurationForPickupType(2), 1000.0, "pickup_type_two_duration_1000");
    Near(ms::DropFallX(0.0, 100.0, 1150, 1800), 75.0, "x_1150_of_1800_duration");
    Near(ms::DropFallX(0.0, 100.0, 1800, 1800), 100.0, "x_at_1800_duration");

    Near(ms::DropFallY(200.0, 0, V400), 200.0, "y_at_0");
    Near(ms::DropFallY(200.0, 250, V400), 125.0, "y_at_250");
    Near(ms::DropFallY(200.0, 500, V400), 100.0, "y_at_500");
    Near(ms::DropFallY(200.0, 1000, V400), 200.0, "y_at_duration");

    Near(ms::DropDescendY(200.0, 0, V400), 200.0, "descend_at_0");
    Near(ms::DropDescendY(200.0, 250, V400), 300.0, "descend_at_250");

    // drop+0x2C == 3 selects v=720; the field is the DropLoot pickuptype byte.
    Near(ms::DropFallVelocityForPickupType(3), 720.0, "pickup_type_three_uses_720");
    Near(ms::DropFallVelocityForPickupType(0), 400.0, "pickup_type_zero_uses_400");
    Near(ms::DropFallVelocityForPickupType(2), 400.0, "pickup_type_two_uses_400");
    Near(ms::DropFallY(200.0, 250, V720), 45.0, "y720_at_250");
    Near(ms::DropDescendY(200.0, 250, V720), 380.0, "descend720_at_250");

    if (!ms::DropFallNeedsDescent(100.0, 200.0)) {
        std::cerr << "start_above_anchor_needs_descent\n";
        return 1;
    }
    if (ms::DropFallNeedsDescent(200.0, 100.0)) {
        std::cerr << "start_below_anchor_lands_without_descent\n";
        return 1;
    }

    std::cout << "ok\n";
    return 0;
}
