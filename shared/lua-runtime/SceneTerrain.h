// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Observation.h"

#include <cstdint>
#include <initializer_list>
#include <sstream>

namespace MapleControl {

inline bool ReadTerrainIndex(const std::string& name, std::int64_t& value) {
    std::istringstream input(name);
    if (!(input >> value)) return false;
    input >> std::ws;
    return input.eof();
}

// Node is a read-only IMG view: bool for presence, operator[](const char*),
// name(), and range-for children. readInteger(node, out) must accept only an
// actual integer property, never a missing node's default conversion. This
// keeps the hot headless tree and the GUI's single-IMG view on one contract.
// Scene identity/lifetime belongs to the caller, not to static resource data.
template <class Node, class ReadInteger>
Observation ReadSceneTerrain(const Node& map, std::uint32_t mapId, const std::string& source, ReadInteger readInteger) {
    const auto unavailable = [&](const char* status, const char* error) {
        return Observation{status, Value::Object({{"map_id", mapId}, {"source", source}}), error};
    };
    if (!map) return unavailable("unavailable", "hunt_terrain_unavailable");

    const auto fields = [&](const Node& node, std::initializer_list<const char*> names, Value& output) {
        for (const auto* name : names) {
            std::int64_t value = 0;
            if (!readInteger(node[name], value)) return false;
            output[name] = value;
        }
        return true;
    };
    Value footholds = Value::Array();
    for (const auto& layer : map["foothold"])
        for (const auto& group : layer)
            for (const auto& entry : group) {
                std::int64_t id = 0;
                if (!ReadTerrainIndex(entry.name(), id)) return unavailable("unavailable", "hunt_terrain_invalid");
                auto foothold = Value::Object({{"id", id}});
                if (!fields(entry, {"x1", "x2", "y1", "y2", "prev", "next"}, foothold))
                    return unavailable("unavailable", "hunt_terrain_invalid");
                footholds.Add(std::move(foothold));
            }
    // Match load_hunt_terrain: use this map's own complete geometry when it
    // exists, even if info.link also exists. Never follow link for missing data.
    if (footholds.Elements().empty())
        return map["info"]["link"] ? unavailable("unsupported", "hunt_terrain_unsupported")
                                   : unavailable("unavailable", "hunt_terrain_unavailable");

    Value ropes = Value::Array();
    for (const auto& entry : map["ladderRope"]) {
        std::int64_t index = 0;
        if (!ReadTerrainIndex(entry.name(), index)) return unavailable("unavailable", "hunt_terrain_invalid");
        auto rope = Value::Object({{"index", index}});
        if (!fields(entry, {"x", "y1", "y2"}, rope)) return unavailable("unavailable", "hunt_terrain_invalid");
        for (const auto* name : {"l", "uf"}) {
            std::int64_t value = 0;
            if (readInteger(entry[name], value)) rope[name] = value;
        }
        ropes.Add(std::move(rope));
    }
    return {
        "ok",
        Value::Object(
            {{"map_id", mapId}, {"source", source}, {"footholds", std::move(footholds)}, {"ropes", std::move(ropes)}}),
        {}};
}

}
