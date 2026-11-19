// SPDX-License-Identifier: AGPL-3.0-or-later
// Expected values derived from the original client's static allocation evidence.
#include "AutoAp.h"
#include <cassert>

int main() {
    assert(CheckAutoApAdmission(false, false, "", "one") == AutoApAdmission::NewRequest);
    assert(CheckAutoApAdmission(true, true, "one", "one") == AutoApAdmission::SameSession);
    assert(CheckAutoApAdmission(true, true, "one", "two") == AutoApAdmission::Pending);
    assert(CheckAutoApAdmission(false, true, "", "two") == AutoApAdmission::Pending);
    assert(CheckAutoApAdmission(true, false, "one", "two") == AutoApAdmission::Pending);
    assert(CheckAutoApAdmission(false, false, "", "two") == AutoApAdmission::NewRequest);
    AutoApPlan p;
    AutoApIdentity identity{123, false};
    assert(identity.Observe(123));
    assert(!identity.Observe(456));
    // Returning to the original ID cannot revive attribution of an old request.
    assert(!identity.Observe(123));
    assert(identity.changed);
    // Beginner family includes jobs whose last three digits are zero, and 2001.
    for (auto job : {0u, 1000u, 2000u, 2001u}) {
        assert(PlanAutoAp({10, job, 4, 4, 4, 4, 10}, p));
        assert((p.codes == std::array<int32_t, 2>{0x80, 0x40}));
        assert((p.amounts == std::array<int32_t, 2>{6, 4}));
    }
    assert(!PlanAutoAp({10, 1, 4, 4, 4, 4, 10}, p));
    assert(PlanAutoAp({40, 100, 4, 4, 4, 4, 100}, p));
    assert((p.amounts == std::array<int32_t, 2>{66, 34}));
    assert(PlanAutoAp({10, 200, 4, 4, 4, 4, 20}, p));
    assert((p.codes == std::array<int32_t, 2>{0x200, 0x100}));
    assert((p.amounts == std::array<int32_t, 2>{9, 11}));
    assert(PlanAutoAp({30, 310, 4, 4, 4, 4, 50}, p));
    assert((p.amounts == std::array<int32_t, 2>{31, 19}));
    assert(PlanAutoAp({30, 320, 4, 4, 4, 4, 50}, p));
    assert((p.amounts == std::array<int32_t, 2>{26, 24}));
    assert(!PlanAutoAp({30, 313, 4, 4, 4, 4, 50}, p));
    assert(PlanAutoAp({50, 400, 4, 4, 4, 4, 100}, p));
    assert((p.codes == std::array<int32_t, 2>{0x80, 0x200}));
    assert((p.amounts == std::array<int32_t, 2>{86, 14}));
    assert(!PlanAutoAp({10, 500, 4, 4, 4, 4, 5}, p));
    for (auto job : {1500u, 510u, 511u, 519u}) {
        assert(PlanAutoAp({30, job, 4, 4, 4, 4, 50}, p));
        assert((p.amounts == std::array<int32_t, 2>{46, 4}));
    }
    assert(PlanAutoAp({30, 520, 4, 4, 4, 4, 50}, p));
    assert((p.codes == std::array<int32_t, 2>{0x40, 0x80}));
    assert((p.amounts == std::array<int32_t, 2>{26, 24}));
    assert(!PlanAutoAp({10, 530, 4, 4, 4, 4, 5}, p));
    // When both targets are already met, the original assigns all remaining AP
    // to the second entry rather than dropping it.
    assert(PlanAutoAp({10, 100, 100, 100, 4, 4, 5}, p));
    assert((p.amounts == std::array<int32_t, 2>{0, 5}));
}
