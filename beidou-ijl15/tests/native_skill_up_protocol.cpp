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
    assert(BatchEligible(request, state));
    state.delta = 1; assert(!BatchEligible(request, state));
    state.delta = 0; state.sp = 2; assert(!BatchEligible(request, state));
    state.sp = 3; state.scene = 8; assert(!BatchEligible(request, state));
    state.scene = 7; state.known = false; assert(!BatchEligible(request, state));
    auto unreadable = [](std::uint32_t, std::array<unsigned char, 16>&) { return false; };
    NativeCalls<decltype(unreadable)> native{unreadable};
    assert(!native.Fingerprints());
    Backend backend;
    const char* reason = nullptr;
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
