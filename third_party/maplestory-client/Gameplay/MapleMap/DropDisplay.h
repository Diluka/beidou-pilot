// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "../../Constants.h"

#include <cmath>

namespace ms
{
// V17 floating drop display (docs/V17_EXTENDED_MOTION_RULES.md §9, state3
// 0x504D98-0x504E62): the displayed y is yd + 3*sin(phase) and the phase
// advances 0.0942477 per 30ms update (~π rad/s, 2s period). The headless world
// runs an 8ms timestep, so the angular rate is preserved per unit time.
inline float DropFloatingPhasePerWorldStep() {
    constexpr float PHASE_PER_30MS = 0.0942477f;
    return PHASE_PER_30MS * (static_cast<float>(Constants::TIMESTEP) / 30.0f);
}

inline float DropFloatingOffsetY(float phase) {
    return 3.0f * std::sin(phase);
}

inline float DropFloatingNextPhase(float phase) {
    constexpr float TWO_PI = 6.28318530717958647692f;
    const float next = phase + DropFloatingPhasePerWorldStep();
    return next >= TWO_PI ? next - TWO_PI : next;
}
}
