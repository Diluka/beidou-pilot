// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <cstdint>

namespace BeiDouBridge {
// Experimental one-shot cancellation decision state. The caller owns object lifetime
// and must bind this to the same thread and live native call stack.
struct NativeAutoApCancelProbe {
    bool active = false;
    bool attempted = false;
    std::uintptr_t modal = 0;
    std::uint32_t character = 0;
    std::uint64_t scene = 0;
    std::uint32_t context = 0;

    bool Bind(std::uintptr_t object, std::uintptr_t caller) {
        if (!active || modal || !object || caller != 0x00992EB1) return false;
        modal = object;
        return true;
    }

    bool TakeCancel(std::uintptr_t object, std::uintptr_t focused, std::uint32_t table, std::uint32_t type,
                    std::uint32_t handler, std::uint32_t liveCharacter, std::uint64_t liveScene,
                    std::uint32_t liveContext, bool buttonEnabled) {
        if (!active || attempted || !modal || modal != object || focused != object || table != 0x00B3BB24
            || type != 1001 || handler != 0x008D5251 || character == 0 || context == 0 || character != liveCharacter
            || scene != liveScene || context != liveContext || !buttonEnabled)
            return false;
        attempted = true;
        return true;
    }
};
}
