// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <array>
#include <cstdint>
#include <string>

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

// Project only dimension-matched layer bounds using checked signed arithmetic.
inline bool ProjectStageLayer(const std::array<std::int32_t, 4>& layer,
    const std::array<std::int32_t, 4>& camera, std::int32_t width, std::int32_t height,
    std::array<std::int32_t, 4>& result) {
    if (width <= 0 || height <= 0 || static_cast<std::int64_t>(layer[2]) - layer[0] != width ||
        static_cast<std::int64_t>(layer[3]) - layer[1] != height) return false;
    for (int i = 0; i < 4; ++i) {
        const auto value = static_cast<std::int64_t>(layer[i]) - camera[i % 2];
        if (value < INT32_MIN || value > INT32_MAX) return false;
        result[i] = static_cast<std::int32_t>(value);
    }
    return true;
}

// Only classify focus identity; never read edit text or length.
template <class Read32>
const char* LoginEditFocus(std::uint32_t stage, std::uint32_t window, Read32 read32) {
    if (!stage || stage > UINT32_MAX - 0x173 || !window || window > UINT32_MAX - 0xD7) return nullptr;
    std::array<std::uint32_t, 4> previous{};
    for (int sample = 0; sample < 3; ++sample) {
        if (read32(0x00BEDED4) != stage || read32(stage) != 0x00AF6B24 ||
            read32(stage + 0x168) != 0 || read32(stage + 0x16C) != 0 || read32(stage + 0x170) != 0 ||
            read32(window) != 0x00AF7940 || read32(window + 4) != 0x00AF78F4 ||
            read32(window + 8) != 0x00AF78F0) return nullptr;
        const auto manager = read32(0x00BEC20C);
        if (!manager || manager > UINT32_MAX - 0x8B || read32(manager) != 0x00B3F13C) return nullptr;
        const auto account = read32(window + 0xCC);
        const auto password = read32(window + 0xD4);
        if (!account || !password || account == password || account > UINT32_MAX - 0x27 ||
            password > UINT32_MAX - 0x27) return nullptr;
        if (read32(account + 4) != 0x00AF2B5C || read32(password + 4) != 0x00AF2B5C ||
            read32(manager + 0x80) != window ||
            read32(account + 0x14) != 1007 || read32(password + 0x14) != 1008 ||
            read32(account + 0x24) != window || read32(password + 0x24) != window) return nullptr;
        const std::array<std::uint32_t, 4> current{manager, account, password, read32(manager + 0x88)};
        if (sample && current != previous) return nullptr;
        previous = current;
    }
    if (read32(0x00BEDED4) != stage || read32(0x00BEC20C) != previous[0] ||
        read32(previous[0] + 0x88) != previous[3] || read32(window + 0xCC) != previous[1] ||
        read32(window + 0xD4) != previous[2]) return nullptr;
    return previous[3] == previous[1] + 4 ? "account" :
        previous[3] == previous[2] + 4 ? "password" : nullptr;
}

// Expose only emptiness, never edit text or length; reject mutable snapshots.
template <class Read32>
bool LoginEditEmpty(std::uint32_t stage, std::uint32_t window, Read32 read32, bool& accountEmpty, bool& passwordEmpty) {
    const auto focus = LoginEditFocus(stage, window, read32);
    if (!focus) return false;
    const auto account = read32(window + 0xCC), password = read32(window + 0xD4);
    std::array<std::uint32_t, 2> pointers[2]{}, lengths[2]{};
    for (int sample = 0; sample < 2; ++sample) {
        if (read32(window + 0xCC) != account || read32(window + 0xD4) != password) return false;
        for (int i = 0; i < 2; ++i) {
            const auto control = i == 0 ? account : password;
            if (!control || control > UINT32_MAX - 0x37) return false;
            const auto p = read32(control + 0x34);
            pointers[sample][i] = p;
            if (p != 0) {
                if (p < 4) return false;
                const auto length = read32(p - 4);
                if (length == UINT32_MAX) return false;
                lengths[sample][i] = length;
            }
        }
    }
    const auto after = LoginEditFocus(stage, window, read32);
    if (!after || after != focus || read32(window + 0xCC) != account || read32(window + 0xD4) != password ||
        pointers[0] != pointers[1] || lengths[0] != lengths[1]) return false;
    for (int i = 0; i < 2; ++i) {
        const auto control = i == 0 ? account : password;
        const auto pointer = read32(control + 0x34);
        if (pointer != pointers[1][i] || (pointer != 0 && read32(pointer - 4) != lengths[1][i])) return false;
    }
    accountEmpty = lengths[0][0] == 0;
    passwordEmpty = lengths[0][1] == 0;
    return true;
}

