// SPDX-License-Identifier: AGPL-3.0-or-later
#define NL_METADATA_ONLY
#define NL_NO_MAIN
#define NL_NO_PROGRESS_OUTPUT
#define NL_PRESERVE_UNRESOLVED_UOL
#include "../../third_party/nolifewztonx/NoLifeWzToNx.cpp"

#include "ImgResources.h"

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
class DirectoryParser final : public nl::wztonx {
public:
    DirectoryParser(std::filesystem::path source, bool base_only)
        : nl::wztonx(source, true, false), source(std::move(source)), base_only(base_only) {}

    void parse() {
        add_string({});
        add_directory(0, source);
        finish_parse();
    }

    std::filesystem::path source;
    bool base_only;
    std::vector<std::string> sources;

private:
    void assign_source(nl::wz::id_t parent, uint32_t source_id) {
        auto& node = nodes[parent];
        node.source_file_id = source_id;
        for (uint32_t index = 0; index < node.num; ++index)
            assign_source(node.children + index, source_id);
    }

    void add_directory(nl::wz::id_t parent, std::filesystem::path const& path) {
        std::vector<std::filesystem::path> entries;
        for (auto const& entry : std::filesystem::directory_iterator(path)) {
            if ((!base_only && entry.is_directory()) ||
                (entry.is_regular_file() && entry.path().extension() == ".img"))
                entries.push_back(entry.path());
        }
        std::sort(entries.begin(), entries.end());
        auto first = static_cast<nl::wz::id_t>(nodes.size());
        nodes[parent].children = first;
        nodes[parent].num = static_cast<uint16_t>(entries.size());
        nodes.resize(first + entries.size());
        for (size_t index = 0; index < entries.size(); ++index) {
            auto child = first + static_cast<nl::wz::id_t>(index);
            auto const& entry = entries[index];
            nodes[child].name = add_string(entry.filename().string());
            nodes[child].source_order = static_cast<uint16_t>(index);
            if (std::filesystem::is_directory(entry)) {
                add_directory(child, entry);
            } else {
                const auto source_id = static_cast<uint32_t>(sources.size());
                sources.push_back(entry.string());
                in.open(entry.string());
                img(child, static_cast<int32_t>(std::filesystem::file_size(entry)));
                assign_source(child, source_id);
            }
        }
        nodes_to_sort.emplace_back(first, entries.size());
    }
};

void set_error(char* output, size_t capacity, std::string const& error) {
    if (!output || capacity == 0) return;
    const auto length = std::min(capacity - 1, error.size());
    std::memcpy(output, error.data(), length);
    output[length] = '\0';
}
}

struct BeidouImgDirectory {
    explicit BeidouImgDirectory(std::filesystem::path const& path, bool base_only)
        : parser(path, base_only) {
        parser.parse();
    }

    DirectoryParser parser;
};

extern "C" int beidou_img_directory_open(const char* path, int base_only,
                                          BeidouImgDirectory** result,
                                          char* error, size_t error_capacity) {
    if (!path || !result) {
        set_error(error, error_capacity, "IMG directory path and result are required");
        return 0;
    }
    try {
        *result = new BeidouImgDirectory(path, base_only != 0);
        return 1;
    } catch (std::exception const& failure) {
        *result = nullptr;
        set_error(error, error_capacity, failure.what());
        return 0;
    }
}

extern "C" void beidou_img_directory_close(BeidouImgDirectory* directory) {
    delete directory;
}

extern "C" size_t beidou_img_directory_node_count(BeidouImgDirectory const* directory) {
    return directory ? directory->parser.nodes.size() : 0;
}

extern "C" size_t beidou_img_directory_string_count(BeidouImgDirectory const* directory) {
    return directory ? directory->parser.strings.size() : 0;
}

extern "C" size_t beidou_img_directory_source_count(BeidouImgDirectory const* directory) {
    return directory ? directory->parser.sources.size() : 0;
}

extern "C" int beidou_img_directory_node(BeidouImgDirectory const* directory, size_t index,
                                          BeidouImgNodeInfo* result) {
    if (!directory || !result || index >= directory->parser.nodes.size()) return 0;
    auto const& source = directory->parser.nodes[index];
    *result = {};
    result->name_string_id = source.name;
    result->children = source.children;
    result->source_file_id = source.source_file_id;
    result->source_order = source.source_order;
    result->child_count = source.num;
    result->type = static_cast<uint16_t>(source.data_type);
    switch (source.data_type) {
    case nl::wz::node::type::integer:
        result->integer = source.data.integer;
        break;
    case nl::wz::node::type::real:
        result->real = source.data.real;
        break;
    case nl::wz::node::type::string:
    case nl::wz::node::type::uol:
        result->value_string_id = source.data.string;
        break;
    case nl::wz::node::type::vector:
        result->vector_x = source.data.vector[0];
        result->vector_y = source.data.vector[1];
        break;
    case nl::wz::node::type::bitmap:
        result->bitmap_id = source.data.bitmap.id;
        result->bitmap_width = source.data.bitmap.width;
        result->bitmap_height = source.data.bitmap.height;
        break;
    case nl::wz::node::type::audio:
        result->audio_id = source.data.audio.id;
        result->audio_length = source.data.audio.length;
        break;
    case nl::wz::node::type::none:
        break;
    }
    return 1;
}

extern "C" const char* beidou_img_directory_string(BeidouImgDirectory const* directory,
                                                    size_t index, size_t* length) {
    if (!directory || !length || index >= directory->parser.strings.size()) return nullptr;
    auto const& value = directory->parser.strings[index];
    *length = value.size();
    return value.data();
}

extern "C" const char* beidou_img_directory_source(BeidouImgDirectory const* directory,
                                                   size_t index, size_t* length) {
    if (!directory || !length || index >= directory->parser.sources.size()) return nullptr;
    auto const& value = directory->parser.sources[index];
    *length = value.size();
    return value.data();
}
