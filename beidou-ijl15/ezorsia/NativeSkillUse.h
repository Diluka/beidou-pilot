// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"

#include <cstdint>
#include <string>
#include <utility>

namespace BeiDouBridge {

// A skill waits outside the Lua stack until its direction has reached the real
// character consumer. Native invocation may itself pump another application update.
class NativeSkillUse {
public:
    struct Skill {
        std::uint32_t skillId = 0;
        std::uint32_t character = 0;
        std::uint32_t user = 0;
        std::uint64_t sceneGeneration = 0;
        std::uint64_t inputEpoch = 0;
        std::uint64_t deadline = 0;
        int direction = 0; // -1 left, 0 unchanged, 1 right.
    };

    struct Context {
        std::uint32_t character = 0;
        std::uint32_t user = 0;
        std::uint64_t sceneGeneration = 0;
        std::uint64_t inputEpoch = 0;
        std::uint64_t now = 0;
        std::uint32_t updatedCharacter = 0;
        std::uint64_t characterUpdates = 0;
        bool facingKnown = false;
        bool facingLeft = false;
    };

    void Request(const Skill& skill) {
        requested = skill;
        pending = true;
        directionDelivered = false;
        result = {false, 0, "native_skill_pending", false};
        ++revision;
    }

    void DirectionDelivered(std::uint64_t epoch, std::uint64_t characterUpdates) {
        if (pending && requested.inputEpoch == epoch && requested.direction != 0 && !directionDelivered) {
            directionAt = characterUpdates;
            directionDelivered = true;
        }
    }

    bool Pending() const { return pending; }

    const MapleControl::SkillResult& Result() const { return result; }

    void Cancel(const char* reason) {
        if (!pending) return;
        pending = false;
        directionDelivered = false;
        result = {false, 0, reason, false};
        ++revision;
    }

    template <typename Invoke> bool Consume(const Context& context, const Invoke& invoke) {
        if (!pending) return true;
        const auto skill = requested;
        if (skill.character != context.character || skill.user != context.user
            || skill.sceneGeneration != context.sceneGeneration || skill.inputEpoch != context.inputEpoch) {
            Cancel("native_skill_context_changed");
            return true;
        }
        if (context.now >= skill.deadline) {
            Cancel("native_skill_expired");
            return true;
        }
        if (skill.direction != 0
            && (!directionDelivered || context.updatedCharacter != skill.user || context.characterUpdates <= directionAt
                || !context.facingKnown || context.facingLeft != (skill.direction < 0)))
            return true;
        pending = false;
        directionDelivered = false;
        const auto consumedRevision = revision;
        MapleControl::SkillResult consumed{false, 0, {}, false};
        std::string error;
        const bool called = invoke(skill.skillId, consumed.nativeResult, error);
        if (revision != consumedRevision) return true;
        consumed.nativeResultKnown = called;
        consumed.dispatched = called && consumed.nativeResult != 0;
        consumed.reason = called ? (consumed.dispatched ? "native_skill_admitted" : "native_skill_rejected") : error;
        result = std::move(consumed);
        return called;
    }

private:
    Skill requested;
    bool pending = false;
    bool directionDelivered = false;
    std::uint64_t directionAt = 0;
    MapleControl::SkillResult result{false, 0, {}, false};
    std::uint64_t revision = 0;
};

}
