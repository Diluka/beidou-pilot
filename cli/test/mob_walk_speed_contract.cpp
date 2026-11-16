// SPDX-License-Identifier: AGPL-3.0-or-later
// Ground-monster walk force mapping contract for the #253 dynamic evidence.
#include "Gameplay/MapleMap/MobWalkSpeed.h"

#include <cmath>
#include <cstdlib>
#include <iostream>

namespace {
void Near(float actual, float expected, const char* message) {
    if (std::fabs(actual - expected) > 1e-6f) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}
}

int main() {
    // Observed original templates: -70 -> 39.8px/s, -50 -> 59.76px/s in the
    // Journey physics; the aligned mapping doubles the legacy (raw+100)*0.001.
    Near(ms::MobWalkForceFromTemplate(-70.0f), 0.06f, "template_minus_70");
    Near(ms::MobWalkForceFromTemplate(-50.0f), 0.10f, "template_minus_50");
    Near(ms::MobWalkForceFromTemplate(-100.0f), 0.0f, "zero_force_template");
    Near(ms::MobWalkForceFromTemplate(0.0f), 0.20f, "zero_template_speed");
    std::cout << "ok\n";
    return 0;
}
