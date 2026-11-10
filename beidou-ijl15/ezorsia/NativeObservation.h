// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Observation.h"

#include <cstdint>
#include <cstddef>
#include <stdexcept>
#include <string>
#include <vector>

namespace MapleControl {
class EventTransport;
struct State;
}

namespace NativeObservation {

using MapleControl::Value;

class ReadError : public std::runtime_error {
public:
    explicit ReadError(const std::string& message) : std::runtime_error(message) {}
};

void Copy(std::uintptr_t address, void* output, std::size_t size);

template <class T> T Read(std::uintptr_t address) {
    T value{};
    Copy(address, &value, sizeof(value));
    return value;
}

std::vector<unsigned char> Bytes(std::uintptr_t address, std::size_t size);
std::string Utf8(const std::string& cp936);
std::string ZxString(std::uintptr_t field, std::size_t maximum = 65536);
std::uint32_t SecureInt(std::uintptr_t address);
std::uint32_t SecureValue(std::uintptr_t address);

Value Stage();
Value Scene();
Value Inventory();
Value Character();
Value Quests();
Value Hotkeys();
Value Dialog();
Value Window(std::uintptr_t address);
Value Ui();
Value Shop();
Value Invitations();
Value Party();
void PollInvitations(MapleControl::EventTransport& events, const MapleControl::State& state);
MapleControl::Observation Collect(const std::string& domain);

// Separate read-only request lane; it never replaces a running action/script request.
void Tick(const std::string& directory, const std::string& instance, const std::string& run, std::uint64_t generation,
          std::uint64_t sequence);
}
