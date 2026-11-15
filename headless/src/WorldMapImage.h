// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "WorldMap.h"

#include <filesystem>
#include <string>

namespace MapleControl {

// Persisted world-map cache root from the client environment. Empty means the
// caller runs without a shared file cache (model is still built in memory).
std::string WorldMapCacheRootFromEnvironment();

// Loads the versioned cache for this data root, or derives it from the local
// IMG portal records and publishes it. cacheState is hit, built or memory.
// The source data is only read; nothing outside the cache root is written.
bool LoadOrBuildWorldMap(const std::filesystem::path& dataRoot, std::string cacheRoot, WorldMapModel& model,
                         std::string& cacheState, std::string& error);

} // namespace MapleControl
