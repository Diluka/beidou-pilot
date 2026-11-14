// SPDX-License-Identifier: AGPL-3.0-or-later
#include "ImgResources.h"
#include "SceneTerrain.h"

#include <array>
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>

#ifdef TERRAIN_HOT_TREE
#include "ImgResourceFile.h"
#include <nlnx/node.hpp>
#endif

namespace {
// Exercise the real C ABI as a read-only node view. No geometry or fallback
// behavior lives here: both native representations use ReadSceneTerrain.
class ImgNode {
public:
    ImgNode() = default;

    ImgNode(const BeidouImgDirectory* directory, std::size_t index) : directory(directory), index(index) {}

    explicit operator bool() const { return directory != nullptr && index != Missing; }

    BeidouImgNodeInfo Info() const {
        BeidouImgNodeInfo info{};
        if (*this) assert(beidou_img_directory_node(directory, index, &info) != 0);
        return info;
    }

    std::string name() const {
        if (!*this) return {};
        std::size_t length = 0;
        const auto* text = beidou_img_directory_string(directory, Info().name_string_id, &length);
        assert(text != nullptr);
        return {text, length};
    }

    ImgNode operator[](const char* key) const {
        for (const auto& child : *this)
            if (child.name() == key) return child;
        return {};
    }

    ImgNode begin() const { return {directory, Info().children}; }

    ImgNode end() const {
        const auto info = Info();
        return {directory, info.children + info.child_count};
    }

    ImgNode operator*() const { return *this; }

    ImgNode& operator++() {
        ++index;
        return *this;
    }

    bool operator!=(const ImgNode& other) const { return directory != other.directory || index != other.index; }

private:
    static constexpr std::size_t Missing = std::numeric_limits<std::size_t>::max();
    const BeidouImgDirectory* directory = nullptr;
    std::size_t index = Missing;
};
}

int main(int argc, char** argv) {
    assert(argc == 4);
    const std::string directory = argv[1];
    const std::string filename = argv[2];
    const auto mapId = static_cast<std::uint32_t>(std::stoul(argv[3]));
    const auto source = directory + "/" + filename;
    MapleControl::Observation terrain;
#ifdef TERRAIN_HOT_TREE
    // This is the real headless IMG -> nl::file -> nl::node path. The query
    // consumes a tree that has already been parsed, not a second decoder.
    const auto file = load_img_directory(directory);
    terrain = MapleControl::ReadSceneTerrain(file.root()[filename], mapId, source,
                                             [](const nl::node& node, std::int64_t& value) {
                                                 if (!node || node.data_type() != nl::node::type::integer) return false;
                                                 value = node.get_integer();
                                                 return true;
                                             });
#else
    std::array<char, 1024> error{};
    BeidouImgDirectory* parsed = nullptr;
    assert(beidou_img_file_open(source.c_str(), &parsed, error.data(), error.size()) != 0);
    terrain =
        MapleControl::ReadSceneTerrain(ImgNode(parsed, 0), mapId, source, [](const ImgNode& node, std::int64_t& value) {
            if (!node) return false;
            const auto info = node.Info();
            if (info.type != BEIDOU_IMG_NODE_INTEGER) return false;
            value = info.integer;
            return true;
        });
    beidou_img_directory_close(parsed);
#endif
    std::cout << MapleControl::Value::Object(
                     {{"status", terrain.status},
                      {"data", terrain.data},
                      {"error", terrain.error.empty() ? MapleControl::Value{} : MapleControl::Value(terrain.error)}})
                     .Dump()
              << '\n';
}
