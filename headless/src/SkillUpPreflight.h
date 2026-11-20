// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <cstdint>

namespace headless {
constexpr int BeginnerGroup(int job) {
    switch (job) {
    case 0: case 100: case 110: case 111: case 112: case 120: case 121: case 122:
    case 130: case 131: case 132: case 200: case 210: case 211: case 212:
    case 220: case 221: case 222: case 230: case 231: case 232: case 300:
    case 310: case 311: case 312: case 320: case 321: case 322: case 400:
    case 410: case 411: case 412: case 420: case 421: case 422: case 500:
    case 510: case 511: case 512: case 520: case 521: case 522: return 0;
    case 1000: case 1100: case 1110: case 1111: case 1112: case 1200:
    case 1210: case 1211: case 1212: case 1300: case 1310: case 1311:
    case 1312: case 1400: case 1410: case 1411: case 1412: case 1500:
    case 1510: case 1511: case 1512: return 1000;
    case 2000: case 2100: case 2110: case 2111: case 2112: return 2000;
    default: return -1;
    }
}

constexpr bool UnsupportedBeginnerSkill(std::int32_t skill) {
    return skill / 10000 == 2001;
}

constexpr bool BeginnerPoolSkill(std::int32_t skill, int job) {
    const auto group = BeginnerGroup(job);
    return group >= 0 && skill >= group * 10000 + 1000 && skill <= group * 10000 + 1002;
}

constexpr bool UnsupportedSkillPointBook(std::int32_t skill) {
    const auto group = skill / 10000;
    return group >= 2210 && group <= 2218;
}

constexpr bool UnsupportedSkillAllocation(std::int32_t skill, int job) {
    const auto root = BeginnerGroup(job);
    const auto group = skill / 10000;
    return root < 0 || ((group == 0 || group == 1000 || group == 2000 || group == 2001) && group != root)
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

template <typename Skills>
bool BeginnerResourceValid(int group, const Skills& skills) {
    if (group < 0) return false;
    for (int i = 0; i < 3; ++i) {
        bool found = false;
        for (auto skill : skills) if (skill == group * 10000 + 1000 + i) found = true;
        if (!found) return false;
    }
    return true;
}

template <typename Level>
int BeginnerPoolPoints(int group, int level, Level skillLevel) {
    int used = 0;
    for (int i = 0; i < 3; ++i) used += skillLevel(group * 10000 + 1000 + i);
    return BeginnerSkillPointBudget(level, used);
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
