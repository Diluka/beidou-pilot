// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <array>
#include <cstdint>

namespace NativeObservation {
// Each signature is based on one GUI sample; it is a candidate, not proof
// of page semantics or of the absence of other dialogs.
inline const char* ObservedLoginPage(bool loginStage, const std::array<std::uint32_t, 3>& tables,
    int width, int height) {
    if (!loginStage) return nullptr;
    if (tables == std::array<std::uint32_t, 3>{0x00AF79C8, 0x00AF797C, 0x00AF7978} &&
        width == 431 && height == 426) return "terms";
    if (tables == std::array<std::uint32_t, 3>{0x00AF7298, 0x00AF724C, 0x00AF7248} &&
        width == 354 && height == 259) return "gender";
    return nullptr;
}

// Read only the first DWORD of each nonempty native array; no native length
// controls allocation or traversal. The caller isolates memory-read failures.
template <class Read32, class Read8>
bool RawAppearanceSnapshot(std::uint32_t window, std::uint32_t stage, Read32 read32, Read8 read8,
    std::array<std::uint32_t, 8>& values) {
    if (window > UINT32_MAX - 0x6F || stage > UINT32_MAX - 0x288) return false;
    struct Sample {
        std::uint8_t selector;
        std::array<std::uint32_t, 8> pointers, lengths, values;
    } samples[2]{};
    for (auto& sample : samples) {
        if (!stage || read32(0x00BEDED4) != stage || read32(stage) != 0x00AF6B24 ||
            read32(window) != 0x00AF777C || read32(window + 4) != 0x00AF7730 ||
            read32(window + 8) != 0x00AF772C || read32(window + 0x24) != 225 ||
            read32(window + 0x28) != 377 || read32(window + 0x6C) != stage ||
            read32(stage + 0x168) != 4 || read32(stage + 0x16C) != 0 ||
            read32(stage + 0x170) != 0) return false;
        sample.selector = read8(stage + 0x234);
        if (sample.selector > 1) return false;
        const auto base = stage + (sample.selector == 0 ? 0x244 : 0x268);
        for (std::uint32_t index = 0; index < 8; ++index) {
            const auto pointer = read32(base + 4 * index);
            if (pointer < 4 || pointer > UINT32_MAX - 3) return false;
            const auto length = read32(pointer - 4);
            if (!length) return false;
            sample.pointers[index] = pointer;
            sample.lengths[index] = length;
            sample.values[index] = read32(pointer);
        }
    }
    if (read32(0x00BEDED4) != stage || read32(stage) != 0x00AF6B24 ||
        read32(window) != 0x00AF777C || read32(window + 4) != 0x00AF7730 ||
        read32(window + 8) != 0x00AF772C || read32(window + 0x24) != 225 ||
        read32(window + 0x28) != 377 || read32(window + 0x6C) != stage ||
        read32(stage + 0x168) != 4 || read32(stage + 0x16C) != 0 ||
        read32(stage + 0x170) != 0 || read8(stage + 0x234) != samples[1].selector) return false;
    if (samples[0].selector != samples[1].selector || samples[0].pointers != samples[1].pointers ||
        samples[0].lengths != samples[1].lengths || samples[0].values != samples[1].values) return false;
    values = samples[0].values;
    return true;
}

inline bool StableRawGenderSelection(std::uint8_t first, std::uint8_t second, bool sameWindow) {
    return sameWindow && first == second && first <= 1;
}
}
