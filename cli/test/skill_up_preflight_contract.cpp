// SPDX-License-Identifier: AGPL-3.0-or-later
#include "SkillUpPreflight.h"
#include <cassert>
#include <map>
#include <vector>

int main() {
    const std::map<int, int> requirements{{42, 3}};
    auto check = [&](bool job, int sp, int current, unsigned points, int prerequisite) {
        return headless::SkillUpEligible(job, true, false, 10, current, sp, points, requirements,
                                         [&](int) { return prerequisite; });
    };
    for (int skill : {20011000, 20011001, 20011002}) assert(headless::UnsupportedBeginnerSkill(skill));
    for (int skill : {10001000, 10001001, 10001002}) {
        assert(headless::BeginnerPoolSkill(skill, 1112));
        assert(!headless::BeginnerPoolSkill(skill, 2112));
    }
    for (int skill : {20001000, 20001001, 20001002}) {
        assert(headless::BeginnerPoolSkill(skill, 2112));
        assert(!headless::BeginnerPoolSkill(skill, 1112));
    }
    assert(!headless::BeginnerPoolSkill(10001003, 1112));
    assert(headless::BeginnerGroup(2001) == -1);
    assert(headless::BeginnerGroup(2200) == -1);
    for (int skill : {1000, 1001, 1002, 1001003, 2101002, 11001000, 21101000})
        assert(!headless::UnsupportedBeginnerSkill(skill));
    for (int group = 2210; group <= 2218; ++group) {
        assert(headless::UnsupportedSkillAllocation(group * 10000, 100));
        assert(headless::UnsupportedSkillAllocation(group * 10000 + 9999, 100));
    }
    for (int job = 2200; job <= 2218; ++job) assert(headless::UnsupportedSkillAllocation(1001003, job));
    assert(headless::UnsupportedSkillAllocation(1001003, 2001));
    assert(headless::UnsupportedSkillAllocation(1001003, 2199));
    assert(headless::UnsupportedSkillAllocation(1001003, 2219));
    assert(!headless::UnsupportedSkillAllocation(1001003, 2000));
    assert(headless::UnsupportedSkillAllocation(1000, 1));
    assert(headless::UnsupportedSkillAllocation(10001000, 2112));
    assert(headless::UnsupportedSkillAllocation(20001000, 1112));
    assert(headless::UnsupportedSkillAllocation(1000, 1112));
    assert(!headless::UnsupportedSkillAllocation(10001000, 1112));
    assert(!headless::UnsupportedSkillAllocation(20001000, 2112));
    assert(!headless::UnsupportedSkillPointBook(22099999));
    assert(!headless::UnsupportedSkillPointBook(22190000));
    assert(!headless::UnsupportedSkillPointBook(2101002));
    for (int skill : {1121000, 2121000, 22170001, 22171003, 22171004, 22181002, 22181003})
        assert(headless::ServerFourthJobSkill(skill));
    for (int skill : {1001003, 2101002, 22120000, 22121000, 22171002, 22181004})
        assert(!headless::ServerFourthJobSkill(skill));
    assert(!headless::BeginnerResourceValid(1000, std::vector<int>{}));
    assert(!headless::BeginnerResourceValid(1000, std::vector<int>{10001000, 10001001}));
    assert(headless::BeginnerResourceValid(1000, std::vector<int>{10001000, 10001001, 10001002, 10001003}));
    // The server counts learned levels even when the client marks a skill invisible with master level zero.
    assert(headless::BeginnerPoolPoints(0, 7, [](int skill) { return skill == 1001 ? 2 : 0; }) == 4);
    assert(headless::BeginnerSkillPointBudget(5, 2) == 2);
    assert(headless::BeginnerSkillPointBudget(20, 6) == 0);
    assert(check(true, headless::BeginnerSkillPointBudget(5, 2), 1, 2, 3));
    assert(check(true, 4, 2, 3, 3));
    assert(!check(true, 2, 1, 3, 3));
    assert(!check(true, 10, 9, 2, 3));
    assert(!headless::SkillUpEligible(true, true, false, 0, 0, 3, 1, requirements, [&](int) { return 3; }));
    assert(!check(false, 10, 0, 1, 3));
    assert(!check(true, 10, 0, 1, 2));
}
