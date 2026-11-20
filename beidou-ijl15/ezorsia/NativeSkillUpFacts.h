// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "NativeObservation.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <map>
#include <set>
#include <vector>
#include "NativeSkillUpProtocol.h"

namespace BeiDouBridge { namespace NativeSkillUpFacts {
// Reader has the NativeObservation::Bytes(address, size) contract. The map
// layout and snapshot checks match ObserveCharacter's MapRecords.
template<class Reader>
inline std::map<std::uint32_t, std::uint32_t> MapRecords(Reader read, std::uint32_t address) {
    using A = std::uint32_t;
    auto at = [](const std::vector<unsigned char>& bytes, std::size_t offset) {
        A value; std::memcpy(&value, bytes.data() + offset, sizeof(value)); return value;
    };
    const auto header = read(address, 24);
    if (header.size() != 24) throw NativeObservation::ReadError("short ZMap header");
    const auto table = at(header, 4), buckets = at(header, 8), count = at(header, 12);
    if (at(header, 0) != 0xAF2074 || !buckets || buckets > 65536 || count > 65536 || (count && !table))
        throw NativeObservation::ReadError("invalid skill ZMap header");
    const auto pointers = table ? read(table, buckets * 4) : std::vector<unsigned char>{};
    if (table && pointers.size() != buckets * 4) throw NativeObservation::ReadError("short ZMap buckets");
    std::set<A> visited;
    std::map<A, A> result;
    std::vector<std::pair<A, std::vector<unsigned char>>> nodeSnapshots;
    for (std::size_t i = 0; i < pointers.size(); i += 4) {
        auto node = at(pointers, i);
        while (node) {
            if (visited.size() >= count || !visited.insert(node).second)
                throw NativeObservation::ReadError("invalid skill ZMap chain");
            const auto data = read(node, 16);
            if (data.size() != 16 || at(data, 0) != 0xAF3314 || !result.emplace(at(data, 8), at(data, 12)).second)
                throw NativeObservation::ReadError("invalid skill ZMap node");
            nodeSnapshots.emplace_back(node, data);
            node = at(data, 4);
        }
    }
    for (const auto& snapshot : nodeSnapshots)
        if (read(snapshot.first, snapshot.second.size()) != snapshot.second)
            throw NativeObservation::ReadError("skill ZMap node changed");
    if (visited.size() != count || read(address, 24) != header || (table && read(table, pointers.size()) != pointers))
        throw NativeObservation::ReadError("skill ZMap changed");
    return result;
}
// Same-thread, read-only membership check. Group zero is permitted only in
// explicit beginner mode for the three supported skill IDs.
template<class Reader>
inline bool GroupContains(Reader read, std::uint32_t manager, const std::vector<std::uint32_t>& groups,
                          std::uint32_t skill, std::uint32_t expectedObject, bool beginnerGroup = false) {
    using A = std::uint32_t;
    if (!manager || manager > UINT32_MAX - 0x1c || !skill || !expectedObject || groups.empty()) return false;
    std::set<A> wanted(groups.begin(), groups.end());
    if (wanted.size() != groups.size()) return false;
    if (beginnerGroup) {
        if (wanted.size() != 1 || !wanted.count(0) || !NativeSkillUp::BeginnerSkill(skill)) return false;
    } else if (wanted.count(0)) return false;
    try {
        std::vector<std::pair<A, std::vector<unsigned char>>> snapshots;
        auto take = [&](A address, std::size_t size) {
            if (!address || size > UINT32_MAX || address > UINT32_MAX - (size - 1))
                throw NativeObservation::ReadError("invalid group address");
            auto bytes = read(address, size);
            if (bytes.size() != size) throw NativeObservation::ReadError("short group read");
            snapshots.emplace_back(address, bytes);
            return bytes;
        };
        auto at = [](const std::vector<unsigned char>& bytes, std::size_t offset) {
            A value; std::memcpy(&value, bytes.data() + offset, 4); return value;
        };
        const auto header = take(manager + 0x1c, 24);
        const auto table = at(header, 4), buckets = at(header, 8), count = at(header, 12);
        if (at(header, 0) != 0xB3F4C8 || !buckets || buckets > 65536 || count > 65536 || (count && !table)) return false;
        const auto pointers = table ? take(table, buckets * 4) : std::vector<unsigned char>{};
        std::set<A> nodes, keys;
        bool found = false;
        for (std::size_t i = 0; i < pointers.size(); i += 4) {
            auto node = at(pointers, i);
            while (node) {
                if (nodes.size() >= count || !nodes.insert(node).second) return false;
                const auto record = take(node, 20);
                const auto key = at(record, 8), group = at(record, 16);
                if (at(record, 0) != 0xAFE390 || !keys.insert(key).second || !group) return false;
                if (wanted.count(key)) {
                    if (group > UINT32_MAX - 8) return false;
                    const auto array = at(take(group + 8, 4), 0);
                    if (array) {
                        if (array < 4) return false;
                        const auto length = at(take(array - 4, 4), 0);
                        if (length > 4096) return false;
                        const auto entries = length ? take(array, length * 8) : std::vector<unsigned char>{};
                        std::set<A> ids, objects;
                        for (A j = 0; j < length; ++j) {
                            const auto object = at(entries, j * 8 + 4);
                            if (!object || !objects.insert(object).second) return false;
                            const auto id = at(take(object, 4), 0);
                            if (!id || !ids.insert(id).second) return false;
                            if (id == skill) {
                                if (object != expectedObject || found) return false;
                                found = true;
                            }
                        }
                    }
                }
                node = at(record, 4);
            }
        }
        if (nodes.size() != count) return false;
        for (const auto& snapshot : snapshots)
            if (read(snapshot.first, snapshot.second.size()) != snapshot.second) return false;
        return found;
    } catch (const NativeObservation::ReadError&) { return false; }
}
// Reproduce the ordinary window's visibility filter for the three beginner
// skills. Missing data is unknown, not an empty skill map or zero flag.
struct BeginnerVisibilitySnapshot {
    std::vector<unsigned char> flags;
    bool levelPresent = false;
    std::uint32_t level = 0;
    bool operator==(const BeginnerVisibilitySnapshot& other) const {
        return flags == other.flags && levelPresent == other.levelPresent && level == other.level;
    }
};
template<class Reader>
inline bool BeginnerVisible(Reader read, std::uint32_t character, std::uint32_t skill, std::uint32_t object,
                            BeginnerVisibilitySnapshot& snapshot) {
    if (!NativeSkillUp::BeginnerSkill(skill) || !character || character > UINT32_MAX - 0x467
        || !object || object > UINT32_MAX - 0x3b) return false;
    try {
        const auto flags = read(object + 0x28, 20);
        if (flags.size() != 20) return false;
        std::uint32_t hiddenWhenAbsent = 0, requiresLearned = 0;
        std::memcpy(&hiddenWhenAbsent, flags.data(), 4);
        std::memcpy(&requiresLearned, flags.data() + 0x10, 4);
        const auto levels = MapRecords(read, character + 0x467);
        const auto found = levels.find(skill);
        if (found == levels.end() && hiddenWhenAbsent != 0) return false;
        if (requiresLearned != 0 && (found == levels.end() || found->second == 0)) return false;
        if (read(object + 0x28, 20) != flags) return false;
        snapshot = {flags, found != levels.end(), found == levels.end() ? 0u : found->second};
        return true;
    } catch (const NativeObservation::ReadError&) { return false; }
}
// Ordinary skill window cumulative stage-point gate. This is only one
// eligibility condition; membership and all other checks remain mandatory.
enum class StagePointsResult { Allowed, Limit, Unavailable };
template<class Reader>
inline StagePointsResult StagePointsDecision(Reader read, std::uint32_t character, std::uint32_t level,
                                             std::uint32_t skill, std::uint32_t remaining) {
    if (!character || character > UINT32_MAX - 0x467 || !level || level > 255 || !skill || skill > INT32_MAX || !remaining) return StagePointsResult::Unavailable;
    const auto q = skill / 10000;
    try {
        const auto records = MapRecords(read, character + 0x467);
        for (const auto& record : records)
            if (!record.first || record.first > INT32_MAX || record.second > INT32_MAX) return StagePointsResult::Unavailable;
        if (q % 100 == 0 || q % 10 > 2) return StagePointsResult::Allowed;
        std::uint64_t sum = 0;
        const auto category = q % 10;
        for (const auto& record : records) {
            const auto group = record.first / 10000;
            if ((category == 0 && group % 100 != 0 && group % 10 == 0) ||
                (category != 0 && group % 10 == category)) {
                sum += record.second;
                if (sum > UINT32_MAX) return StagePointsResult::Unavailable;
            }
        }
        const std::int64_t limit = 3LL * level - (category == 0 ? 89 : category == 1 ? 209 : 357);
        return limit >= 0 && sum + remaining <= static_cast<std::uint64_t>(limit)
            ? StagePointsResult::Allowed : StagePointsResult::Limit;
    } catch (const NativeObservation::ReadError&) { return StagePointsResult::Unavailable; }
}
template<class Reader>
inline bool StagePointsEligible(Reader read, std::uint32_t character, std::uint32_t level,
                                std::uint32_t skill, std::uint32_t remaining) {
    return StagePointsDecision(read, character, level, skill, remaining) == StagePointsResult::Allowed;
}
// V17 0x765e9e sums base levels across all twelve beginner IDs.
// A negative or otherwise inconsistent result is unknown for admission.
template<class Reader>
inline bool BeginnerPoints(Reader read, std::uint32_t character, std::uint32_t level, std::uint32_t& points) {
    if (!character || !level || level > 255) return false;
    try {
        const auto levels = MapRecords(read, character + 0x467);
        const std::array<std::uint32_t, 12> ids{{1000,1001,1002,10001000,10001001,10001002,
            20001000,20001001,20001002,20011000,20011001,20011002}};
        const std::uint32_t available = (level < 7 ? level : 7) - 1;
        std::uint32_t used = 0;
        for (const auto id : ids) {
            const auto item = levels.find(id);
            if (item != levels.end()) {
                if (item->second > available - used) return false;
                used += item->second;
            }
        }
        points = available - used;
        return true;
    } catch (const NativeObservation::ReadError&) { return false; }
}
struct JobSp { std::uint32_t character; std::uint32_t job; std::uint32_t sp; };
// Supply the fresh CaptureState result from this game-thread callback. Only the
// two observed job/skill families use this ordinary SP field here.
inline bool CaptureJobSp(const MapleControl::State& state, const NativeSkillUp::Request& request, JobSp& result) {
    const auto& character = state.character;
    if (!state.characterKnown || !character.known[1] || !character.known[11] ||
        character.id != request.character || !NativeSkillUp::SupportedSkill(character.values[1], request.skill))
        return false;
    result = {character.id, character.values[1], character.values[11]};
    return true;
}
struct Levels { std::uint32_t base; std::int32_t delta; };
template<class Reader>
inline Levels SkillLevels(Reader read, std::uint32_t character, std::uint32_t skill) {
    const auto base = MapRecords(read, character + 0x467);
    const auto delta = MapRecords(read, character + 0x47F);
    const auto b = base.find(skill), d = delta.find(skill);
    std::int32_t signedDelta = 0;
    if (d != delta.end()) std::memcpy(&signedDelta, &d->second, sizeof(signedDelta));
    return {b == base.end() ? 0u : b->second, signedDelta};
}
// Read-only part of the preflight. Caller must obtain the object on the game
// thread and separately validate character, job, SP, levels and scene.
// A successful resource read alone never authorizes a skill-up.
inline std::uint32_t ResourceCount(std::uint32_t skillObject, std::uint32_t skillId) {
    using NativeObservation::Read;
    using NativeObservation::ReadError;
    using Address = std::uint32_t;
    const std::array<unsigned char, 29> getter = {{
        0x8b,0x44,0x24,0x08,0x85,0xc0,0x75,0x07,0xb8,0x03,0x40,0x00,0x80,0xeb,0x0b,0x8b,
        0x4c,0x24,0x04,0x8b,0x49,0x30,0x89,0x08,0x33,0xc0,0xc2,0x08,0x00}};
    const std::array<Address, 16> table = {{
        0x50C034FA,0x50C034E9,0x50C0391D,0x50C0D90A,
        0x50C0D939,0x50C0CF8F,0x50C0CF52,0x50C0CD03,
        0x50C0CCE6,0x50C0CD7A,0x50C0D323,0x50C11666,
        0x50C034C3,0x50C0349D,0x50C102FA,0x50C102FA}};
    if (!skillObject || Read<std::array<Address, 16>>(0x50C131C4) != table ||
        Read<std::array<unsigned char, 29>>(0x50C0CCE6) != getter ||
        Read<Address>(skillObject) != skillId)
        throw ReadError("skill resource identity or PCOM fingerprint mismatch");
    const auto binding = Read<Address>(skillObject + 0x5C);
    if (!binding || Read<Address>(binding) != 0x50C131C4)
        throw ReadError("skill resource binding is unavailable");
    const auto count = Read<Address>(binding + 0x30);
    if (count < 1 || count > 255 || Read<Address>(skillObject + 0x5C) != binding ||
        Read<Address>(skillObject) != skillId)
        throw ReadError("skill resource count or identity changed");
    return count;
}
} }
