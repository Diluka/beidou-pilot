// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Observation.h"

#include <array>
#include <cstdint>
#include <string>

namespace MapleControl {

struct AllocationRequest {
    bool skill = false;
    std::string stat;
    std::uint32_t skillId = 0;
    unsigned count = 1;
    unsigned timeoutMs = 1200;
};

// Hosts supply native facts and eligibility; neither host invents missing facts.
struct AllocationFacts {
    std::string instanceId;
    std::uint32_t characterId = 0;
    std::uint64_t sceneGeneration = 0;
    std::uint32_t job = 0;
    bool known = false;
    unsigned points = 0;
    unsigned value = 0;
    std::array<unsigned, 4> attributes{};
    unsigned maximum = 0; // Zero means the native upper limit is unavailable.
    std::string refusal;
};

// One request at a time, with no retry of a point whose effect is uncertain.
// Tick commits pending BEFORE the host enters a possibly reentrant native call.
class Allocation {
public:
    void Start(const AllocationRequest& input, const AllocationFacts& facts) {
        request = input;
        initial = previous = current = facts;
        allocated = 0;
        dispatched = pending = false;
        active = true;
        reason = "allocation_ready";
        if (input.count < 1 || input.count > 100 || input.timeoutMs < 1 || input.timeoutMs > 30000
            || (!input.skill && input.stat != "strength" && input.stat != "dexterity" && input.stat != "intelligence"
                && input.stat != "luck")
            || (input.skill && (input.skillId == 0 || input.skillId > 2147483647)))
            Stop("invalid_allocation");
        else if (!facts.known)
            Stop("allocation_facts_unavailable");
        else if (!facts.refusal.empty())
            Stop(facts.refusal);
        else if (facts.points < input.count)
            Stop(input.skill ? "insufficient_sp" : "insufficient_ap");
        else if (facts.maximum != 0 && (facts.value >= facts.maximum || input.count > facts.maximum - facts.value))
            Stop("allocation_limit_exceeded");
    }

    bool Tick(const AllocationFacts& facts, std::uint64_t now, bool mayDispatch = true) {
        if (!active) return false;
        current = facts;
        if (!facts.known) {
            Stop("allocation_facts_unavailable");
            return false;
        }
        if (facts.instanceId != initial.instanceId || facts.characterId != initial.characterId
            || facts.sceneGeneration != initial.sceneGeneration || facts.job != initial.job) {
            Stop("allocation_context_changed");
            return false;
        }
        if (pending) {
            bool otherAttributesUnchanged = true;
            if (!request.skill) {
                for (unsigned index = 0; index < facts.attributes.size(); ++index)
                    if (index != AttributeIndex(request.stat) && facts.attributes[index] != previous.attributes[index])
                        otherAttributesUnchanged = false;
            }
            if (facts.points == previous.points - 1 && facts.value == previous.value + 1 && otherAttributesUnchanged) {
                ++allocated;
                pending = false;
                previous = facts;
                if (allocated == request.count) {
                    Stop("allocation_confirmed");
                    return false;
                }
                // A later native tick must reread eligibility before the next point.
                return false;
            }
            if (!otherAttributesUnchanged || facts.value > previous.value + 1 || facts.value < previous.value
                || facts.points > previous.points || facts.points + 1 < previous.points) {
                Stop("allocation_observation_conflict");
                return false;
            }
            if (now >= deadline) Stop("allocation_not_confirmed");
            return false;
        }
        if (facts.points != previous.points || facts.value != previous.value
            || facts.attributes != previous.attributes) {
            Stop("allocation_baseline_changed");
            return false;
        }
        if (!facts.refusal.empty()) {
            Stop(facts.refusal);
            return false;
        }
        if (facts.points == 0 || (facts.maximum != 0 && facts.value >= facts.maximum)) {
            Stop("allocation_limit_exceeded");
            return false;
        }
        if (!mayDispatch) return false;
        pending = dispatched = true;
        deadline = now + request.timeoutMs;
        reason = "allocation_point_requested";
        return true;
    }

    void Cancel() {
        if (active) Stop("allocation_confirmation_stopped");
    }

    void Cancel(const AllocationFacts& facts, std::uint64_t now, bool mayConfirm = true) {
        if (mayConfirm)
            Tick(facts, now, false);
        else if (active)
            current = facts;
        Cancel();
    }

    bool Active() const { return active; }

    bool Confirmed() const { return reason == "allocation_confirmed"; }

    bool Dispatched() const { return dispatched; }

    bool Pending() const { return pending; }

    unsigned Allocated() const { return allocated; }

    const std::string& Reason() const { return reason; }

    Value Report() const {
        return Value::Object({{"kind", request.skill ? "sp" : "ap"},
                              {"stat", request.skill ? Value() : Value(request.stat)},
                              {"skill_id", request.skill ? Value(request.skillId) : Value()},
                              {"character_id", initial.characterId},
                              {"scene_generation", initial.sceneGeneration},
                              {"job_before", initial.job},
                              {"job_after", current.known ? Value(current.job) : Value()},
                              {"requested", request.count},
                              {"allocated", allocated},
                              {"point_pending", pending},
                              {"points_before", initial.known ? Value(initial.points) : Value()},
                              {"value_before", initial.known ? Value(initial.value) : Value()},
                              {"points_after", current.known ? Value(current.points) : Value()},
                              {"value_after", current.known ? Value(current.value) : Value()},
                              {"current_character_id", current.known ? Value(current.characterId) : Value()},
                              {"current_scene_generation", current.known ? Value(current.sceneGeneration) : Value()}});
    }

    static unsigned AttributeIndex(const std::string& stat) {
        return stat == "strength" ? 0 : stat == "dexterity" ? 1 : stat == "intelligence" ? 2 : 3;
    }

private:
    void Stop(const std::string& why) {
        active = false;
        reason = why;
    }

    AllocationRequest request;
    AllocationFacts initial, previous, current;
    unsigned allocated = 0;
    bool active = false;
    bool dispatched = false;
    bool pending = false;
    std::uint64_t deadline = 0;
    std::string reason;
};
}
