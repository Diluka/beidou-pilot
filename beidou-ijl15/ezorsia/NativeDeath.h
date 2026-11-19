#pragma once

#include "Contract.h"

namespace BeiDouBridge {
// Only a complete current scene and checksum-validated character can establish HP.
inline MapleControl::Fact DeathFromState(const MapleControl::State& state) {
    if (!state.ready) return MapleControl::Fact::Unknown;
    return state.character.values[6] == 0 ? MapleControl::Fact::True : MapleControl::Fact::False;
}
}
