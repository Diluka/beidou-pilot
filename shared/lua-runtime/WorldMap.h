// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <algorithm>
#include <cstdint>
#include <deque>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace MapleControl {

// Static cross-map portal model. The model is derived from local, read-only
// client IMG portal records; it never contains character state or server
// state. Cache paths include both this logic version and a source fingerprint,
// so a changed parser or changed client resources never overwrite each other.
constexpr int kWorldMapLogicVersion = 1;
constexpr int kWorldMapSchemaVersion = 1;
constexpr std::size_t kWorldRouteMaxLegs = 24;
constexpr std::int64_t kWorldExternalTarget = 999999999;

struct WorldPortal {
    std::string name;
    std::string targetName;
    std::string script;
    std::int64_t x = 0;
    std::int64_t y = 0;
    std::int64_t type = 0;
    std::int64_t target = 0;
};

struct WorldMapEdge {
    std::string name;
    std::string targetName;
    std::string script;
    std::int64_t target = 0;
    std::vector<std::pair<std::int64_t, std::int64_t>> sources;
    std::vector<std::pair<std::int64_t, std::int64_t>> receivers;
};

struct WorldMapModel {
    int logicVersion = kWorldMapLogicVersion;
    std::string sourceFingerprint;
    std::map<std::int64_t, std::vector<WorldPortal>> scenes;
    std::map<std::int64_t, std::vector<WorldMapEdge>> edges;
};

struct WorldRouteLeg {
    std::int64_t from = 0;
    std::string portal;
    std::int64_t to = 0;
    std::vector<std::pair<std::int64_t, std::int64_t>> portalAt;
};

struct WorldRoute {
    // ok | no_route | map_unknown | route_too_long
    std::string status;
    std::string error;
    std::int64_t start = 0;
    std::int64_t goal = 0;
    std::vector<WorldRouteLeg> legs;
};

struct WorldMapFile {
    std::string path; // Relative path, independent from the mount root.
    std::uint64_t size = 0;
    std::int64_t mtime = 0;
};

inline bool WorldPortalIsCrossMap(const WorldPortal& portal) {
    return (portal.type == 1 || portal.type == 2 || portal.type == 3 || portal.type == 6 || portal.type == 10)
           && portal.target != 0 && portal.target != kWorldExternalTarget && portal.script.empty();
}

// A map node exposes bool for presence, operator[](const char*), name() and
// range-for children. readInteger/readString must accept only an actual value
// node of the right type. Missing portal fields keep their empty/default value;
// malformed required numeric fields reject the map instead of guessing.
template <class Node, class ReadInteger, class ReadString>
bool ReadWorldPortals(const Node& map, std::vector<WorldPortal>& portals, std::string& error, ReadInteger readInteger,
                      ReadString readString) {
    if (!map) {
        error = "world_map_node_unavailable";
        return false;
    }
    const auto integer = [&](const Node& node, std::int64_t& value) { return readInteger(node, value); };
    const auto string = [&](const Node& node, std::string& value) { return readString(node, value); };
    for (const auto& entry : map["portal"]) {
        WorldPortal portal;
        if (!integer(entry["x"], portal.x) || !integer(entry["y"], portal.y) || !integer(entry["pt"], portal.type)) {
            error = "world_map_portal_invalid";
            return false;
        }
        if (!integer(entry["tm"], portal.target)) portal.target = 0;
        string(entry["pn"], portal.name);
        string(entry["tn"], portal.targetName);
        string(entry["script"], portal.script);
        portals.push_back(std::move(portal));
    }
    return true;
}

inline void BuildWorldMapEdges(WorldMapModel& model) {
    model.edges.clear();
    for (const auto& scene : model.scenes) {
        std::map<std::tuple<std::int64_t, std::string, std::string, std::string>, WorldMapEdge> grouped;
        for (const auto& portal : scene.second) {
            if (!WorldPortalIsCrossMap(portal)) continue;
            const auto key = std::make_tuple(portal.target, portal.name, portal.targetName, portal.script);
            auto& edge = grouped[key];
            edge.target = portal.target;
            edge.name = portal.name;
            edge.targetName = portal.targetName;
            edge.script = portal.script;
            edge.sources.emplace_back(portal.x, portal.y);
        }
        auto& edges = model.edges[scene.first];
        for (auto& entry : grouped) {
            auto& edge = entry.second;
            const auto target = model.scenes.find(edge.target);
            if (target != model.scenes.end() && !edge.targetName.empty()) {
                const auto named =
                    std::count_if(target->second.begin(), target->second.end(),
                                  [&](const WorldPortal& portal) { return portal.name == edge.targetName; });
                if (named > 0) {
                    for (const auto& portal : target->second)
                        if (portal.name == edge.targetName) {
                            edge.receivers.emplace_back(portal.x, portal.y);
                            break;
                        }
                }
            }
            edges.push_back(std::move(edge));
        }
    }
}