// CWndMan relation only; it does not guarantee operating-system focus.
template <class Read32>
bool CreationNameFocus(std::uint32_t stage, std::uint32_t window, Read32 read32, bool& focused) {
    if (!stage || stage > UINT32_MAX - 0x173 || !window || window > UINT32_MAX - 0x87) return false;
    std::array<std::uint32_t, 3> previous{};
    for (int sample = 0; sample < 3; ++sample) {
        if (read32(0x00BEDED4) != stage || read32(stage) != 0x00AF6B24 ||
            read32(stage + 0x168) != 4 || read32(stage + 0x16C) != 0 || read32(stage + 0x170) != 0 ||
            read32(0x00BEDA44) != window || read32(window) != 0x00AF7564 ||
            read32(window + 4) != 0x00AF7518 || read32(window + 8) != 0x00AF7514 ||
            read32(window + 0x24) != 201 || read32(window + 0x28) != 224 || read32(window + 0x6C) != stage)
            return false;
        const auto edit = read32(window + 0x84);
        if (!edit || edit > UINT32_MAX - 0x27 || read32(edit) != 0x00AF2BA8 ||
            read32(edit + 4) != 0x00AF2B5C || read32(edit + 8) != 0x00AF2B58 ||
            read32(edit + 0x14) != 1002 || read32(edit + 0x24) != window) return false;
        const auto manager = read32(0x00BEC20C);
        if (!manager || manager > UINT32_MAX - 0x8B || read32(manager) != 0x00B3F13C ||
            read32(manager + 0x80) != window) return false;
        const std::array<std::uint32_t, 3> current{edit, manager, read32(manager + 0x88)};
        if (sample && current != previous) return false;
        previous = current;
    }
    focused = previous[2] == previous[0] + 4;
    return true;
}

// ASCII only: never inspect any edit other than the verified creation-name control.
template <class Read32, class Read8>
bool CreationNameCandidate(std::uint32_t stage, std::uint32_t window, Read32 read32, Read8 read8, std::string& result) {
    if (!stage || stage > UINT32_MAX - 0x173 || !window || window > UINT32_MAX - 0x87) return false;
    std::uint32_t savedEdit = 0, savedPointer = 0, savedLength = 0;
    std::string saved;
    for (int sample = 0; sample < 2; ++sample) {
        if (read32(0x00BEDED4) != stage || read32(stage) != 0x00AF6B24 ||
            read32(stage + 0x168) != 4 || read32(stage + 0x16C) != 0 || read32(stage + 0x170) != 0 ||
            read32(0x00BEDA44) != window || read32(window) != 0x00AF7564 ||
            read32(window + 4) != 0x00AF7518 || read32(window + 8) != 0x00AF7514 ||
            read32(window + 0x24) != 201 || read32(window + 0x28) != 224 || read32(window + 0x6C) != stage)
            return false;
        const auto edit = read32(window + 0x84);
        if (!edit || edit > UINT32_MAX - 0x37 || read32(edit) != 0x00AF2BA8 ||
            read32(edit + 4) != 0x00AF2B5C || read32(edit + 8) != 0x00AF2B58 ||
            read32(edit + 0x14) != 1002 || read32(edit + 0x24) != window) return false;
        const auto pointer = read32(edit + 0x34);
        if (pointer != 0 && pointer < 4) return false;
        const auto length = pointer == 0 ? 0 : read32(pointer - 4);
        if (length > 255 || (pointer != 0 && pointer > UINT32_MAX - length)) return false;
        std::string text;
        for (std::uint32_t i = 0; i < length; ++i) {
            const auto c = read8(pointer + i);
            if (c < 0x20 || c > 0x7E) return false;
            text.push_back(static_cast<char>(c));
        }
        if (pointer != 0 && read8(pointer + length) != 0) return false;
        if (sample && (edit != savedEdit || pointer != savedPointer || length != savedLength || text != saved)) return false;
        savedEdit = edit; savedPointer = pointer; savedLength = length; saved = text;
    }
    if (read32(0x00BEDED4) != stage || read32(stage) != 0x00AF6B24 || read32(0x00BEDA44) != window ||
        read32(window) != 0x00AF7564 || read32(window + 4) != 0x00AF7518 ||
        read32(window + 8) != 0x00AF7514 || read32(window + 0x24) != 201 ||
        read32(window + 0x28) != 224 || read32(window + 0x6C) != stage ||
        read32(window + 0x84) != savedEdit || read32(savedEdit) != 0x00AF2BA8 ||
        read32(savedEdit + 4) != 0x00AF2B5C || read32(savedEdit + 8) != 0x00AF2B58 ||
        read32(savedEdit + 0x14) != 1002 || read32(savedEdit + 0x24) != window ||
        read32(savedEdit + 0x34) != savedPointer ||
        (savedPointer != 0 && read32(savedPointer - 4) != savedLength) || read32(stage + 0x168) != 4 ||
        read32(stage + 0x16C) != 0 || read32(stage + 0x170) != 0) return false;
    result = saved;
    return true;
}

