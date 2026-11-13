// SPDX-License-Identifier: AGPL-3.0-or-later
#include "LoginPageObservation.h"
#include <cassert>
#include <string>
#include <map>
#include <stdexcept>

int main() {
    std::array<std::int32_t, 4> projection{};
    using NativeObservation::ProjectStageLayer;
    assert(ProjectStageLayer({10, 20, 110, 70}, {-10, -20, 790, 580}, 100, 50, projection));
    assert((projection == std::array<std::int32_t, 4>{20, 40, 120, 90}));
    assert(!ProjectStageLayer({10, 20, 111, 70}, {-10, -20, 790, 580}, 100, 50, projection));
    assert(!ProjectStageLayer({INT32_MAX - 1, 0, INT32_MAX, 1}, {-2, 0, 0, 0}, 1, 1, projection));
    using NativeObservation::ObservedLoginPage;
    const std::array<std::uint32_t, 3> terms{0x00AF79C8, 0x00AF797C, 0x00AF7978};
    const std::array<std::uint32_t, 3> gender{0x00AF7298, 0x00AF724C, 0x00AF7248};
    assert(std::string(ObservedLoginPage(true, terms, 431, 426)) == "terms");
    assert(std::string(ObservedLoginPage(true, gender, 354, 259)) == "gender");
    assert(ObservedLoginPage(false, terms, 431, 426) == nullptr);
    assert(ObservedLoginPage(true, terms, 430, 426) == nullptr);
    assert(ObservedLoginPage(true, gender, 354, 260) == nullptr);
    assert(ObservedLoginPage(true, {0x00AF79C8, 0, 0x00AF7978}, 431, 426) == nullptr);
    assert(ObservedLoginPage(true, {0, 0, 0}, 431, 426) == nullptr);
    using NativeObservation::StableRawGenderSelection;
    assert(StableRawGenderSelection(0, 0, true));
    assert(StableRawGenderSelection(1, 1, true));
    assert(!StableRawGenderSelection(2, 2, true));
    assert(!StableRawGenderSelection(0, 1, true));
    assert(!StableRawGenderSelection(0, 0, false));

    const std::uint32_t stage = 0x10000, window = 0x20000;
    std::map<std::uint32_t, std::uint32_t> memory{
        {0x00BEDED4, stage},      {stage, 0x00AF6B24},  {window, 0x00AF777C}, {window + 4, 0x00AF7730},
        {window + 8, 0x00AF772C}, {window + 0x24, 225}, {window + 0x28, 377}, {window + 0x6C, stage},
        {stage + 0x168, 4},       {stage + 0x16C, 0},   {stage + 0x170, 0},   {stage + 0x234, 0}};
    for (std::uint32_t i = 0; i < 8; ++i) {
        const auto p = 0x30000 + i * 0x100;
        memory[stage + 0x244 + 4 * i] = p;
        memory[p - 4] = 2;
        memory[p] = 100 + i;
    }
    auto read32 = [&](std::uint32_t at) { return memory.at(at); };
    auto read8 = [&](std::uint32_t at) { return static_cast<std::uint8_t>(memory.at(at)); };
    std::array<std::uint32_t, 8> values{};
    std::uint8_t selector = 0;
    std::uint32_t job = 0;
    memory[stage + 0x214] = 42;
    using NativeObservation::RawAppearanceSnapshot;
    assert(RawAppearanceSnapshot(window, stage, read32, read8, values, selector, job));
    assert(values[0] == 100 && values[7] == 107 && job == 42);
    for (std::uint32_t i = 0; i < 8; ++i) memory[stage + 0x268 + 4 * i] = 0x30000 + i * 0x100;
    memory[stage + 0x234] = 1;
    assert(RawAppearanceSnapshot(window, stage, read32, read8, values, selector, job));
    assert(values[0] == 100 && values[7] == 107 && job == 42);
    assert(selector == 1);
    int jobReads = 0;
    auto changingJob = [&](std::uint32_t at) {
        auto value = memory.at(at);
        return at == stage + 0x214 && ++jobReads == 2 ? value + 1 : value;
    };
    assert(!RawAppearanceSnapshot(window, stage, changingJob, read8, values, selector, job));
    memory[stage + 0x234] = 2;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values, selector, job));
    memory[stage + 0x234] = 0;
    memory[window + 0x6C] = stage + 4;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values, selector, job));
    memory[window + 0x6C] = stage;
    memory[stage + 0x170] = 1;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values, selector, job));
    memory[stage + 0x170] = 0;
    memory[0x30000 - 4] = 0;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values, selector, job));
    memory[0x30000 - 4] = 2;
    int reads = 0;
    auto changing = [&](std::uint32_t at) {
        auto value = memory.at(at);
        return at == 0x30000 && ++reads == 2 ? value + 1 : value;
    };
    assert(!RawAppearanceSnapshot(window, stage, changing, read8, values, selector, job));
    assert(!RawAppearanceSnapshot(window, UINT32_MAX, read32, read8, values, selector, job));
    assert(!RawAppearanceSnapshot(UINT32_MAX - 0x6E, stage, read32, read8, values, selector, job));
    memory[stage + 0x244] = UINT32_MAX - 2;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values, selector, job));
    memory[stage + 0x244] = 0x30000;
    memory.erase(0x30000 - 4);
    bool failed = false;
    try {
        RawAppearanceSnapshot(window, stage, read32, read8, values, selector, job);
    } catch (const std::out_of_range&) {
        failed = true;
    }
    assert(failed);

    const std::uint32_t world = 0x40000;
    memory[0x00BEDA5C] = world;
    memory[world] = 0x00AF7A90;
    memory[world + 4] = 0x00AF7A44;
    memory[world + 8] = 0x00AF7A40;
    memory[world + 0x80] = stage;
    memory[world + 0x84] = 3;
    memory[world + 0x88] = UINT32_MAX;
    memory[stage + 0x168] = 1;
    std::uint32_t count = 0, index = 0;
    using NativeObservation::RawWorldSelection;
    assert(RawWorldSelection(stage, read32, count, index) && count == 3 && index == UINT32_MAX);
    memory[world + 0x88] = 2;
    assert(RawWorldSelection(stage, read32, count, index) && index == 2);
    memory[world + 0x88] = 3;
    assert(!RawWorldSelection(stage, read32, count, index));
    memory[world + 0x88] = 0;
    memory[world + 0x84] = 31;
    assert(!RawWorldSelection(stage, read32, count, index));
    memory[world + 0x84] = 3;
    memory[world + 0x80] = stage + 4;
    assert(!RawWorldSelection(stage, read32, count, index));
    memory[world + 0x80] = stage;
    int worldReads = 0;
    auto changingWorld = [&](std::uint32_t at) {
        auto value = memory.at(at);
        return at == world + 0x88 && ++worldReads == 2 ? value + 1 : value;
    };
    assert(!RawWorldSelection(stage, changingWorld, count, index));
    memory[0x00BEDA5C] = UINT32_MAX - 0x8A;
    assert(!RawWorldSelection(stage, read32, count, index));
    memory[0x00BEDA5C] = world;
    memory[world + 0x88] = 1;
    memory[stage + 0x18C] = 0x90004;
    memory[0x90000] = 3;
    memory[0x90024] = 17;
    auto read16 = [&](std::uint32_t at) { return static_cast<std::uint16_t>(memory.at(at)); };
    std::uint16_t rawId = 0;
    using NativeObservation::RawWorldId;
    assert(RawWorldId(stage, read32, read16, rawId) && rawId == 17);
    memory[0x90000] = 1;
    assert(!RawWorldId(stage, read32, read16, rawId));
    memory[0x90000] = 3;
    memory[stage + 0x18C] = UINT32_MAX - 15;
    memory[UINT32_MAX - 19] = 3;
    assert(!RawWorldId(stage, read32, read16, rawId));
    memory[stage + 0x18C] = 0x90004;
    int idReads = 0;
    auto changingId = [&](std::uint32_t at) {
        auto value = read16(at);
        return static_cast<std::uint16_t>(value + (++idReads == 2 ? 1 : 0));
    };
    assert(!RawWorldId(stage, read32, changingId, rawId));
    memory[world + 0x88] = UINT32_MAX;
    assert(!RawWorldId(stage, read32, read16, rawId));

    const std::uint32_t manager = 0x50000, account = 0x60000, password = 0x70000;
    memory[stage + 0x168] = 0;
    memory[window] = 0x00AF7940;
    memory[window + 4] = 0x00AF78F4;
    memory[window + 8] = 0x00AF78F0;
    memory[window + 0xCC] = account;
    memory[window + 0xD4] = password;
    memory[0x00BEC20C] = manager;
    memory[manager] = 0x00B3F13C;
    memory[manager + 0x80] = window;
    memory[account + 4] = memory[password + 4] = 0x00AF2B5C;
    memory[account + 0x14] = 1007;
    memory[password + 0x14] = 1008;
    memory[account + 0x24] = memory[password + 0x24] = window;
    memory[manager + 0x88] = account + 4;
    using NativeObservation::LoginEditEmpty;
    using NativeObservation::LoginEditFocus;
    assert(std::string(LoginEditFocus(stage, window, read32)) == "account");
    memory[manager + 0x88] = password + 4;
    assert(std::string(LoginEditFocus(stage, window, read32)) == "password");
    memory[account + 0x34] = 0;
    memory[password + 0x34] = 0x80004;
    memory[0x80000] = 7;
    bool a = false, p = true;
    assert(LoginEditEmpty(stage, window, read32, a, p) && a && !p);
    memory[password + 0x34] = 3;
    assert(!LoginEditEmpty(stage, window, read32, a, p));
    memory[password + 0x34] = 0x80004;
    int focusReads = 0;
    auto changingFocus = [&](std::uint32_t at) {
        auto value = memory.at(at);
        return at == manager + 0x88 && ++focusReads == 2 ? account + 4 : value;
    };
    assert(!LoginEditFocus(stage, window, changingFocus));
    int stringReads = 0;
    auto changingString = [&](std::uint32_t at) {
        auto value = memory.at(at);
        return at == password + 0x34 && ++stringReads == 2 ? 0u : value;
    };
    assert(!LoginEditEmpty(stage, window, changingString, a, p));
    int lengthReads = 0;
    auto changingLength = [&](std::uint32_t at) {
        auto value = memory.at(at);
        return at == 0x80000 && ++lengthReads == 2 ? value + 1 : value;
    };
    assert(!LoginEditEmpty(stage, window, changingLength, a, p));
    int managerReads = 0;
    auto changingManager = [&](std::uint32_t at) {
        auto value = memory.at(at);
        return at == 0x00BEC20C && ++managerReads == 2 ? 0u : value;
    };
    assert(!LoginEditFocus(stage, window, changingManager));
    memory[account + 0x14] = 1;
    assert(!LoginEditFocus(stage, window, read32));
    memory[account + 0x14] = 1007;
    memory[password + 0x24] = 0;
    assert(!LoginEditFocus(stage, window, read32));
    memory[password + 0x24] = window;
    memory[0x80000] = 0;
    assert(LoginEditEmpty(stage, window, read32, a, p) && a && p);
    memory.erase(0x80000);
    failed = false;
    try {
        LoginEditEmpty(stage, window, read32, a, p);
    } catch (const std::out_of_range&) {
        failed = true;
    }
    assert(failed);
    memory[manager + 0x88] = 0;
    assert(!LoginEditFocus(stage, window, read32));
    assert(!LoginEditFocus(stage, UINT32_MAX - 0xD6, read32));

    memory[stage + 0x168] = 4;
    memory[0x00BEDA44] = window;
    memory[window] = 0x00AF7564;
    memory[window + 4] = 0x00AF7518;
    memory[window + 8] = 0x00AF7514;
    memory[window + 0x24] = 201;
    memory[window + 0x28] = 224;
    memory[window + 0x6C] = stage;
    const std::uint32_t edit = 0xA0000, text = 0xB0004;
    memory[window + 0x84] = edit;
    memory[edit] = 0x00AF2BA8;
    memory[edit + 4] = 0x00AF2B5C;
    memory[edit + 8] = 0x00AF2B58;
    memory[edit + 0x14] = 1002;
    memory[edit + 0x24] = window;
    memory[edit + 0x34] = text;
    memory[text - 4] = 2;
    memory[text] = 'A';
    memory[text + 1] = 'b';
    memory[text + 2] = 0;
    std::string name;
    using NativeObservation::CreationNameCandidate;
    assert(CreationNameCandidate(stage, window, read32, read8, name) && name == "Ab");
    memory[text + 1] = 0x80;
    assert(!CreationNameCandidate(stage, window, read32, read8, name));
    memory[text + 1] = 'b';
    memory[text + 2] = 1;
    assert(!CreationNameCandidate(stage, window, read32, read8, name));
    memory[text + 2] = 0;
    memory[edit + 0x24] = 0;
    assert(!CreationNameCandidate(stage, window, read32, read8, name));
    memory[edit + 0x24] = window;
    memory[text - 4] = 256;
    assert(!CreationNameCandidate(stage, window, read32, read8, name));
    memory[text - 4] = 0;
    assert(!CreationNameCandidate(stage, window, read32, read8, name)); // Nonzero terminator.
    memory[text] = 0;
    assert(CreationNameCandidate(stage, window, read32, read8, name) && name.empty());
    memory.erase(text - 4);
    bool missingLength = false;
    try {
        CreationNameCandidate(stage, window, read32, read8, name);
    } catch (const std::out_of_range&) {
        missingLength = true;
    }
    assert(missingLength);
    memory[text - 4] = 0;
    memory.erase(text);
    bool missingTerminator = false;
    try {
        CreationNameCandidate(stage, window, read32, read8, name);
    } catch (const std::out_of_range&) {
        missingTerminator = true;
    }
    assert(missingTerminator);
    memory[text] = 0;
    memory[edit + 0x34] = 0;
    assert(CreationNameCandidate(stage, window, read32, read8, name) && name.empty());
    int pointerReads = 0;
    auto changingEmpty = [&](std::uint32_t at) {
        auto value = read32(at);
        return at == edit + 0x34 && ++pointerReads == 2 ? text : value;
    };
    assert(!CreationNameCandidate(stage, window, changingEmpty, read8, name));
    memory[text] = 'A';
    memory[edit + 0x34] = UINT32_MAX;
    memory[UINT32_MAX - 4] = 2;
    assert(!CreationNameCandidate(stage, window, read32, read8, name));
    memory[edit + 0x34] = text;
    memory[text - 4] = 2;
    int charReads = 0;
    auto changingName = [&](std::uint32_t at) {
        auto value = read8(at);
        return static_cast<std::uint8_t>(at == text && ++charReads == 2 ? 'C' : value);
    };
    assert(!CreationNameCandidate(stage, window, read32, changingName, name));
    int stageReads = 0;
    auto changingStage = [&](std::uint32_t at) {
        auto value = read32(at);
        return at == stage && ++stageReads == 3 ? 0u : value;
    };
    assert(!CreationNameCandidate(stage, window, changingStage, read8, name));
    int editReads = 0;
    auto changingEdit = [&](std::uint32_t at) {
        auto value = read32(at);
        return at == edit + 4 && ++editReads == 3 ? 0u : value;
    };
    assert(!CreationNameCandidate(stage, window, changingEdit, read8, name));
    using NativeObservation::CreationNameFocus;
    bool focused = false;
    memory[manager + 0x80] = window;
    memory[manager + 0x88] = edit + 4;
    assert(CreationNameFocus(stage, window, read32, focused) && focused);
    memory[manager + 0x88] = 0;
    assert(CreationNameFocus(stage, window, read32, focused) && !focused);
    memory[manager + 0x80] = 0;
    assert(!CreationNameFocus(stage, window, read32, focused));
    memory[manager + 0x80] = window;
    memory[manager + 0x88] = edit + 4;
    int handlerReads = 0;
    auto changingHandler = [&](std::uint32_t at) {
        auto value = read32(at);
        return at == manager + 0x88 && ++handlerReads == 2 ? 0u : value;
    };
    assert(!CreationNameFocus(stage, window, changingHandler, focused));
    memory[edit + 0x14] = 0;
    assert(!CreationNameFocus(stage, window, read32, focused));
    memory[edit + 0x14] = 1002;
    memory[manager + 0x80] = window;
    memory.erase(manager + 0x88);
    bool focusError = false;
    try {
        CreationNameFocus(stage, window, read32, focused);
    } catch (const std::out_of_range&) {
        focusError = true;
    }
    assert(focusError);
}
