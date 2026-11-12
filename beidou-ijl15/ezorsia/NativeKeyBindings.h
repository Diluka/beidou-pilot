// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <array>
#include <cstdint>
#include <cstring>

namespace BeiDouBridge {

enum class NativeBindingType : unsigned char { Menu = 4, Action = 5 };

// Menu and action IDs overlap. Resolve the requested native type and ID
// together, both when queuing a pulse and immediately before its key-down.
template <class ReadKey>
bool FindNativeBinding(const std::array<unsigned char, 89 * 5>& table, NativeBindingType type, std::uint32_t id,
                       unsigned int& key, const ReadKey& readKey) {
    for (unsigned index = 0; index < 89; ++index) {
        std::uint32_t action = 0;
        std::memcpy(&action, table.data() + index * 5 + 1, sizeof(action));
        if (table[index * 5] != static_cast<unsigned char>(type) || action != id) continue;
        unsigned scan = index;
        if (index == 71 || index == 72 || index == 73 || index == 75 || index == 77 || index == 79 || index == 80
            || index == 81 || index == 82 || index == 83)
            scan |= 0x80;
        unsigned int resolved = 0;
        if (!readKey(scan, resolved) || resolved == 0 || resolved > 255) continue;
        key = resolved;
        return true;
    }
    return false;
}
}
