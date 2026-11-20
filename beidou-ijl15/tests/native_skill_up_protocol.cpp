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
    assert(SupportedSkill(100, 1000) && !SupportedSkill(100, 1001) && !SupportedSkill(210, 1000));
    assert(SupportedSkill(100, 1001005) && SupportedSkill(210, 2101005));
    assert(!SupportedSkill(210, 1001005) && !SupportedSkill(211, 2101005));
    assert(Parse("1 instance run " + id + " 7 123 1001005 3 123456789", request));
    Eligibility state{true, 7, 123, 100, 3, 20, 17, 0};
    assert(BatchFailure(request, state) == nullptr);
    state.delta = 1; assert(std::string(BatchFailure(request, state)) == "skill_up_insufficient_level_capacity");
    state.delta = 0; state.sp = 2; assert(std::string(BatchFailure(request, state)) == "skill_up_insufficient_sp");
    state.sp = 3; state.job = 210; assert(std::string(BatchFailure(request, state)) == "skill_up_job_skill_unsupported");
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
    PendingFence fence;
    fence.Arm(request, 100, 17, 3);
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
    RequestGuard guard;
    assert(guard.Consume(id));
    assert(!guard.Consume(id));
}
