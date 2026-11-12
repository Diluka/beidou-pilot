// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Allocation.h"
#include <cassert>
#include <string>

using namespace MapleControl;

AllocationFacts Facts() {
    AllocationFacts facts;
    facts.instanceId = "instance-1";
    facts.characterId = 7;
    facts.sceneGeneration = 2;
    facts.job = 100;
    facts.known = true;
    facts.points = 5;
    facts.value = 10;
    facts.attributes = {10, 4, 4, 4};
    return facts;
}

void Allocated(const Allocation& allocation, unsigned count, bool pending) {
    const auto report = allocation.Report().Dump();
    assert(report.find("\"allocated\":" + std::to_string(count) + ",") != std::string::npos);
    assert(report.find(std::string("\"point_pending\":") + (pending ? "true" : "false")) != std::string::npos);
}

int main() {
    AllocationRequest ap;
    ap.stat = "strength";
    ap.count = 2;
    Allocation allocation;
    auto facts = Facts();
    allocation.Start(ap, facts);
    assert(allocation.Tick(facts, 0));
    assert(!allocation.Tick(facts, 10));
    // Packets may update the pool and target in different native ticks.
    --facts.points;
    assert(!allocation.Tick(facts, 20));
    Allocated(allocation, 0, true);
    ++facts.value;
    ++facts.attributes[0];
    assert(!allocation.Tick(facts, 30));
    Allocated(allocation, 1, false);
    assert(allocation.Tick(facts, 40));
    --facts.points;
    ++facts.value;
    ++facts.attributes[0];
    assert(!allocation.Tick(facts, 50));
    assert(!allocation.Active() && allocation.Confirmed());
    Allocated(allocation, 2, false);
    assert(!allocation.Tick(facts, 60));

    // No effect, a one-sided effect, and unknown facts never cause a resend.
    for (int partial = 0; partial < 3; ++partial) {
        facts = Facts();
        allocation.Start(ap, facts);
        assert(allocation.Tick(facts, 100));
        if (partial == 1) --facts.points;
        if (partial == 2) facts.known = false;
        assert(!allocation.Tick(facts, 1300));
        assert(!allocation.Active() && !allocation.Confirmed());
        Allocated(allocation, 0, true);
        assert(!allocation.Tick(facts, 1400));
        if (partial == 2) assert(allocation.Report().Dump().find("\"points_after\":null") != std::string::npos);
    }

    // An unrelated attribute change cannot count as a confirmed AP.
    facts = Facts();
    allocation.Start(ap, facts);
    assert(allocation.Tick(facts, 0));
    --facts.points;
    ++facts.value;
    ++facts.attributes[0];
    ++facts.attributes[1];
    assert(!allocation.Tick(facts, 10));
    assert(allocation.Reason() == "allocation_observation_conflict");
    Allocated(allocation, 0, true);

    // All identity components and unexpected changes stop a partial batch.
    for (int change = 0; change < 6; ++change) {
        facts = Facts();
        allocation.Start(ap, facts);
        assert(allocation.Tick(facts, 0));
        --facts.points;
        ++facts.value;
        ++facts.attributes[0];
        assert(!allocation.Tick(facts, 10));
        if (change == 0) facts.characterId++;
        if (change == 1) facts.sceneGeneration++;
        if (change == 2) facts.instanceId += "-next";
        if (change == 3) facts.job++;
        if (change == 4) facts.value++;
        if (change == 5) facts.refusal = "skill_prerequisite_not_met";
        assert(!allocation.Tick(facts, 20));
        assert(!allocation.Active());
        Allocated(allocation, 1, false);
    }

    // Cancelling before dispatch and while a point is pending retains the facts.
    for (bool dispatch : {false, true}) {
        facts = Facts();
        allocation.Start(ap, facts);
        if (dispatch) assert(allocation.Tick(facts, 0));
        allocation.Cancel();
        assert(!allocation.Active() && allocation.Dispatched() == dispatch);
        assert(!allocation.Tick(facts, 100));
        Allocated(allocation, 0, dispatch);
    }

    AllocationRequest sp;
    // Acknowledgement already present at cancellation is retained, with no next point.
    facts = Facts();
    allocation.Start(ap, facts);
    assert(allocation.Tick(facts, 0));
    --facts.points;
    ++facts.value;
    ++facts.attributes[0];
    allocation.Cancel(facts, 10);
    Allocated(allocation, 1, false);
    assert(!allocation.Active() && !allocation.Tick(facts, 20));

    sp.skill = true;
    sp.skillId = 1000000;
    sp.count = 2;
    facts = Facts();
    facts.value = 3;
    facts.maximum = 5;
    allocation.Start(sp, facts);
    for (unsigned point = 0; point < 2; ++point) {
        assert(allocation.Tick(facts, point * 20));
        --facts.points;
        ++facts.value;
        // Reaching the cap can disable the UI, while the final point is confirmed.
        if (facts.value == facts.maximum) facts.refusal = "skill_at_maximum";
        assert(!allocation.Tick(facts, point * 20 + 10));
    }
    assert(allocation.Confirmed());
    Allocated(allocation, 2, false);
    for (int refusal = 0; refusal < 4; ++refusal) {
        facts = Facts();
        if (refusal == 0) facts.points = 1;
        if (refusal == 1) facts.maximum = 11;
        if (refusal == 2) facts.refusal = "skill_job_mismatch";
        if (refusal == 3) facts.refusal = "skill_prerequisite_not_met";
        allocation.Start(sp, facts);
        assert(!allocation.Active() && !allocation.Dispatched());
        assert(!allocation.Tick(facts, 0));
        Allocated(allocation, 0, false);
    }
}
