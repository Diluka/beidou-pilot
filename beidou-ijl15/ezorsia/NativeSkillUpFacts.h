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
    for (std::size_t i = 0; i < pointers.size(); i += 4) {
        auto node = at(pointers, i);
        while (node) {
            if (visited.size() >= count || !visited.insert(node).second)
                throw NativeObservation::ReadError("invalid skill ZMap chain");
            const auto data = read(node, 16);
            if (data.size() != 16 || at(data, 0) != 0xAF3314 || !result.emplace(at(data, 8), at(data, 12)).second)
                throw NativeObservation::ReadError("invalid skill ZMap node");
            node = at(data, 4);
        }
    }
    if (visited.size() != count || read(address, 24) != header || (table && read(table, pointers.size()) != pointers))
        throw NativeObservation::ReadError("skill ZMap changed");
    return result;
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
