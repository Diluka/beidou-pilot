// SPDX-License-Identifier: AGPL-3.0-or-later
#include "../ezorsia/NativeSkillUpFacts.h"
#include "../ezorsia/NativeSkillUpStage.h"
#include <cassert>
#include <cstring>
#include <map>

int main() {
    using namespace BeiDouBridge::NativeSkillUpFacts;
    MapleControl::State state;
    BeiDouBridge::NativeSkillUp::Request request;
    request.character = 42; request.skill = 1000000;
    JobSp jobsp{99, 99, 99};
    assert(!CaptureJobSp(state, request, jobsp) && jobsp.character == 99);
    state.characterKnown = true; state.character.id = 42;
    state.character.known[1] = state.character.known[11] = true;
    state.character.values[1] = 100; state.character.values[11] = 4;
    assert(CaptureJobSp(state, request, jobsp) && jobsp.job == 100 && jobsp.sp == 4);
    state.character.known[11] = false;
    assert(!CaptureJobSp(state, request, jobsp));
    state.character.known[11] = true;
    state.character.values[1] = 210; request.skill = 2101001;
    assert(CaptureJobSp(state, request, jobsp) && jobsp.job == 210);
    for (auto id : {1000u, 1001u, 1002u}) {
        request.skill = id;
        assert(CaptureJobSp(state, request, jobsp) && jobsp.job == 210);
    }
    request.skill = 1003; assert(!CaptureJobSp(state, request, jobsp));
    state.character.values[1] = 100;
    for (auto id : {1000u, 1001u, 1002u}) {
        request.skill = id;
        assert(CaptureJobSp(state, request, jobsp) && jobsp.job == 100);
    }
    state.character.values[1] = 210; request.skill = 1000000;
    assert(!CaptureJobSp(state, request, jobsp));
    state.character.id = 43; request.skill = 2101001;
    assert(!CaptureJobSp(state, request, jobsp));
    std::map<std::uint32_t, unsigned char> memory;
    auto put = [&](std::uint32_t address, std::uint32_t value) {
        for (int i = 0; i < 4; ++i) memory[address + i] = static_cast<unsigned char>(value >> (8 * i));
    };
    auto reader = [&](std::uint32_t address, std::size_t size) {
        std::vector<unsigned char> result;
        for (std::size_t i = 0; i < size; ++i) {
            auto it = memory.find(address + static_cast<std::uint32_t>(i));
            if (it == memory.end()) throw NativeObservation::ReadError("unreadable");
            result.push_back(it->second);
        }
        return result;
    };
    auto map = [&](std::uint32_t address, std::uint32_t table, std::uint32_t node, std::uint32_t value) {
        for (int i = 0; i < 24; ++i) memory[address + i] = 0;
        put(address, 0xAF2074); put(address + 4, table); put(address + 8, 1); put(address + 12, 1);
        put(table, node); put(node, 0xAF3314); put(node + 4, 0); put(node + 8, 1000000); put(node + 12, value);
    };
    map(0x1467, 0x2000, 0x3000, 3);
    map(0x147F, 0x2100, 0x3100, 0xFFFFFFFF);
    auto levels = SkillLevels(reader, 0x1000, 1000000);
    assert(levels.base == 3 && levels.delta == -1);
    levels = SkillLevels(reader, 0x1000, 1000001);
    assert(levels.base == 0 && levels.delta == 0);
    std::uint32_t points = 99;
    assert(BeginnerPoints(reader, 0x1000, 8, points) && points == 6);
    put(0x3008, 1000); put(0x300C, 3);
    assert(BeginnerPoints(reader, 0x1000, 7, points) && points == 3);
    for (auto id : {1000u, 1001u, 1002u}) {
        put(0x3008, id); put(0x300C, 2);
        assert(BeginnerPoints(reader, 0x1000, 7, points) && points == 4);
    }
    put(0x3008, 20011002); put(0x300C, 7);
    points = 99;
    assert(!BeginnerPoints(reader, 0x1000, 7, points) && points == 99);
    assert(!BeginnerPoints(reader, 0x1000, 0, points));
    assert(!BeginnerPoints(reader, 0x9000, 7, points));
    // Stage-point limits use all matching base records, not deltas.
    put(0x3008, 1100000); put(0x300c, 1);
    assert(StagePointsEligible(reader, 0x1000, 30, 1100001, 1) == false);
    assert(StagePointsEligible(reader, 0x1000, 31, 1100001, 3));
    assert(StagePointsDecision(reader, 0x1000, 31, 1100001, 3) == StagePointsResult::Allowed);
    assert(StagePointsDecision(reader, 0x1000, 30, 1100001, 1) == StagePointsResult::Limit);
    assert(StagePointsDecision(reader, 0x9000, 30, 1100001, 1) == StagePointsResult::Unavailable);
    using BeiDouBridge::NativeSkillUp::StageFailure;
    using BeiDouBridge::NativeSkillUp::LevelRecheckFailure;
    assert(std::string(LevelRecheckFailure(false, 30, 31)) == "skill_up_state_unavailable");
    assert(std::string(LevelRecheckFailure(true, 30, 31)) == "skill_up_state_changed");
    assert(LevelRecheckFailure(true, 30, 30) == nullptr);
    assert(StageFailure(reader, 0x1000, true, 31, 1100001, 3) == nullptr);
    assert(std::string(StageFailure(reader, 0x1000, true, 30, 1100001, 1)) == "skill_up_stage_limit");
    assert(std::string(StageFailure(reader, 0x9000, true, 30, 1100001, 1)) == "skill_up_state_unavailable");
    assert(std::string(StageFailure(reader, 0x1000, false, 30, 1100001, 1)) == "skill_up_state_unavailable");
    assert(!StagePointsEligible(reader, 0x1000, 29, 1100001, 1));
    put(0x3008, 1110000); put(0x300c, 1);
    assert(!StagePointsEligible(reader, 0x1000, 70, 1110001, 1));
    assert(StagePointsEligible(reader, 0x1000, 71, 1110001, 3));
    put(0x3008, 1120000);
    assert(!StagePointsEligible(reader, 0x1000, 119, 1120001, 1));
    assert(StagePointsEligible(reader, 0x1000, 120, 1120001, 2));
    put(0x300c, 0xffffffffu);
    assert(!StagePointsEligible(reader, 0x1000, 120, 1120001, 1));
    assert(!StagePointsEligible(reader, 0x9000, 120, 1120001, 1));
    assert(!StagePointsEligible(reader, 0x9000, 120, 1000000, 1)); // unknown map even for exempt group
    assert(!StagePointsEligible(reader, 0x1000, 120, 0xffffffffu, 1));
    put(0x3008, 0xffffffffu);
    assert(!StagePointsEligible(reader, 0x1000, 120, 1000000, 1));
    put(0x3008, 2100000); put(0x300c, 1);
    put(0x1467 + 12, 2); put(0x3004, 0x3200);
    put(0x3200, 0xAF3314); put(0x3204, 0); put(0x3208, 2200000); put(0x320c, 1);
    assert(StagePointsEligible(reader, 0x1000, 32, 2101001, 5));
    assert(!StagePointsEligible(reader, 0x1000, 32, 2101001, 6));
    assert(StageFailure(reader, 0x1000, true, 32, 2101001, 5) == nullptr);
    // A second preflight must reject if another category-matching level changed.
    put(0x320c, 2);
    assert(!StagePointsEligible(reader, 0x1000, 32, 2101001, 5));
    assert(std::string(StageFailure(reader, 0x1000, true, 32, 2101001, 5)) == "skill_up_stage_limit");
    put(0x320c, 1);
    put(0x300c, 0x80000000u); put(0x320c, 1);
    assert(!StagePointsEligible(reader, 0x1000, 255, 2101001, 1));
    assert(!StagePointsEligible(reader, 0x1000, 255, 1110000, 1)); // nonmatching category
    assert(!StagePointsEligible(reader, 0x1000, 255, 1000000, 1)); // exempt category
    assert(StagePointsDecision(reader, 0x1000, 255, 1000000, 1) == StagePointsResult::Unavailable);
    assert(StagePointsDecision(reader, 0x1000, 255, 1110000, 1) == StagePointsResult::Unavailable);
    put(0x300c, 1);
    int nodeReads = 0;
    auto changingNode = [&](std::uint32_t address, std::size_t size) {
        auto bytes = reader(address, size);
        if (address == 0x3000 && ++nodeReads == 2) bytes[12] ^= 1;
        return bytes;
    };
    assert(!StagePointsEligible(changingNode, 0x1000, 32, 2101001, 1) && nodeReads == 2);
    put(0x1467 + 12, 0); put(0x2000, 0);
    assert(StagePointsEligible(reader, 0x1000, 30, 2101001, 1));
    put(0x1467 + 12, 1); put(0x2000, 0x3000); put(0x3004, 0);
    // One group with one skill object, then malformed and changing snapshots.
    for (int i = 0; i < 24; ++i) memory[0x501c + i] = 0;
    put(0x501c, 0xB3F4C8); put(0x5020, 0x5100); put(0x5024, 1); put(0x5028, 1);
    put(0x5100, 0x5200); put(0x5200, 0xAFE390); put(0x5204, 0);
    put(0x5208, 100); put(0x520c, 0); put(0x5210, 0x5300);
    put(0x5308, 0x5404); put(0x5400, 1); put(0x5404, 0); put(0x5408, 0x5500); put(0x5500, 1000000);
    assert(GroupContains(reader, 0x5000, {100}, 1000000, 0x5500));
    assert(!GroupContains(reader, 0x5000, {0}, 1000000, 0x5500));
    assert(!GroupContains(reader, 0x5000, {100}, 1000000, 0x5504));
    assert(!GroupContains(reader, 0x5000, {200}, 1000000, 0x5500));
    put(0x5204, 0x5200);
    assert(!GroupContains(reader, 0x5000, {100}, 1000000, 0x5500));
    put(0x5204, 0); put(0x5400, 4097);
    assert(!GroupContains(reader, 0x5000, {100}, 1000000, 0x5500));
    put(0x5400, 1);
    int headerReads = 0;
    auto changing = [&](std::uint32_t address, std::size_t size) {
        auto bytes = reader(address, size);
        if (address == 0x501c && ++headerReads == 2) bytes[0] ^= 1;
        return bytes;
    };
    assert(!GroupContains(changing, 0x5000, {100}, 1000000, 0x5500));
    // Distinct nodes with the same group key must not be accepted.
    put(0x5028, 2); put(0x5204, 0x5600);
    put(0x5600, 0xAFE390); put(0x5604, 0); put(0x5608, 100);
    put(0x560c, 0); put(0x5610, 0x5300);
    assert(!GroupContains(reader, 0x5000, {100}, 1000000, 0x5500));
    put(0x5028, 1); put(0x5204, 0);
    // Duplicate object pointer and duplicate ID on distinct objects.
    put(0x5400, 2); put(0x540c, 0); put(0x5410, 0x5500);
    assert(!GroupContains(reader, 0x5000, {100}, 1000000, 0x5500));
    put(0x5410, 0x5700); put(0x5700, 1000000);
    assert(!GroupContains(reader, 0x5000, {100}, 1000000, 0x5500));
    put(0x5400, 1);
    assert(!GroupContains(reader, 0xfffffff0u, {100}, 1000000, 0x5500));
    put(0x5308, 0xfffffffcu); put(0xfffffff8u, 1);
    assert(!GroupContains(reader, 0x5000, {100}, 1000000, 0x5500));
    put(0x5308, 0x5404);
    for (auto changedAddress : {0x5404u, 0x5500u}) {
        int reads = 0;
        auto mutating = [&](std::uint32_t address, std::size_t size) {
            auto bytes = reader(address, size);
            if (address == changedAddress && ++reads == 2) bytes[0] ^= 1;
            return bytes;
        };
        assert(!GroupContains(mutating, 0x5000, {100}, 1000000, 0x5500));
        assert(reads == 2);
    }
    put(0x3004, 0x3000);
    bool rejected = false;
    try { SkillLevels(reader, 0x1000, 1000000); } catch (const NativeObservation::ReadError&) { rejected = true; }
    assert(rejected);
}
