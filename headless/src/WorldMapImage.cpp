// SPDX-License-Identifier: AGPL-3.0-or-later
#include "WorldMapImage.h"

#include "ImgResources.h"

#include <array>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <sstream>
#include <thread>
#include <vector>

namespace MapleControl {
namespace {

std::string NativePath(const std::filesystem::path& path) {
#if defined(__cpp_lib_char8_t)
    const auto utf8 = path.u8string();
    return std::string(utf8.begin(), utf8.end());
#else
    return path.u8string();
#endif
}

// A typed, read-only view over the IMG C ABI for one already-opened image.
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
        return text == nullptr ? std::string{} : std::string(text, length);
    }

    ImgNode operator[](const std::string& name) const {
        for (std::size_t index = info.children; index < info.children + info.child_count; ++index) {
            ImgNode child(owner, index);
            if (child.present && child.name() == name) return child;
        }
        return {};
    }

    class Iterator {
    public:
        Iterator(const BeidouImgDirectory* owner, std::size_t index) : owner(owner), index(index) {}

        ImgNode operator*() const { return {owner, index}; }

        Iterator& operator++() {
            ++index;
            return *this;
        }

        bool operator!=(const Iterator& other) const { return index != other.index; }

    private:
        const BeidouImgDirectory* owner;
        std::size_t index;
    };

    Iterator begin() const { return {owner, info.children}; }
    Iterator end() const { return {owner, info.children + info.child_count}; }

    bool Integer(std::int64_t& value) const {
        if (!present || info.type != BEIDOU_IMG_NODE_INTEGER) return false;
        value = info.integer;
        return true;
    }

    bool String(std::string& value) const {
        if (!present || info.type != BEIDOU_IMG_NODE_STRING) return false;
        std::size_t length = 0;
        const auto* text = beidou_img_directory_string(owner, info.value_string_id, &length);
        if (text == nullptr) return false;
        value.assign(text, length);
        return true;
    }

private:
    const BeidouImgDirectory* owner = nullptr;
    BeidouImgNodeInfo info{};
    bool present = false;
};

struct CacheLock {
    std::filesystem::path directory;
    bool held = false;

    ~CacheLock() {
        if (!held) return;
        std::error_code ignored;
        std::filesystem::remove(directory, ignored);
    }
};

bool ReadCache(const std::filesystem::path& path, const std::string& fingerprint, WorldMapModel& model) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return false;
    std::ostringstream buffer;
    buffer << input.rdbuf();
    if (!input.good() && !input.eof()) return false;
    WorldMapModel parsed;
    std::string error;
    if (!ParseWorldMap(buffer.str(), parsed, error)) return false;
    if (parsed.sourceFingerprint != fingerprint) return false;
    model = std::move(parsed);
    return true;
}

bool WriteCache(const std::filesystem::path& path, const WorldMapModel& model) {
    std::error_code error;
    std::filesystem::create_directories(path.parent_path(), error);
    if (error) return false;
    const auto temporary = path.string() + ".tmp-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output) return false;
        output << SerializeWorldMap(model);
        if (!output) {
            output.close();
            std::filesystem::remove(temporary, error);
            return false;
        }
    }
    std::filesystem::rename(temporary, path, error);
    if (!error) return true;
    // Another process may have published the same versioned cache first.
    std::error_code ignored;
    if (std::filesystem::is_regular_file(path, ignored)) {
        std::filesystem::remove(temporary, ignored);
        return true;
    }
    std::filesystem::remove(temporary, ignored);
    return false;
}

std::vector<std::filesystem::path> MapFiles(const std::filesystem::path& dataRoot) {
    std::error_code error;
    const auto root = std::filesystem::is_directory(dataRoot / "Map002", error) ? dataRoot / "Map002"
                                                                                : dataRoot / "Map";
    std::vector<std::filesystem::path> files;
    for (const auto& group : std::filesystem::directory_iterator(root / "Map", error)) {
        if (error || !group.is_directory()) continue;
        for (const auto& entry : std::filesystem::directory_iterator(group.path(), error)) {
            if (error) break;
            if (entry.is_regular_file() && entry.path().extension() == ".img") files.push_back(entry.path());
        }
    }
    std::sort(files.begin(), files.end());
    return files;
}

