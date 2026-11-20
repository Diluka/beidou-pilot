// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include "NativeSkillUpFacts.h"

namespace BeiDouBridge { namespace NativeSkillUp {
inline const char* LevelRecheckFailure(bool known, std::uint32_t previous, std::uint32_t current) {
    if (!known) return "skill_up_state_unavailable";
    return previous == current ? nullptr : "skill_up_state_changed";
}
// nullptr means this one stage gate is satisfied, not overall eligibility.
template<class Reader>
const char* StageFailure(Reader read, std::uint32_t character, bool levelKnown, std::uint32_t level,
                         std::uint32_t skill, std::uint32_t remaining) {
    if (BeginnerSkill(skill)) return nullptr;
    if (!levelKnown) return "skill_up_state_unavailable";
    const auto result = NativeSkillUpFacts::StagePointsDecision(read, character, level, skill, remaining);
    if (result == NativeSkillUpFacts::StagePointsResult::Allowed) return nullptr;
    return result == NativeSkillUpFacts::StagePointsResult::Limit ? "skill_up_stage_limit"
                                                                  : "skill_up_state_unavailable";
}
} }
