// SPDX-License-Identifier: AGPL-3.0-or-later
#include "SkillUpPreflight.h"
#include <cassert>
#include <map>

int main() {
    const std::map<int, int> requirements{{42, 3}};
    auto check = [&](bool job, int sp, int current, unsigned points, int prerequisite) {
        return headless::SkillUpEligible(job, true, false, 10, current, sp, points, requirements,
                                         [&](int) { return prerequisite; });
    };
    assert(headless::BeginnerSkillPointBudget(5, 2) == 2);
    assert(headless::BeginnerSkillPointBudget(20, 6) == 0);
    assert(check(true, headless::BeginnerSkillPointBudget(5, 2), 1, 2, 3));
    assert(check(true, 4, 2, 3, 3));
    assert(!check(true, 2, 1, 3, 3));
    assert(!check(true, 10, 9, 2, 3));
    assert(!check(false, 10, 0, 1, 3));
    assert(!check(true, 10, 0, 1, 2));
}
