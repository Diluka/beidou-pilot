// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeSceneTerrain.h"
#include "SceneTerrain.h"
#include "../../headless/src/ImgResources.h"

#include <array>
#include <filesystem>
#include <iomanip>
#include <memory>
#include <sstream>

namespace {
// A typed, read-only view over the existing IMG C ABI. The directory owns all
// nodes and strings for the duration of a single map extraction.
class ImgNode {
public:
    ImgNode() = default;

    ImgNode(const BeidouImgDirectory* directory, std::size_t index) : owner(directory) {
        present = beidou_img_directory_node(owner, index, &info) != 0;
    }

    explicit operator bool() const { return present; }

    std::string name() const {
        if (!present) return {};
        std::size_t length = 0;
        const auto* text = beidou_img_directory_string(owner, info.name_string_id, &length);
        return text ? std::string(text, length) : std::string{};
    }

    ImgNode operator[](const char* key) const {
        for (const auto& child : *this)
            if (child.name() == key) return child;
        return {};
    }

    bool Integer(std::int64_t& value) const {
        if (!present || info.type != BEIDOU_IMG_NODE_INTEGER) return false;
        value = info.integer;
        return true;
    }

    struct Iterator {
        const BeidouImgDirectory* owner;
        std::size_t index;

        ImgNode operator*() const { return {owner, index}; }

        Iterator& operator++() {
            ++index;
            return *this;
        }

        bool operator!=(const Iterator& other) const { return index != other.index; }
    };

    Iterator begin() const { return {owner, info.children}; }

    Iterator end() const { return {owner, info.children + info.child_count}; }

private:
    const BeidouImgDirectory* owner = nullptr;
    BeidouImgNodeInfo info{};
    bool present = false;
};
}

MapleControl::Observation BeiDouBridge::ObserveSceneTerrain(const MapleControl::State& state,
                                                            const std::string& dataRoot) {
    using MapleControl::Observation;
    using MapleControl::Value;
    std::string source;
    const auto unavailable = [&](const char* reason, const std::string& message = {}) {
        auto data = Value::Object({{"map_id", state.mapId}, {"source", source}});
        if (!message.empty()) data["message"] = message;
        return Observation{"unavailable", std::move(data), reason};
    };
    if (!state.ready || !state.mapKnown || !state.characterKnown) return unavailable("strategy_scene_unavailable");
    if (dataRoot.empty()) return unavailable("terrain_data_root_unavailable");

    const auto root = std::filesystem::u8path(dataRoot);
    std::error_code error;
    const auto maps = std::filesystem::is_directory(root / "Map002", error) ? root / "Map002" : root / "Map";
    if (error && error != std::errc::no_such_file_or_directory)
        return unavailable("terrain_data_root_unavailable", error.message());
    std::ostringstream name;
    name << std::setfill('0') << std::setw(9) << state.mapId << ".img";
    const auto imagePath = maps / "Map" / ("Map" + std::to_string(state.mapId / 100000000)) / name.str();
    source = imagePath.generic_u8string();
    std::array<char, 4096> message{};
    BeidouImgDirectory* opened = nullptr;
    if (!beidou_img_file_open(imagePath.u8string().c_str(), &opened, message.data(), message.size()))
        return unavailable("hunt_terrain_unavailable", message.data());
    const std::unique_ptr<BeidouImgDirectory, decltype(&beidou_img_directory_close)> image(opened,
                                                                                           beidou_img_directory_close);
    return MapleControl::ReadSceneTerrain(ImgNode(image.get(), 0), state.mapId, source,
                                          [](const ImgNode& node, std::int64_t& value) { return node.Integer(value); });
}
