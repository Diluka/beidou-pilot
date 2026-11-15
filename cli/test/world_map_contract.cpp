// SPDX-License-Identifier: AGPL-3.0-or-later
#include "WorldMap.h"
#include "WorldMapImage.h"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {
using namespace MapleControl;

void Check(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

WorldMapModel Model() {
    WorldMapModel model;
    model.logicVersion = kWorldMapLogicVersion;
    model.sourceFingerprint = "0011223344556677";
    model.scenes[100] = {{"in00", "out00", "", -5, 7, 2, 200}, {"sp", "", "", 0, 0, 0, 0}};
    model.scenes[200] = {{"out00", "in00", "", 9, 11, 2, 100},
                         {"in00", "out00", "", 4, 5, 2, 300},
                         {"scripted", "out00", "script", 1, 2, 2, 100}};
    model.scenes[300] = {{"out00", "in00", "", 3, 4, 2, 200}};
    model.scenes[400] = {};
    BuildWorldMapEdges(model);
    return model;
}

void ModelContract() {
    const auto model = Model();
    // type 0 and scripted portals never become edges.
    Check(model.edges.at(100).size() == 1, "only the cross-map portal becomes an edge");
    Check(model.edges.at(200).size() == 2, "two directed cross-map edges");
    Check(model.edges.at(200)[0].sources.size() == 1 || model.edges.at(200)[1].sources.size() == 1,
          "script portal is excluded from edges");
    const auto route = FindWorldRoute(model, 100, 300);
    Check(route.status == "ok" && route.legs.size() == 2, "directed route");
    Check(route.legs[0].from == 100 && route.legs[0].to == 200 && route.legs[0].portal == "in00", "first leg");
    Check(route.legs[0].portalAt.size() == 1 && route.legs[0].portalAt[0].first == -5, "first leg portal point");
    Check(FindWorldRoute(model, 100, 400).status == "no_route", "unknown reachability is no_route");
    Check(FindWorldRoute(model, 100, 400).error == "no_route", "no_route error");
    Check(FindWorldRoute(model, 9, 100).status == "map_unknown", "unknown start");
    Check(FindWorldRoute(model, 9, 100).error == "source_map_unknown", "unknown start error");
    Check(FindWorldRoute(model, 100, 9).status == "map_unknown", "unknown goal");
    Check(FindWorldRoute(model, 100, 9).error == "target_map_unknown", "unknown goal error");
    Check(FindWorldRoute(model, 100, 100).status == "ok" && FindWorldRoute(model, 100, 100).legs.empty(),
          "same map has an empty ok route");
    Check(FindWorldRoute(model, 100, 300, 1).status == "route_too_long", "leg limit");

    const auto text = SerializeWorldMap(model);
    WorldMapModel parsed;
    std::string error;
    Check(ParseWorldMap(text, parsed, error), error.c_str());
    Check(parsed.sourceFingerprint == model.sourceFingerprint, "fingerprint roundtrip");
    Check(parsed.scenes.size() == model.scenes.size(), "map count roundtrip");
    Check(parsed.edges.at(200).size() == 2, "edges rebuilt after parse");
    const auto parsedRoute = FindWorldRoute(parsed, 100, 300);
    Check(parsedRoute.status == "ok" && parsedRoute.legs.size() == 2, "route after parse");

    WorldMapModel escaped;
    escaped.scenes[1] = {{"名 字%带空格", "目标 名", "脚本 路径", 0, 1, 2, 2}};
    escaped.scenes[2] = {{"目标 名", "名 字%带空格", "", 0, 0, 2, 1}};
    BuildWorldMapEdges(escaped);
    WorldMapModel escapedParsed;
    Check(ParseWorldMap(SerializeWorldMap(escaped), escapedParsed, error), "escaped fields parse");
    Check(escapedParsed.scenes.at(1)[0].name == "名 字%带空格", "escaped portal name");
    Check(escapedParsed.scenes.at(1)[0].script == "脚本 路径", "escaped script");

    std::vector<WorldMapFile> files{{"Map/Map/Map1/a.img", 10, 100}, {"Map/Map/Map1/b.img", 20, 200}};
    const auto first = FingerprintWorldMapFiles(files);
    files[1].sampleHash = 201;
    Check(first != FingerprintWorldMapFiles(files), "fingerprint changes with source content sample");
    Check(WorldMapCacheRelativePath(first) == "world-map/2/" + first + ".wmap", "versioned cache path");

    std::cout << "{\"model\":\"ok\",\"legs\":" << route.legs.size() << ",\"roundtrip\":true}\n";
}

void CacheContract(const std::string& data, const std::string& cache) {
    WorldMapModel model;
    std::string cacheState;
    std::string error;
    Check(LoadOrBuildWorldMap(data, cache, model, cacheState, error), error.c_str());
    const auto route = FindWorldRoute(model, 101000000, 103000000);
    std::cout << "{\"cache\":\"" << cacheState << "\",\"maps\":" << model.scenes.size() << ",\"edges\":" <<
        [&] {
            std::size_t edges = 0;
            for (const auto& scene : model.edges) edges += scene.second.size();
            return edges;
        }() << ",\"fingerprint\":\""
              << model.sourceFingerprint << "\",\"route\":\"" << route.status << "\",\"legs\":" << route.legs.size()
              << "}\n";
}

} // namespace

int main(int argc, char** argv) {
    if (argc >= 2 && std::string(argv[1]) == "model") {
        ModelContract();
        return 0;
    }
    if (argc == 4 && std::string(argv[1]) == "cache") return CacheContract(argv[2], argv[3]), 0;
    std::cerr << "usage: world_map_contract model | cache DATA CACHE\n";
    return 2;
}
