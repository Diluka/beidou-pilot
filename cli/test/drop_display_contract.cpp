// SPDX-License-Identifier: AGPL-3.0-or-later
// V17 floating drop display contract (docs/V17_EXTENDED_MOTION_RULES.md §9).
#include "Gameplay/MapleMap/DropDisplay.h"

#include <cmath>
#include <cstdlib>
#include <iostream>

namespace {
constexpr float PI = 3.14159265358979323846f;

void Near(float actual, float expected, const char* message, float tolerance = 1e-5f) {
    if (std::fabs(actual - expected) > tolerance) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}
}

int main() {
    // Preserve the original angular rate (0.0942477 per 30ms = π rad/s).
    Near(ms::DropFloatingPhasePerWorldStep() * 125.0f, PI, "phase_rate_rad_per_second");
    Near(ms::DropFloatingPhasePerWorldStep() * 3.75f, 0.0942477f, "phase_per_30ms");

    Near(ms::DropFloatingOffsetY(0.0f), 0.0f, "offset_0");
    Near(ms::DropFloatingOffsetY(PI * 0.5f), 3.0f, "offset_quarter");
    Near(ms::DropFloatingOffsetY(PI), 0.0f, "offset_half");
    Near(ms::DropFloatingOffsetY(PI * 1.5f), -3.0f, "offset_three_quarter");

    // Phase wraps at 2π instead of growing without bound.
    const float near_two_pi = 6.28f;
    float phase = near_two_pi;
    for (int i = 0; i < 10; ++i) phase = ms::DropFloatingNextPhase(phase);
    if (phase < 0.0f || phase >= 2.0f * PI) {
        std::cerr << "phase_wrap: phase=" << phase << '\n';
        return 1;
    }

    std::cout << "ok\n";
    return 0;
}