inline WorldRoute FindWorldRoute(const WorldMapModel& model, std::int64_t start, std::int64_t goal,
                                 std::size_t maxLegs = kWorldRouteMaxLegs) {
    WorldRoute route;
    route.start = start;
    route.goal = goal;
    if (model.scenes.find(start) == model.scenes.end()) {
        route.status = "map_unknown";
        route.error = "source_map_unknown";
        return route;
    }
    if (model.scenes.find(goal) == model.scenes.end()) {
        route.status = "map_unknown";
        route.error = "target_map_unknown";
        return route;
    }
    if (start == goal) {
        route.status = "ok";
        return route;
    }
    // Directed BFS over resource portals; no reverse edge is inferred.
    std::map<std::int64_t, std::pair<std::int64_t, WorldMapEdge>> previous;
    std::set<std::int64_t> visited{start};
    std::deque<std::int64_t> queue{start};
    while (!queue.empty()) {
        const auto current = queue.front();
        queue.pop_front();
        const auto edges = model.edges.find(current);
        if (edges == model.edges.end()) continue;
        for (const auto& edge : edges->second) {
            if (!edge.script.empty() || model.scenes.find(edge.target) == model.scenes.end()
                || visited.count(edge.target) != 0)
                continue;
            visited.insert(edge.target);
            previous.emplace(edge.target, std::make_pair(current, edge));
            if (edge.target == goal) {
                queue.clear();
                break;
            }
            queue.push_back(edge.target);
        }
    }
    const auto found = previous.find(goal);
    if (found == previous.end()) {
        route.status = "no_route";
        route.error = "no_route";
        return route;
    }
    for (auto node = goal; node != start;) {
        const auto& step = previous.at(node);
        route.legs.push_back({step.first, step.second.name, node, step.second.sources});
        node = step.first;
    }
    std::reverse(route.legs.begin(), route.legs.end());
    if (route.legs.size() > maxLegs) {
        route.legs.clear();
        route.status = "route_too_long";
        route.error = "route_too_long";
        return route;
    }
    route.status = "ok";
    return route;
}

inline std::string EscapeWorldMapField(const std::string& value) {
    if (value.empty()) return "~";
    std::string escaped;
    escaped.reserve(value.size());
    const auto hex = "0123456789ABCDEF";
    for (const unsigned char byte : value) {
        const bool safe = (byte >= 'A' && byte <= 'Z') || (byte >= 'a' && byte <= 'z') || (byte >= '0' && byte <= '9')
                          || byte == '_' || byte == '.' || byte == '-';
        if (safe) {
            escaped.push_back(static_cast<char>(byte));
        } else {
            escaped.push_back('%');
            escaped.push_back(hex[byte >> 4]);
            escaped.push_back(hex[byte & 0x0F]);
        }
    }
    return escaped;
}

inline bool UnescapeWorldMapField(const std::string& value, std::string& result) {
    result.clear();
    if (value == "~") return true;
    const auto hex = [](char digit) -> int {
        if (digit >= '0' && digit <= '9') return digit - '0';
        if (digit >= 'A' && digit <= 'F') return digit - 'A' + 10;
        if (digit >= 'a' && digit <= 'f') return digit - 'a' + 10;
        return -1;
    };
    for (std::size_t index = 0; index < value.size(); ++index) {
        if (value[index] != '%') {
            result.push_back(value[index]);
            continue;
        }
        if (index + 2 >= value.size()) return false;
        const auto high = hex(value[index + 1]);
        const auto low = hex(value[index + 2]);
        if (high < 0 || low < 0) return false;
        result.push_back(static_cast<char>((high << 4) | low));
        index += 2;
    }
    return true;
}

inline std::string SerializeWorldMap(const WorldMapModel& model) {
    std::ostringstream output;
    output << "beidou-world-map " << kWorldMapSchemaVersion << '\n';
    output << "logic " << model.logicVersion << '\n';
    output << "fingerprint " << EscapeWorldMapField(model.sourceFingerprint) << '\n';
    output << "maps " << model.scenes.size() << '\n';
    for (const auto& scene : model.scenes) {
        output << "map " << scene.first << ' ' << scene.second.size() << '\n';
        for (const auto& portal : scene.second) {
            output << "portal " << EscapeWorldMapField(portal.name) << ' ' << portal.x << ' ' << portal.y << ' '
                   << portal.type << ' ' << portal.target << ' ' << EscapeWorldMapField(portal.targetName) << ' '
                   << EscapeWorldMapField(portal.script) << '\n';
        }
    }
    return output.str();
}

