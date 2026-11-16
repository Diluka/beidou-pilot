// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

namespace ms
{
// Ground-monster walk force mapping for the Journey mob implementation.
//
// V17 dynamic evidence (docs/V17_EXTENDED_MOTION_RULES.md §4, 2026-11-17):
// the original client's controlled ground monsters moved at twice the speed of
// the Journey mapping for the same templates (木妖/黑木妖 template speed -70:
// 39.80 vs 19.92 px/s; 红蜗牛 -50: 59.76 vs 29.89 px/s). Journey used
// (raw+100)*0.001 as PhysicsObject::hforce; doubling the same mapping matches
// the observed original steady speed for these walking templates.
inline float MobWalkForceFromTemplate(float templateSpeed) {
    return (templateSpeed + 100.0f) * 0.002f;
}
}
