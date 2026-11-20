// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <array>
#include <cstdint>

namespace BeiDouBridge { namespace NativeSkillUp {
// V17 executable SHA-256 must be verified by the caller in addition to these
// in-memory fingerprints. All methods must run on the game thread.
template<class Reader> struct NativeCalls {
    Reader read;
    bool Fingerprints() const {
        const std::array<unsigned char, 16> lookup{{0xb8,0x7c,0x3d,0xab,0x00,0xe8,0x39,0x44,0x30,0x00,0x51,0x51,0x8b,0x45,0x08,0x56}};
        const std::array<unsigned char, 16> check{{0x55,0x8b,0xec,0x83,0xec,0x0c,0x53,0x56,0x57,0x8d,0x45,0xf4,0x50,0xe8,0xf4,0xce}};
        const std::array<unsigned char, 16> send{{0xb8,0x4c,0xc7,0xae,0x00,0xe8,0x9b,0xce,0x03,0x00,0x83,0xec,0x10,0x56,0x6a,0x00}};
        const std::array<unsigned char, 16> gate{{0x56,0x8b,0xf1,0x83,0xbe,0xa4,0x20,0x00,0x00,0x00,0x75,0x36,0x83,0x7c,0x24,0x0c}};
        std::array<unsigned char, 16> actual{};
        return read(0x0075c755, actual) && actual == lookup
            && read(0x00a08e05, actual) && actual == check
            && read(0x00a23cf3, actual) && actual == send
            && read(0x00485bf7, actual) && actual == gate;
    }
    std::uint32_t Lookup(std::uint32_t manager, std::uint32_t id) const {
        using Fn = std::uint32_t(__thiscall*)(void*, std::uint32_t);
        return reinterpret_cast<Fn>(0x0075c755)(reinterpret_cast<void*>(manager), id);
    }
    bool CanRaise(std::uint32_t context, std::uint32_t skill) const {
        using Fn = int(__thiscall*)(void*, void*);
        return reinterpret_cast<Fn>(0x00a08e05)(reinterpret_cast<void*>(context), reinterpret_cast<void*>(skill)) == 1;
    }
    // This is the same preflight the event repeats; it never sends a packet.
    bool Gate(std::uint32_t context) const {
        using Fn = int(__thiscall*)(void*, int, int);
        return reinterpret_cast<Fn>(0x00485bf7)(reinterpret_cast<void*>(context), 500, 0) == 1;
    }
    void Request(std::uint32_t context, std::uint32_t id) const {
        using Fn = void(__thiscall*)(void*, std::uint32_t);
        reinterpret_cast<Fn>(0x00a23cf3)(reinterpret_cast<void*>(context), id);
    }
};
} }
