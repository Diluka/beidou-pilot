// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <cstdint>

namespace headless {
constexpr bool UnsupportedBeginnerSkill(std::int32_t skill) {
    const auto group = skill / 10000;
    return group == 1000 || group == 2000 || group == 2001;
}

constexpr bool UnsupportedSkillPointBook(std::int32_t skill) {
    const auto group = skill / 10000;
    return group >= 2210 && group <= 2218;
}

constexpr bool UnsupportedSkillAllocation(std::int32_t skill, int job) {
    return job == 2001 || (job >= 2200 && job <= 2218)
        || UnsupportedBeginnerSkill(skill) || UnsupportedSkillPointBook(skill);
}

constexpr bool ServerFourthJobSkill(std::int32_t skill) {
    if (skill == 22170001 || skill == 22171003 || skill == 22171004 || skill == 22181002 || skill == 22181003)
        return true;
    const auto group = skill / 10000;
    return group != 2212 && group % 10 == 2;
}

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
