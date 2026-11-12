// SPDX-License-Identifier: AGPL-3.0-or-later
#include "ImgResourceFile.h"

#include "ImgResources.h"
#include <nlnx/node_impl.hpp>

#include <array>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
nl::node::data make_node(BeidouImgNodeInfo const& source) {
    const auto name = source.name_string_id;
    const auto children = source.children;
    const auto count = source.child_count;
    switch (source.type) {
    case BEIDOU_IMG_NODE_INTEGER:
        return {.name = name, .children = children, .num = count,
                .type = nl::node::type::integer, .ireal = source.integer};
    case BEIDOU_IMG_NODE_REAL:
        return {.name = name, .children = children, .num = count,
                .type = nl::node::type::real, .dreal = source.real};
    case BEIDOU_IMG_NODE_STRING:
        return {.name = name, .children = children, .num = count,
                .type = nl::node::type::string, .string = source.value_string_id};
    case BEIDOU_IMG_NODE_VECTOR:
        return {.name = name, .children = children, .num = count,
                .type = nl::node::type::vector, .vector = {source.vector_x, source.vector_y}};
    case BEIDOU_IMG_NODE_BITMAP:
        return {.name = name, .children = children, .num = count,
                .type = nl::node::type::bitmap,
                .bitmap = {source.bitmap_id, source.bitmap_width, source.bitmap_height}};
    case BEIDOU_IMG_NODE_AUDIO:
        return {.name = name, .children = children, .num = count,
                .type = nl::node::type::audio, .audio = {source.audio_id, source.audio_length}};
    default:
        return {.name = name, .children = children, .num = count,
                .type = nl::node::type::none, .ireal = 0};
    }
}
}

nl::file load_img_directory(std::filesystem::path const& path, bool base_only) {
    std::array<char, 1024> error{};
    BeidouImgDirectory* parsed = nullptr;
    if (!beidou_img_directory_open(path.string().c_str(), base_only, &parsed,
                                   error.data(), error.size()))
        throw std::runtime_error(error.data());

    std::shared_ptr<void> owner(parsed, [](void* directory) {
        beidou_img_directory_close(static_cast<BeidouImgDirectory*>(directory));
    });
    const auto node_count = beidou_img_directory_node_count(parsed);
    std::vector<nl::node::data> nodes;
    nodes.reserve(node_count);
    for (size_t index = 0; index < node_count; ++index) {
        BeidouImgNodeInfo info{};
        if (!beidou_img_directory_node(parsed, index, &info))
            throw std::runtime_error("IMG parser returned an invalid node index");
        nodes.push_back(make_node(info));
    }

    const auto string_count = beidou_img_directory_string_count(parsed);
    std::vector<std::string_view> strings;
    strings.reserve(string_count);
    for (size_t index = 0; index < string_count; ++index) {
        size_t length = 0;
        auto const value = beidou_img_directory_string(parsed, index, &length);
        if (!value) throw std::runtime_error("IMG parser returned an invalid string index");
        strings.emplace_back(value, length);
    }

    nl::file file;
    file.open_nodes(std::move(nodes), std::move(strings), std::move(owner));
    return file;
}
