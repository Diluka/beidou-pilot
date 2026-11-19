// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <cstdint>

namespace headless {
constexpr int BeginnerSkillPointBudget(int level, int used) {
    return (level >= 7 ? 6 : level - 1) - used;
}

template <typename Requirements, typename Level>
bool SkillUpEligible(bool jobEligible, bool visible, bool forbidden, int maximum, int current,
                     int sp, std::uint64_t points, const Requirements& requirements, Level level) {
    if (!jobEligible || !visible || forbidden || maximum < current || sp < 0
        || points > static_cast<std::uint64_t>(maximum - current)
        || points > static_cast<std::uint64_t>(sp)) return false;
    for (const auto& required : requirements)
        if (level(required.first) < required.second) return false;
    return true;
}

}
