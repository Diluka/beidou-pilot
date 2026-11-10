// SPDX-License-Identifier: AGPL-3.0-or-later
#include "EventTransport.h"

#include <cstdio>
#include <fstream>
#include <utility>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace MapleControl {

EventTransport::EventTransport(std::string bridgeDirectory, std::string registeredRun)
    : directory(std::move(bridgeDirectory)), runId(std::move(registeredRun)) {}

std::uint64_t EventTransport::Emit(const State& state, const std::string& type, const std::string& source,
                                   const Value& data, std::uint64_t expiresAtMs) {
    events.push_back(Value::Object({{"seq", ++sequence},
                                    {"observed_at_ms", state.observedAtMs},
                                    {"scene_generation", state.sceneGeneration},
                                    {"character_id", state.characterKnown ? Value(state.character.id) : Value{}},
                                    {"type", type},
                                    {"source", source},
                                    {"expires_at_ms", expiresAtMs ? Value(expiresAtMs) : Value{}},
                                    {"data", data}}));
    if (events.size() > 128) events.pop_front();
    dirty = true;
    return sequence;
}

bool EventTransport::Flush(const State& state) {
    if (!dirty) return true;
    auto retained = Value::Array();
    for (const auto& event : events) retained.Add(event);
    const auto document = Value::Object({{"protocol", 1},
                                         {"instance_id", state.instanceId},
                                         {"run_id", runId},
                                         {"first_seq", sequence - events.size() + 1},
                                         {"last_seq", sequence},
                                         {"events", retained}});
    const auto temporary = directory + "/events.tmp";
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output) return false;
    output << document.Dump() << '\n';
    output.close();
    if (!output) return false;
#ifdef _WIN32
    const bool saved = MoveFileExA(temporary.c_str(), (directory + "/events.json").c_str(),
                                   MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)
                       != FALSE;
#else
    const bool saved = std::rename(temporary.c_str(), (directory + "/events.json").c_str()) == 0;
#endif
    if (saved) dirty = false;
    return saved;
}

}
