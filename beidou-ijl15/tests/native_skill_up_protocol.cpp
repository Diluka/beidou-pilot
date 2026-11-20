// SPDX-License-Identifier: AGPL-3.0-or-later
#include "../ezorsia/NativeSkillUpProtocol.h"
#ifndef _WIN32
#define __thiscall
#endif
#include "../ezorsia/NativeSkillUpCalls.h"
#include <cassert>
struct Backend {
    bool version = true, capture = true, can = true, valid = true, gate = true;
    int calls = 0;
    BeiDouBridge::NativeSkillUp::Eligibility facts{true, 7, 123, 100, 3, 20, 17, 0};
    bool VersionSupported() { return version; }
    bool Capture(const BeiDouBridge::NativeSkillUp::Request&, BeiDouBridge::NativeSkillUp::Eligibility& out) { out = facts; return capture; }
    bool CanRaise() { return can; }
    bool Revalidate(const BeiDouBridge::NativeSkillUp::Request&, const BeiDouBridge::NativeSkillUp::Eligibility&) { return valid; }
    bool Gate() { return gate; }
    void Send(std::uint32_t) { ++calls; }
};
int main() {
    using namespace BeiDouBridge::NativeSkillUp;
    Request request;
    const std::string id = "0123456789abcdef0123456789abcdef";
    assert(Parse("1 instance run " + id + " 0 123 1000000 3 123456789", request));
    assert(request.deadlineMs == 123456789);
    assert(!Expired(request, 123456788) && Expired(request, 123456789));
    assert(!Parse("1 instance run " + id + " 0 123 1000000 3 0", request));
    assert(!Parse("1 instance run " + id + " 0 123 1000000 3 18446744073709551616", request));
    assert(request.scene == 0 && request.character == 123 && request.skill == 1000000 && request.remaining == 3);
    assert(Parse("1 instance run " + id + " 18446744073709551615 4294967295 2101005 1 1", request));
    assert(!Parse("1 instance run " + id + " 18446744073709551616 1 1 1 1", request));
    assert(!Parse("1 instance run " + id + " 1 4294967296 1 1 1", request));
    assert(!Parse("1 instance run " + id + " 1 1 1 0 1", request));
    assert(!Parse("1 instance run bad 1 1 1 1 1", request));
    assert(!Parse("1 instance run " + id + " 1 1 1 1 1 extra", request));
    assert(!Parse("1 instance run 0123456789ABCDEF0123456789ABCDEF 1 1 1 1 1", request));
    for (auto job : {100u, 210u}) {
        for (auto skill : {1000u, 1001u, 1002u})
            assert(SupportedSkill(job, skill) && BeginnerSkill(skill));
        assert(!SupportedSkill(job, 1003) && !SupportedSkill(job, 10001000));
    }
    assert(SupportedSkill(200, 1001) && SupportedSkill(522, 1002));
    assert(!SupportedSkill(0, 1001) && !SupportedSkill(1000, 1001) && !BeginnerSkill(1003));
    assert(SupportedSkill(100, 1001005));
    for (auto skill : {2100000u, 2101001u, 2101002u, 2101003u, 2101004u, 2101005u})
        assert(SupportedSkill(210, skill));
    // These are candidates only: client group membership is still required.
    assert(SupportedSkill(210, 2101006) && SupportedSkill(211, 2101005));
    assert(!SupportedSkill(999, 2101005));
    assert((OrdinaryGroups(112) == std::vector<std::uint32_t>{100, 110, 111, 112}));
    assert((OrdinaryGroups(210) == std::vector<std::uint32_t>{200, 210}));
    assert(OrdinaryGroups(430).empty() && OrdinaryGroups(900).empty());
    for (auto skill : {1009u,1010u,1011u,1020u,10001009u,10001010u,10001011u,10001020u,
                       20001009u,20001010u,20001011u,20001020u,20011009u,20011010u,20011011u,20011020u})
        assert(FixedLevelSkill(skill) && !SupportedSkill(210, skill));
    assert(Parse("1 instance run " + id + " 7 123 1001005 3 123456789", request));
    Eligibility state{true, 7, 123, 100, 3, 20, 17, 0};
    assert(BatchFailure(request, state) == nullptr);
    state.delta = 1; assert(std::string(BatchFailure(request, state)) == "skill_up_insufficient_level_capacity");
    state.delta = 0; state.sp = 2; assert(std::string(BatchFailure(request, state)) == "skill_up_insufficient_sp");
    state.sp = 3; state.job = 999; assert(std::string(BatchFailure(request, state)) == "skill_up_job_skill_unsupported");
    state.job = 100; state.scene = 8; assert(std::string(BatchFailure(request, state)) == "skill_up_state_unavailable");
    state.scene = 7; state.known = false; assert(std::string(BatchFailure(request, state)) == "skill_up_state_unavailable");
    state.known = true; state.count = 0; assert(std::string(BatchFailure(request, state)) == "skill_up_state_unavailable");
    state.count = 20; state.base = 1; state.delta = -2;
    assert(std::string(BatchFailure(request, state)) == "skill_up_state_unavailable");
    Request beginner = request; beginner.skill = 1000; beginner.remaining = 2;
    Eligibility beginnerState{true, 7, 123, 100, 4, 3, 2, 0};
    assert(std::string(BatchFailure(beginner, beginnerState)) == "skill_up_insufficient_level_capacity");
    auto unreadable = [](std::uint32_t, std::array<unsigned char, 16>&) { return false; };
    NativeCalls<decltype(unreadable)> native{unreadable};
    assert(!native.Fingerprints());
    Backend backend;
    const char* reason = nullptr;
    backend.facts.sp = 2;
    assert(!Dispatch(request, backend, reason) && backend.calls == 0
        && std::string(reason) == "skill_up_insufficient_sp");
    backend.facts.sp = 3; backend.facts.delta = 1;
    assert(!Dispatch(request, backend, reason) && backend.calls == 0
        && std::string(reason) == "skill_up_insufficient_level_capacity");
    backend.facts.delta = 0;
    backend.version = false; assert(!Dispatch(request, backend, reason) && backend.calls == 0);
    backend.version = true; backend.capture = false; assert(!Dispatch(request, backend, reason) && backend.calls == 0);
    backend.capture = true; backend.can = false; assert(!Dispatch(request, backend, reason) && backend.calls == 0);
    backend.can = true; backend.valid = false; assert(!Dispatch(request, backend, reason) && backend.calls == 0);
    backend.valid = true; backend.gate = false; assert(!Dispatch(request, backend, reason) && backend.calls == 0);
    backend.gate = true; assert(Dispatch(request, backend, reason) && backend.calls == 1);
    Request reconciliation;
    std::string originalId;
    const auto line = "1 instance run " + id + " 8 123 1001005 1 123456789 " + id;
    assert(ParseReconcile(line, reconciliation, originalId) && originalId == id);
    assert(!ParseReconcile(line + " extra", reconciliation, originalId));
    assert(!ParseReconcile("1 instance run " + id + " 8 123 1001005 2 123456789 " + id, reconciliation, originalId));
    assert(ParseReconcile(line, reconciliation, originalId));
    // Exercise the same pool selector used by the bridge for admissions,
    // pending confirmation and explicit reconciliation.
    for (auto firstSkill : {1000u, 1000000u}) {
        const auto nextSkill = BeginnerSkill(firstSkill) ? 1000000u : 1001u;
        std::uint32_t normal = 8, beginnerPoints = 5, selected = 0;
        auto readBeginner = [&](std::uint32_t& out) { out = beginnerPoints; return true; };
        Request firstRequest = request; firstRequest.skill = firstSkill;
        assert(SelectPoints(firstSkill, normal, readBeginner, selected));
        PendingFence transition;
        transition.Arm(firstRequest, 100, 1, selected);
        if (BeginnerSkill(firstSkill)) --beginnerPoints; else --normal;
        std::uint32_t prior = 0, next = 0;
        assert(SelectPoints(firstSkill, normal, readBeginner, prior));
        assert(SelectPoints(nextSkill, normal, readBeginner, next));
        assert(!transition.Confirm(123, 100, 2, next)); // wrong pool cannot confirm
        assert(ReconcileObserved(transition, firstRequest, firstRequest.requestId, firstRequest.scene, 1, 100, 2, prior));
        assert(!transition.pending);
        assert(next == (BeginnerSkill(nextSkill) ? beginnerPoints : normal));
    }
    for (auto skill : {1000u, 1001u, 1002u}) {
        Request beginnerPending = request; beginnerPending.skill = skill;
        PendingFence separate;
        separate.Arm(beginnerPending, 210, 1, 4);
        assert(BeginnerSkill(separate.skill));
        assert(!separate.Confirm(123, 210, 2, 9)); // ordinary SP is not the beginner pool
        assert(separate.Confirm(123, 210, 2, 3));
    }
    PendingFence fence;
    fence.Arm(request, 100, 17, 3);
    assert(fence.Matches(reconciliation, id));
    assert(!fence.Matches(reconciliation, "11111111111111111111111111111111"));
    reconciliation.skill = 1000;
    assert(!fence.Matches(reconciliation, id));
    assert(!fence.Confirm(123, 100, 17, 3));
    assert(!fence.Confirm(124, 100, 18, 2));
    assert(!fence.Confirm(123, 210, 18, 2));
    assert(!fence.Confirm(123, 100, 18, 3));
    assert(!fence.Confirm(123, 100, 17, 2));
    // Scene changes are checked on the new request, not used to invalidate
    // an otherwise exact same-character confirmation.
    request.scene = 8;
    assert(fence.Confirm(123, 100, 18, 2));
    assert(!fence.pending);
    reconciliation.skill = 1001005;
    assert(fence.WasConfirmed(reconciliation, id, 100));
    assert(!fence.WasConfirmed(reconciliation, id, 210));
    auto next = request; next.requestId = "22222222222222222222222222222222";
    fence.Arm(next, 100, 18, 2);
    assert(fence.WasConfirmed(reconciliation, id, 100));
    reconciliation.character = 999;
    assert(!fence.WasConfirmed(reconciliation, id, 100));
    RequestGuard guard;
    assert(guard.Consume(id));
    assert(!guard.Consume(id));
}