// World panel values are raw indices, not world identifiers.
template <class Read32>
bool RawWorldSelection(std::uint32_t stage, Read32 read32, std::uint32_t& count, std::uint32_t& index) {
    if (!stage || stage > UINT32_MAX - 0x173) return false;
    std::array<std::uint32_t, 2> counts{}, indices{};
    std::uint32_t panel = 0;
    for (int sample = 0; sample < 2; ++sample) {
        if (read32(0x00BEDED4) != stage || read32(stage) != 0x00AF6B24 ||
            read32(stage + 0x168) != 1 || read32(stage + 0x16C) != 0 || read32(stage + 0x170) != 0)
            return false;
        const auto current = read32(0x00BEDA5C);
        if (current == 0 || current > UINT32_MAX - 0x8B || (sample && current != panel)) return false;
        panel = current;
        if (read32(panel) != 0x00AF7A90 || read32(panel + 4) != 0x00AF7A44 ||
            read32(panel + 8) != 0x00AF7A40 || read32(panel + 0x80) != stage) return false;
        counts[sample] = read32(panel + 0x84);
        indices[sample] = read32(panel + 0x88);
        if (counts[sample] > 30 || (indices[sample] != UINT32_MAX && indices[sample] >= counts[sample])) return false;
    }
    if (counts[0] != counts[1] || indices[0] != indices[1] ||
        read32(0x00BEDED4) != stage || read32(0x00BEDA5C) != panel ||
        read32(stage) != 0x00AF6B24 || read32(stage + 0x168) != 1 ||
        read32(stage + 0x16C) != 0 || read32(stage + 0x170) != 0 ||
        read32(panel) != 0x00AF7A90 || read32(panel + 4) != 0x00AF7A44 ||
        read32(panel + 8) != 0x00AF7A40 || read32(panel + 0x80) != stage) return false;
    count = counts[0];
    index = indices[0];
    return true;
}

// Raw WORD at the selected world-array slot; this is not a verified world ID mapping.
template <class Read32, class Read16>
bool RawWorldId(std::uint32_t stage, Read32 read32, Read16 read16, std::uint16_t& result) {
    if (!stage || stage > UINT32_MAX - 0x18F) return false;
    std::uint32_t pointers[2]{}, lengths[2]{}, counts[2]{}, indices[2]{};
    std::uint16_t values[2]{};
    for (int i = 0; i < 2; ++i) {
        if (!RawWorldSelection(stage, read32, counts[i], indices[i]) || indices[i] == UINT32_MAX) return false;
        pointers[i] = read32(stage + 0x18C);
        if (pointers[i] < 4) return false;
        lengths[i] = read32(pointers[i] - 4);
        if (lengths[i] < counts[i] || indices[i] >= lengths[i]) return false;
        const std::uint64_t address = static_cast<std::uint64_t>(pointers[i]) + 32ull * indices[i];
        if (address > UINT32_MAX - 1) return false;
        values[i] = read16(static_cast<std::uint32_t>(address));
    }
    std::uint32_t count = 0, index = 0;
    if (pointers[0] != pointers[1] || lengths[0] != lengths[1] || counts[0] != counts[1] ||
        indices[0] != indices[1] || values[0] != values[1] || read32(stage + 0x18C) != pointers[1] ||
        read32(pointers[1] - 4) != lengths[1] || !RawWorldSelection(stage, read32, count, index) ||
        count != counts[1] || index != indices[1]) return false;
    result = values[0];
    return true;
}

// Read only the first DWORD of each nonempty native array; no native length
// controls allocation or traversal. The caller isolates memory-read failures.
template <class Read32, class Read8>
bool RawAppearanceSnapshot(std::uint32_t window, std::uint32_t stage, Read32 read32, Read8 read8,
    std::array<std::uint32_t, 8>& values, std::uint8_t& selector, std::uint32_t& job) {
    if (window > UINT32_MAX - 0x6F || stage > UINT32_MAX - 0x288) return false;
    struct Sample {
        std::uint8_t selector;
        std::uint32_t job;
        std::array<std::uint32_t, 8> pointers, lengths, values;
    } samples[2]{};
    for (auto& sample : samples) {
        if (!stage || read32(0x00BEDED4) != stage || read32(stage) != 0x00AF6B24 ||
            read32(window) != 0x00AF777C || read32(window + 4) != 0x00AF7730 ||
            read32(window + 8) != 0x00AF772C || read32(window + 0x24) != 225 ||
            read32(window + 0x28) != 377 || read32(window + 0x6C) != stage ||
            read32(stage + 0x168) != 4 || read32(stage + 0x16C) != 0 ||
            read32(stage + 0x170) != 0) return false;
        sample.job = read32(stage + 0x214);
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
        read32(stage + 0x170) != 0 || read8(stage + 0x234) != samples[1].selector ||
        read32(stage + 0x214) != samples[1].job) return false;
    if (samples[0].job != samples[1].job || samples[0].selector != samples[1].selector || samples[0].pointers != samples[1].pointers ||
        samples[0].lengths != samples[1].lengths || samples[0].values != samples[1].values) return false;
    values = samples[0].values;
    selector = samples[0].selector;
    job = samples[0].job;
    return true;
}

inline bool StableRawGenderSelection(std::uint8_t first, std::uint8_t second, bool sameWindow) {
    return sameWindow && first == second && first <= 1;
}
}
