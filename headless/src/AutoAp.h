// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <string>

enum class AutoApAdmission { NewRequest, SameSession, Pending };

inline AutoApAdmission CheckAutoApAdmission(bool active, bool pending,
                                             const std::string& owner, const std::string& requester) {
    if (active) return owner == requester ? AutoApAdmission::SameSession : AutoApAdmission::Pending;
    return pending ? AutoApAdmission::Pending : AutoApAdmission::NewRequest;
}

// Once another character is observed, this request cannot be attributed again.
struct AutoApIdentity {
    std::uint32_t characterId = 0;
    bool changed = false;

    bool Observe(std::uint32_t observedId) {
        if (observedId != characterId) changed = true;
        return !changed;
    }
};

struct AutoApPlan {
    std::array<int32_t, 2> codes{};
    std::array<int32_t, 2> amounts{};
};

// Returns false where the original client's branch depends on an unknown flag
// or rejects the job. Values use level, job, STR, DEX, INT, LUK, AP order.
inline bool PlanAutoAp(const std::array<std::uint32_t, 7>& v, AutoApPlan& plan) {
    const int level = static_cast<int>(v[0]);
    const int job = static_cast<int>(v[1]);
    const int group = (job % 1000) / 100;
    const int subtype = job % 1000;
    int first = 0, second = 0, target = 0;
    if (group == 0) {
        if (subtype != 0 && job != 2001) return false;
        first = 1; second = 0; target = level;
    } else if (group == 1) {
        first = 1; second = 0; target = level + std::min(level, 30);
    } else if (group == 2) {
        first = 3; second = 2; target = level + 3;
    } else if (group == 3) {
        first = 0; second = 1;
        if (subtype == 300 || (subtype >= 310 && subtype <= 312)) target = level + 5;
        else if (subtype >= 320 && subtype <= 322) target = level;
        else return false;
    } else if (group == 4) {
        first = 1; second = 3; target = level + std::min(level, 40);
    } else if (group == 5) {
        if (subtype == 500 && job != 1500) return false;
        if (subtype / 10 == 51 || job == 1500) {
            first = 1; second = 0; target = level + std::min(level, 20);
        } else if (subtype / 10 == 52) {
            first = 0; second = 1; target = level;
        } else return false;
    } else return false;
    const int secondTarget = level * 5 + 12 - target;
    const int ap = static_cast<int>(v[6]);
    int remaining = ap;
    plan.codes = {0x40 << first, 0x40 << second};
    plan.amounts[0] = std::min(remaining, std::max(0, target - static_cast<int>(v[2 + first])));
    remaining -= plan.amounts[0];
    plan.amounts[1] = std::min(remaining, std::max(0, secondTarget - static_cast<int>(v[2 + second])));
    remaining -= plan.amounts[1];
    plan.amounts[1] += remaining;
    return true;
}