std::string CacheKey(const std::filesystem::path& dataRoot, const std::vector<std::filesystem::path>& files) {
    std::vector<WorldMapFile> inventory;
    inventory.reserve(files.size());
    constexpr std::streamsize kSample = 4096;
    for (const auto& path : files) {
        std::error_code error;
        const auto size = std::filesystem::file_size(path, error);
        if (error) return {};
        std::ifstream input(path, std::ios::binary);
        if (!input) return {};
        std::string sample;
        const auto head = static_cast<std::streamsize>(std::min<std::uint64_t>(size, kSample));
        sample.resize(static_cast<std::size_t>(head));
        input.read(sample.data(), head);
        if (!input) return {};
        if (size > static_cast<std::uint64_t>(kSample)) {
            input.clear();
            input.seekg(-kSample, std::ios::end);
            std::string tail(static_cast<std::size_t>(kSample), '\0');
            input.read(tail.data(), kSample);
            if (!input) return {};
            sample += tail;
        }
        inventory.push_back({path.lexically_relative(dataRoot).generic_string(), size,
                             HashWorldMapContent(sample)});
    }
    return FingerprintWorldMapFiles(std::move(inventory));
}

bool BuildModel(const std::vector<std::filesystem::path>& files, const std::string& fingerprint,
                WorldMapModel& model, std::string& error) {
    WorldMapModel built;
    built.sourceFingerprint = fingerprint;
    for (const auto& path : files) {
        std::int64_t mapId = 0;
        try {
            mapId = std::stoll(path.stem().string());
        } catch (const std::exception&) {
            error = "world_map_file_invalid";
            return false;
        }
        std::array<char, 4096> message{};
        BeidouImgDirectory* opened = nullptr;
        if (!beidou_img_file_open(NativePath(path).c_str(), &opened, message.data(), message.size())) {
            error = std::string("world_map_open_failed: ") + message.data();
            return false;
        }
        std::unique_ptr<BeidouImgDirectory, decltype(&beidou_img_directory_close)> image(opened,
                                                                                       beidou_img_directory_close);
        std::vector<WorldPortal> portals;
        std::string portalError;
        if (!ReadWorldPortals(
                ImgNode(image.get(), 0), portals, portalError,
                [](const ImgNode& node, std::int64_t& value) { return node.Integer(value); },
                [](const ImgNode& node, std::string& value) { return node.String(value); })) {
            error = portalError + ":" + std::to_string(mapId);
            return false;
        }
        built.scenes.emplace(mapId, std::move(portals));
    }
    BuildWorldMapEdges(built);
    model = std::move(built);
    return true;
}

} // namespace

std::string WorldMapCacheRootFromEnvironment() {
    const auto* value = std::getenv("BEIDOU_CACHE_DIR");
    return value == nullptr ? std::string{} : std::string(value);
}

bool LoadOrBuildWorldMap(const std::string& dataRootText, std::string cacheRoot, WorldMapModel& model,
                         std::string& cacheState, std::string& error) {
    cacheState.clear();
    error.clear();
    const auto dataRoot = std::filesystem::u8path(dataRootText);
    const auto files = MapFiles(dataRoot);
    if (files.empty()) {
        error = "world_map_data_unavailable";
        return false;
    }
    const auto fingerprint = CacheKey(dataRoot, files);
    if (fingerprint.empty()) {
        error = "world_map_data_unreadable";
        return false;
    }
    std::filesystem::path cachePath;
    if (!cacheRoot.empty()) {
        cachePath = std::filesystem::u8path(cacheRoot) / WorldMapCacheRelativePath(fingerprint);
        if (ReadCache(cachePath, fingerprint, model)) {
            cacheState = "hit";
            return true;
        }
    }
    CacheLock lock;
    if (!cacheRoot.empty()) {
        std::error_code ignored;
        std::filesystem::create_directories(cachePath.parent_path(), ignored);
        lock.directory = cachePath;
        lock.directory += ".lock";
        lock.held = std::filesystem::create_directory(lock.directory, ignored);
        if (!lock.held) {
            // Another client process is deriving the same version. Wait for its
            // atomic publish instead of duplicating the decode work.
            const auto until = std::chrono::steady_clock::now() + std::chrono::seconds(10);
            while (std::chrono::steady_clock::now() < until) {
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
                if (ReadCache(cachePath, fingerprint, model)) {
                    cacheState = "hit";
                    return true;
                }
                if (!std::filesystem::exists(lock.directory)) {
                    lock.held = std::filesystem::create_directory(lock.directory, ignored);
                    if (lock.held) break;
                }
            }
        }
    }
    if (!BuildModel(files, fingerprint, model, error)) return false;
    bool stored = false;
    if (!cacheRoot.empty()) stored = WriteCache(cachePath, model);
    if (lock.held) {
        std::error_code ignored;
        std::filesystem::remove(lock.directory, ignored);
        lock.held = false;
    }
    cacheState = stored ? "built" : "memory";
    return true;
}

} // namespace MapleControl
