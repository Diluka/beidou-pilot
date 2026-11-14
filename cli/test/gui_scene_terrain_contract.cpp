// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeSceneTerrain.h"

#include <cassert>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    assert(argc == 4);
    MapleControl::State state;
    state.ready = std::string(argv[3]) == "ready";
    state.mapKnown = true;
    state.characterKnown = true;
    state.mapId = static_cast<std::uint32_t>(std::stoul(argv[2]));
    const auto result = BeiDouBridge::ObserveSceneTerrain(state, argv[1]);
    std::cout << MapleControl::Value::Object(
                     {{"status", result.status}, {"data", result.data}, {"error", result.error}})
                     .Dump()
              << '\n';
}
