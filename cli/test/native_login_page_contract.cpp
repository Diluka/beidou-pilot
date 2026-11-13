// SPDX-License-Identifier: AGPL-3.0-or-later
#include "LoginPageObservation.h"
#include <cassert>
#include <string>
#include <map>
#include <stdexcept>

int main() {
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
    using NativeObservation::RawAppearanceSnapshot;
    assert(RawAppearanceSnapshot(window, stage, read32, read8, values));
    assert(values[0] == 100 && values[7] == 107);
    for (std::uint32_t i = 0; i < 8; ++i) memory[stage + 0x268 + 4 * i] = 0x30000 + i * 0x100;
    memory[stage + 0x234] = 1;
    assert(RawAppearanceSnapshot(window, stage, read32, read8, values));
    assert(values[0] == 100 && values[7] == 107);
    memory[stage + 0x234] = 2;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values));
    memory[stage + 0x234] = 0;
    memory[window + 0x6C] = stage + 4;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values));
    memory[window + 0x6C] = stage;
    memory[stage + 0x170] = 1;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values));
    memory[stage + 0x170] = 0;
    memory[0x30000 - 4] = 0;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values));
    memory[0x30000 - 4] = 2;
    int reads = 0;
    auto changing = [&](std::uint32_t at) {
        auto value = memory.at(at);
        return at == 0x30000 && ++reads == 2 ? value + 1 : value;
    };
    assert(!RawAppearanceSnapshot(window, stage, changing, read8, values));
    assert(!RawAppearanceSnapshot(window, UINT32_MAX, read32, read8, values));
    assert(!RawAppearanceSnapshot(UINT32_MAX - 0x6E, stage, read32, read8, values));
    memory[stage + 0x244] = UINT32_MAX - 2;
    assert(!RawAppearanceSnapshot(window, stage, read32, read8, values));
    memory[stage + 0x244] = 0x30000;
    memory.erase(0x30000 - 4);
    bool failed = false;
    try {
        RawAppearanceSnapshot(window, stage, read32, read8, values);
    } catch (const std::out_of_range&) {
        failed = true;
    }
    assert(failed);
}
