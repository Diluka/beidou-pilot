// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include "LoginActionProtocol.h"
#include <cstdint>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <string>

namespace BeiDouBridge { namespace NativeSkillUp {
struct Request {
    std::string instance, run, requestId;
    std::uint64_t scene = 0, deadlineMs = 0;
    std::uint32_t character = 0, skill = 0, remaining = 0;
};
inline bool Expired(const Request& request, std::uint64_t nowMs) { return nowMs >= request.deadlineMs; }
// These three beginner skills use the separate beginner SP pool.
inline bool BeginnerSkill(std::uint32_t skill) { return skill == 1000 || skill == 1001 || skill == 1002; }
// Keep normal and beginner pools separate at every admission and confirmation.
template<class ReadBeginner>
bool SelectPoints(std::uint32_t skill, std::uint32_t normal, ReadBeginner readBeginner, std::uint32_t& out) {
    if (BeginnerSkill(skill)) return readBeginner(out);
    out = normal;
    return true;
}
// Only the two observed job/skill families are candidates; this is not an
// eligibility check and must never authorize a native call by itself.
inline bool SupportedSkill(std::uint32_t job, std::uint32_t skill) {
    switch (job) {
    case 100:
        return BeginnerSkill(skill) || skill == 1000000 || skill == 1000001 || skill == 1000002
            || skill == 1001003 || skill == 1001004 || skill == 1001005;
    case 210:
        return BeginnerSkill(skill) || skill == 2100000 || skill == 2101001 || skill == 2101002
            || skill == 2101003 || skill == 2101004 || skill == 2101005;
    default: return false;
    }
}
struct Eligibility {
    bool known = false;
    std::uint64_t scene = 0;
    std::uint32_t character = 0, job = 0, sp = 0, count = 0, base = 0;
    std::int32_t delta = 0;
};
// Only validates the observed batch bounds. Native requirements and object
// identity must still be verified in the game thread before dispatch.
inline const char* BatchFailure(const Request& request, const Eligibility& state) {
    if (!state.known || state.scene != request.scene || state.character != request.character
        || state.count == 0 || state.count > 255 || request.remaining == 0)
        return "skill_up_state_unavailable";
    if (!SupportedSkill(state.job, request.skill)) return "skill_up_job_skill_unsupported";
    const std::int64_t raw = state.base == 0 ? 0 : static_cast<std::int64_t>(state.base) + state.delta;
    if (raw < 0 || raw > INT32_MAX) return "skill_up_state_unavailable";
    if (request.remaining > state.sp) return "skill_up_insufficient_sp";
    const auto level = raw > state.count ? state.count : static_cast<std::uint32_t>(raw);
    if (request.remaining > state.count - level) return "skill_up_insufficient_level_capacity";
    return nullptr;
}
struct PendingFence {
    bool pending = false;
    std::uint32_t character = 0, job = 0, skill = 0, base = 0, sp = 0;
    std::string requestId;
    struct Confirmed { std::uint32_t character, job, skill; };
    std::map<std::string, Confirmed> confirmed;
    bool WasConfirmed(const Request& request, const std::string& originalId, std::uint32_t currentJob) const {
        const auto found = confirmed.find(originalId);
        return found != confirmed.end() && found->second.character == request.character
            && found->second.skill == request.skill && found->second.job == currentJob;
    }
    bool Matches(const Request& request, const std::string& originalId) const {
        return pending && originalId == requestId && request.character == character && request.skill == skill;
    }
    bool Confirm(std::uint32_t currentCharacter, std::uint32_t currentJob,
                 std::uint32_t currentBase, std::uint32_t currentSp) {
        if (!pending) return true;
        if (character != currentCharacter || job != currentJob || base == UINT32_MAX || sp == 0
            || currentBase != base + 1 || currentSp != sp - 1) return false;
        // Preserve the terminal observation before releasing the fence, so a
        // lost result or a later batch rejection does not erase confirmation.
        if (confirmed.size() >= 4096 || !confirmed.emplace(requestId, Confirmed{character, job, skill}).second)
            return false;
        pending = false;
        return true;
    }
    void Arm(const Request& request, std::uint32_t currentJob, std::uint32_t currentBase, std::uint32_t currentSp) {
        pending = true; requestId = request.requestId; character = request.character; job = currentJob;
        skill = request.skill; base = currentBase; sp = currentSp;
    }
};
// Called only after the adapter has captured a fresh identity on the game thread.
inline bool ReconcileRecorded(const PendingFence& fence, const Request& request, const std::string& originalId,
                              std::uint64_t scene, std::uint64_t nowMs, std::uint32_t job) {
    return !Expired(request, nowMs) && request.scene == scene && fence.WasConfirmed(request, originalId, job);
}
// The adapter must first validate both complete snapshots and their equality.
inline bool ReconcileObserved(PendingFence& fence, const Request& request, const std::string& originalId,
                              std::uint64_t scene, std::uint64_t nowMs, std::uint32_t job,
                              std::uint32_t base, std::uint32_t sp) {
    return !Expired(request, nowMs) && request.scene == scene && fence.Matches(request, originalId)
        && fence.Confirm(request.character, job, base, sp);
}
// The adapter owns version checks, same-thread capture and final identity/fact
// revalidation. Success means the native event was invoked, not that a packet was sent.
template<class Backend>
bool Dispatch(const Request& request, Backend& backend, const char*& reason) {
    if (!backend.VersionSupported()) { reason = "skill_up_unsupported"; return false; }
    Eligibility facts;
    if (!backend.Capture(request, facts)) { reason = "skill_up_state_unavailable"; return false; }
    if (const auto failure = BatchFailure(request, facts)) { reason = failure; return false; }
    if (!backend.CanRaise()) { reason = "skill_up_requirements_unmet"; return false; }
    if (!backend.Revalidate(request, facts)) { reason = "skill_up_state_changed"; return false; }
    if (!backend.Gate()) { reason = "skill_up_gate_closed"; return false; }
    backend.Send(request.skill);
    reason = "skill_up_event_invoked";
    return true;
}
// In-process replay guard. A restarted client needs a fresh run identity and
// must not accept a request left over from an earlier run.
struct RequestGuard {
    std::set<std::string> seen;
    bool Consume(const std::string& id) {
        if (seen.size() >= 4096) return false;
        return seen.insert(id).second;
    }
};
inline bool Parse(const std::string& line, Request& request) {
    std::istringstream stream(line);
    std::string version, scene, character, skill, remaining, deadline, extra;
    if (!(stream >> version >> request.instance >> request.run >> request.requestId >> scene >> character >> skill >> remaining >> deadline)
        || version != "1" || (stream >> extra) || !LoginAction::ValidRequestId(request.requestId)) return false;
    for (char c : request.requestId) if (c >= 'A' && c <= 'F') return false;
    std::uint64_t values[5]{};
    const std::string texts[] = {scene, character, skill, remaining, deadline};
    for (int i = 0; i < 5; ++i) {
        const auto maximum = i == 0 || i == 4 ? UINT64_MAX : static_cast<std::uint64_t>(UINT32_MAX);
        for (char c : texts[i]) {
            if (c < '0' || c > '9' || values[i] > (maximum - (c - '0')) / 10) return false;
            values[i] = values[i] * 10 + (c - '0');
        }
        if (i != 0 && values[i] == 0) return false;
    }
    request.scene = values[0]; request.character = static_cast<std::uint32_t>(values[1]);
    request.skill = static_cast<std::uint32_t>(values[2]); request.remaining = static_cast<std::uint32_t>(values[3]);
    request.deadlineMs = values[4];
    return true;
}
// Reconcile uses the same nine fields as a skill-up request, followed by the
// original request ID. remaining must be 1; no skill event is issued.
inline bool ParseReconcile(const std::string& line, Request& request, std::string& originalId) {
    std::istringstream input(line);
    std::string fields[10], extra;
    for (auto& field : fields) if (!(input >> field)) return false;
    if (input >> extra) return false;
    originalId = fields[9];
    if (!LoginAction::ValidRequestId(originalId)) return false;
    for (char c : originalId) if (c >= 'A' && c <= 'F') return false;
    std::string common = fields[0];
    for (int i = 1; i < 9; ++i) common += " " + fields[i];
    return Parse(common, request) && request.remaining == 1;
}
} }
