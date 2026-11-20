// SPDX-License-Identifier: AGPL-3.0-or-later
#include "../ezorsia/NativeSkillUpFacts.h"
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
    request.skill = 1000000;
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
    put(0x3008, 20011002); put(0x300C, 7);
    points = 99;
    assert(!BeginnerPoints(reader, 0x1000, 7, points) && points == 99);
    assert(!BeginnerPoints(reader, 0x1000, 0, points));
    assert(!BeginnerPoints(reader, 0x9000, 7, points));
    put(0x3004, 0x3000);
    bool rejected = false;
    try { SkillLevels(reader, 0x1000, 1000000); } catch (const NativeObservation::ReadError&) { rejected = true; }
    assert(rejected);
}
