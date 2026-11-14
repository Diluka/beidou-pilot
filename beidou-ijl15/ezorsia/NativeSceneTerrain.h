// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Runtime.h"

namespace BeiDouBridge {
// dataRoot is the explicitly mounted local IMG catalog, not the client cwd.
MapleControl::Observation ObserveSceneTerrain(const MapleControl::State& state, const std::string& dataRoot);
}
