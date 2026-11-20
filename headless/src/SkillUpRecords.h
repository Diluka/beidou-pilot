// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <nlohmann/json.hpp>
#include <algorithm>
#include <cstdint>
#include <string>

namespace headless {
using SkillRecords = nlohmann::json;

inline bool SkillRequestIdentity(const std::string& requestRun, const std::string& run, std::int64_t requestCharacter,
                                 bool known, std::int64_t character) {
    return requestRun == run && known && requestCharacter == character;
}

inline bool SkillRequestPending(const SkillRecords& records) {
    return std::any_of(records.begin(), records.end(), [](const auto& record) {
        return record["status"] == "pending" || record["status"] == "unresolved";
    });
}

inline void InvalidatePendingSkillRequests(SkillRecords& records) {
    for (auto& record : records)
        if (record["status"] == "pending") record["status"] = "unresolved";
}

inline void ObserveSkillRequest(nlohmann::json& record, bool valid, int level, int sp) {
    if (record["status"] != "pending") return;
    if (!valid)
        record["status"] = "unresolved";
    else if (level == record["level_before"].get<int>() + 1 && sp == record["sp_before"].get<int>() - 1)
        record["status"] = "confirmed";
}
}
