// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"

#include <deque>
#include <string>

namespace MapleControl {

// Independent readers retain their own cursors; publishing never consumes an event.
class EventTransport {
public:
    EventTransport(std::string bridgeDirectory, std::string registeredRun);

    std::uint64_t Emit(const State& state, const std::string& type, const std::string& source, const Value& data,
                       std::uint64_t expiresAtMs = 0);
    bool Flush(const State& state);

private:
    std::string directory;
    std::string runId;
    std::deque<Value> events;
    std::uint64_t sequence = 0;
    bool dirty = true;
};

}