inline bool ParseWorldMap(const std::string& text, WorldMapModel& model, std::string& error) {
    std::istringstream input(text);
    std::string line;
    if (!std::getline(input, line)) {
        error = "world_map_cache_truncated";
        return false;
    }
    {
        std::istringstream header(line);
        std::string magic;
        int schema = 0;
        std::string extra;
        if (!(header >> magic >> schema) || (header >> extra) || magic != "beidou-world-map"
            || schema != kWorldMapSchemaVersion) {
            error = "world_map_cache_schema";
            return false;
        }
    }
    const auto read_pair = [&](const char* prefix, std::string& value) {
        std::istringstream field(line);
        std::string name;
        std::string extra;
        if (!(field >> name >> value) || (field >> extra) || name != prefix) return false;
        return true;
    };
    std::string logicValue;
    if (!std::getline(input, line) || !read_pair("logic", logicValue)) {
        error = "world_map_cache_logic_version";
        return false;
    }
    {
        std::istringstream logic(logicValue);
        int logicVersion = 0;
        std::string extra;
        if (!(logic >> logicVersion) || (logic >> extra) || logicVersion != kWorldMapLogicVersion) {
            error = "world_map_cache_logic_version";
            return false;
        }
    }
    std::string escaped;
    if (!std::getline(input, line) || !read_pair("fingerprint", escaped)) {
        error = "world_map_cache_fingerprint";
        return false;
    }
    WorldMapModel parsed;
    parsed.logicVersion = kWorldMapLogicVersion;
    if (!UnescapeWorldMapField(escaped, parsed.sourceFingerprint)) {
        error = "world_map_cache_fingerprint";
        return false;
    }
    std::size_t maps = 0;
    if (!std::getline(input, line) || !read_pair("maps", escaped)) {
        error = "world_map_cache_maps";
        return false;
    }
    {
        std::istringstream count(escaped);
        std::string extra;
        if (!(count >> maps) || (count >> extra)) {
            error = "world_map_cache_maps";
            return false;
        }
    }
    for (std::size_t index = 0; index < maps; ++index) {
        if (!std::getline(input, line)) {
            error = "world_map_cache_truncated";
            return false;
        }
        std::int64_t mapId = 0;
        std::size_t portals = 0;
        {
            std::istringstream header(line);
            std::string token;
            std::string extra;
            if (!(header >> token >> mapId >> portals) || (header >> extra) || token != "map") {
                error = "world_map_cache_map";
                return false;
            }
        }
        std::vector<WorldPortal> entries;
        entries.reserve(portals);
        for (std::size_t portalIndex = 0; portalIndex < portals; ++portalIndex) {
            if (!std::getline(input, line)) {
                error = "world_map_cache_truncated";
                return false;
            }
            std::istringstream fields(line);
            std::string token;
            WorldPortal portal;
            std::string name, targetName, script, extra;
            if (!(fields >> token >> name >> portal.x >> portal.y >> portal.type >> portal.target >> targetName
                  >> script)
                || (fields >> extra) || token != "portal" || !UnescapeWorldMapField(name, portal.name)
                || !UnescapeWorldMapField(targetName, portal.targetName)
                || !UnescapeWorldMapField(script, portal.script)) {
                error = "world_map_cache_portal";
                return false;
            }
            entries.push_back(std::move(portal));
        }
        parsed.scenes.emplace(mapId, std::move(entries));
    }
    if (std::getline(input, line) && !line.empty()) {
        error = "world_map_cache_trailing";
        return false;
    }
    BuildWorldMapEdges(parsed);
    model = std::move(parsed);
    return true;
}

inline std::string FingerprintWorldMapFiles(std::vector<WorldMapFile> files) {
    std::sort(files.begin(), files.end(), [](const WorldMapFile& a, const WorldMapFile& b) { return a.path < b.path; });
    std::uint64_t hash = 1469598103934665603ULL;
    const auto mix = [&](const std::string& value) {
        for (const unsigned char byte : value) {
            hash ^= byte;
            hash *= 1099511628211ULL;
        }
        hash ^= 0xFFULL;
        hash *= 1099511628211ULL;
    };
    for (const auto& file : files) {
        mix(file.path);
        mix(std::to_string(file.size));
        mix(std::to_string(file.mtime));
    }
    const auto hex = "0123456789abcdef";
    std::string result(16, '0');
    for (int index = 15; index >= 0; --index) {
        result[static_cast<std::size_t>(index)] = hex[hash & 0x0F];
        hash >>= 4;
    }
    return result;
}

inline std::string WorldMapCacheRelativePath(const std::string& fingerprint) {
    return "world-map/" + std::to_string(kWorldMapLogicVersion) + "/" + fingerprint + ".wmap";
}

} // namespace MapleControl
