// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Observation.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <map>
#include <utility>
#include <vector>

namespace MapleControl {

// Static per-map navigation topology derived from the client's own foothold and
// rope geometry. The derivation is environment data: it uses the client
// navigation model constants below (standing body height, jump reach, drop
// corridor, rope grab reach), never character stats or script policy. Scripts
// consume the result to build their own edge costs, blocked edges and paths.
struct SceneFoothold {
    std::int64_t id = 0;
    std::int64_t x1 = 0;
    std::int64_t x2 = 0;
    std::int64_t y1 = 0;
    std::int64_t y2 = 0;
    std::int64_t prev = 0;
    std::int64_t next = 0;
};

struct SceneRope {
    std::int64_t index = 0;
    std::int64_t x = 0;
    std::int64_t y1 = 0;
    std::int64_t y2 = 0;
};

struct NavigationSegment {
    double left = 0;
    double right = 0;
    double y1 = 0; // Height at left.
    double y2 = 0; // Height at right.
};

struct NavigationPlatform {
    double left = 0;
    double right = 0;
    bool openLeft = true;
    bool openRight = true;
    std::vector<NavigationSegment> segments;
};

struct NavigationWall {
    double x = 0;
    double top = 0;
    double bottom = 0;
};

struct NavigationRopeLayer {
    int platform = 0; // One-based platform index.
    double y = 0;
};

struct NavigationRope {
    std::int64_t index = 0;
    double x = 0;
    double y1 = 0;
    double y2 = 0;
    std::vector<NavigationRopeLayer> platforms;
};

// One executable movement relation. x is the alignment point on the source
// platform and destination the target point on the destination platform. Rise
// sign and sampling points are candidate-kind-specific (see Connect()).
struct NavigationEdge {
    int from = 0; // One-based platform index.
    int to = 0;
    double x = 0;
    double destination = 0;
    double rise = 0;
    std::int64_t rope = 0;
};

// Static topology for one map. Candidates stay separate by kind so scripts can
// ignore kinds they do not execute and apply their own costs.
struct SceneNavigation {
    // Client navigation model constants. They are part of the static resource
    // derivation, identical on both backends, and published for scripts that
    // need the same limits when re-checking relations.
    double bodyHeight = 0;
    double wallMargin = 0;
    double minPlatformWidth = 0;
    double jumpRise = 0;
    double dropMin = 0;
    double dropMax = 0;
    double ropeGrab = 0;

    double terrainLeft = 0;
    double terrainRight = 0;
    std::vector<NavigationPlatform> platforms;
    std::vector<NavigationWall> walls;
    std::vector<NavigationRope> ropes;
    std::vector<NavigationEdge> walk;
    std::vector<NavigationEdge> step;
    std::vector<NavigationEdge> jumpup;
    std::vector<NavigationEdge> drop;
    std::vector<NavigationEdge> ropeEdges;
};

namespace scene_navigation {

// Constants of the shared navigation model. They describe the client's normal
// standing/jumping/falling capability used to derive static relations; scripts
// may re-check the same limits when adapting to current character attributes.
constexpr double kBodyHeight = 70;
constexpr double kWallMargin = 12;
constexpr double kMinPlatformWidth = 16;
constexpr double kJumpRise = 75;
constexpr double kDropMin = 4;
constexpr double kDropMax = 65;
constexpr double kRopeGrab = 76;

inline double SegmentHeight(const NavigationSegment& segment, double x) {
    if (segment.right == segment.left) return segment.y1;
    return segment.y1 + (segment.y2 - segment.y1) * (x - segment.left) / (segment.right - segment.left);
}

inline double PlatformHeight(const NavigationPlatform& platform, double x) {
    for (const auto& segment : platform.segments)
        if (x <= segment.right) return SegmentHeight(segment, x);
    return platform.segments.empty() ? 0 : SegmentHeight(platform.segments.back(), x);
}

inline double Inside(const NavigationPlatform& platform, double x) {
    return std::max(platform.left, std::min(platform.right, x));
}

inline NavigationSegment TrimSegment(const NavigationSegment& segment, double left, double right) {
    return {left, right, SegmentHeight(segment, left), SegmentHeight(segment, right)};
}

inline std::vector<NavigationSegment> Slice(const NavigationPlatform& platform, double left, double right) {
    std::vector<NavigationSegment> parts;
    for (const auto& segment : platform.segments) {
        const auto sliceLeft = std::max(segment.left, left);
        const auto sliceRight = std::min(segment.right, right);
        if (sliceRight > sliceLeft) parts.push_back(TrimSegment(segment, sliceLeft, sliceRight));
    }
    return parts;
}

inline bool WallBlocks(const NavigationWall& wall, const NavigationPlatform& platform, double x) {
    const auto y = PlatformHeight(platform, x);
    return wall.top <= y && wall.bottom >= y - kBodyHeight;
}

inline bool CrossesWall(const std::vector<NavigationWall>& walls, double x1, double x2, double yTop, double yBottom) {
    const auto left = std::min(x1, x2), right = std::max(x1, x2);
    for (const auto& wall : walls)
        if (wall.x > left + 1 && wall.x < right - 1 && wall.top <= yBottom && wall.bottom >= yTop) return true;
    return false;
}

inline void MergeWalls(const std::vector<SceneFoothold>& footholds, std::vector<NavigationWall>& walls) {
    std::vector<NavigationWall> segments;
    for (const auto& foothold : footholds) {
        if (foothold.x1 != foothold.x2) continue;
        segments.push_back({static_cast<double>(foothold.x1), static_cast<double>(std::min(foothold.y1, foothold.y2)),
                            static_cast<double>(std::max(foothold.y1, foothold.y2))});
    }
    std::sort(segments.begin(), segments.end(), [](const NavigationWall& a, const NavigationWall& b) {
        return a.x < b.x || (a.x == b.x && a.top < b.top);
    });
    for (const auto& segment : segments) {
        if (!walls.empty() && walls.back().x == segment.x && segment.top <= walls.back().bottom + 4)
            walls.back().bottom = std::max(walls.back().bottom, segment.bottom);
        else
            walls.push_back(segment);
    }
}

struct MergedSegment {
    std::int64_t id = 0;
    std::int64_t prev = 0;
    std::int64_t next = 0;
    double left = 0;
    double right = 0;
    double y1 = 0;
    double y2 = 0;
};

inline void MergePlatforms(const std::vector<SceneFoothold>& footholds, std::vector<NavigationPlatform>& platforms) {
    std::vector<MergedSegment> segments;
    for (const auto& foothold : footholds) {
        if (foothold.x1 == foothold.x2) continue;
        const double left = static_cast<double>(std::min(foothold.x1, foothold.x2));
        const double right = static_cast<double>(std::max(foothold.x1, foothold.x2));
        const double leftY = static_cast<double>(foothold.x1 < foothold.x2 ? foothold.y1 : foothold.y2);
        const double rightY = static_cast<double>(foothold.x1 < foothold.x2 ? foothold.y2 : foothold.y1);
        segments.push_back({foothold.id, foothold.prev, foothold.next, left, right, leftY, rightY});
    }
    std::map<std::int64_t, std::size_t> byId;
    for (std::size_t index = 0; index < segments.size(); ++index) byId[segments[index].id] = index;
    std::vector<bool> assigned(segments.size(), false);
    for (std::size_t seed = 0; seed < segments.size(); ++seed) {
        if (assigned[seed]) continue;
        std::vector<std::size_t> parts{seed};
        assigned[seed] = true;
        for (std::size_t cursor = 0; cursor < parts.size(); ++cursor) {
            const auto& part = segments[parts[cursor]];
            for (const auto neighborId : {part.prev, part.next}) {
                const auto found = byId.find(neighborId);
                if (found == byId.end() || assigned[found->second]) continue;
                const auto& neighbor = segments[found->second];
                const bool joinsRight = part.right == neighbor.left && part.y2 == neighbor.y1;
                const bool joinsLeft = part.left == neighbor.right && part.y1 == neighbor.y2;
                if (!joinsRight && !joinsLeft) continue;
                assigned[found->second] = true;
                parts.push_back(found->second);
            }
        }
        std::sort(parts.begin(), parts.end(),
                  [&](std::size_t a, std::size_t b) { return segments[a].left < segments[b].left; });
        NavigationPlatform platform;
        platform.left = segments[parts.front()].left;
        platform.right = segments[parts.back()].right;
        for (const auto index : parts) {
            const auto& segment = segments[index];
            platform.segments.push_back({segment.left, segment.right, segment.y1, segment.y2});
        }
        platforms.push_back(std::move(platform));
    }
}

inline void SplitPlatforms(const std::vector<NavigationWall>& walls, std::vector<NavigationPlatform>& platforms) {
    std::vector<NavigationPlatform> split;
    for (const auto& platform : platforms) {
        std::vector<double> cuts;
        for (const auto& wall : walls)
            if (wall.x > platform.left + kWallMargin && wall.x < platform.right - kWallMargin
                && WallBlocks(wall, platform, wall.x))
                cuts.push_back(wall.x);
        std::sort(cuts.begin(), cuts.end());
        if (cuts.empty()) {
            auto sliced = Slice(platform, platform.left, platform.right);
            if (!sliced.empty()) {
                NavigationPlatform result;
                result.left = platform.left;
                result.right = platform.right;
                result.openLeft = true;
                result.openRight = true;
                result.segments = std::move(sliced);
                split.push_back(std::move(result));
            }
            continue;
        }
        std::vector<double> bounds;
        double cursor = platform.left;
        for (const auto x : cuts) {
            if (x - kWallMargin >= cursor) {
                bounds.push_back(cursor);
                bounds.push_back(x - kWallMargin);
                cursor = x + kWallMargin;
            }
        }
        bounds.push_back(cursor);
        bounds.push_back(platform.right);
        for (std::size_t index = 0; index + 1 < bounds.size(); index += 2) {
            const auto left = bounds[index], right = bounds[index + 1];
            if (right - left < kMinPlatformWidth) continue;
            auto sliced = Slice(platform, left, right);
            if (sliced.empty()) continue;
            NavigationPlatform result;
            result.left = left;
            result.right = right;
            result.openLeft = left <= platform.left;
            result.openRight = right >= platform.right;
            result.segments = std::move(sliced);
            split.push_back(std::move(result));
        }
    }
    platforms = std::move(split);
}

inline void CloseOpenEdges(const std::vector<NavigationWall>& walls, std::vector<NavigationPlatform>& platforms) {
    for (auto& platform : platforms) {
        for (const auto& wall : walls) {
            if (platform.openLeft && wall.x >= platform.left - kDropMin && wall.x <= platform.left + 3
                && WallBlocks(wall, platform, std::max(platform.left, wall.x)))
                platform.openLeft = false;
            if (platform.openRight && wall.x <= platform.right + kDropMin && wall.x >= platform.right - 3
                && WallBlocks(wall, platform, std::min(platform.right, wall.x)))
                platform.openRight = false;
        }
    }
}

inline void Connect(const std::vector<NavigationWall>& walls, double terrainLeft, double terrainRight,
                    SceneNavigation& navigation) {
    auto& platforms = navigation.platforms;
    const auto height = [](const NavigationPlatform& platform, double x) { return PlatformHeight(platform, x); };
    const auto inside = [](const NavigationPlatform& platform, double x) { return Inside(platform, x); };
    const auto add = [](std::vector<NavigationEdge>& edges, int from, int to, double x, double destination,
                        double rise) {
        if (from == to) return;
        edges.push_back({from, to, x, destination, rise, 0});
    };
    for (int i = 0; i < static_cast<int>(platforms.size()); ++i) {
        const auto& a = platforms[static_cast<std::size_t>(i)];
        for (int j = 0; j < static_cast<int>(platforms.size()); ++j) {
            if (j == i) continue;
            const auto& b = platforms[static_cast<std::size_t>(j)];
            const double direction = a.right <= b.left ? 1 : -1;
            const double ax = direction == 1 ? a.right : a.left;
            const double bx = direction == 1 ? b.left : b.right;
            const double gap = (bx - ax) * direction;
            const double rise = height(a, ax) - height(b, bx);
            if (gap >= 0 && gap <= 2 && std::abs(rise) <= 6) {
                const double fromX = inside(a, ax - direction * 8);
                const double toX = inside(b, bx + direction * 14);
                const double fromY = height(a, fromX), toY = height(b, toX);
                if (!CrossesWall(walls, ax, bx, std::min(fromY, toY) - kBodyHeight, std::max(fromY, toY)))
                    add(navigation.walk, i + 1, j + 1, fromX, toX, rise);
            }
            if (gap == 0 && rise > 6 && rise <= kJumpRise && a.right - a.left >= kMinPlatformWidth
                && b.right - b.left >= kMinPlatformWidth) {
                const double fromX = ax - direction * 6;
                const double toX = bx + direction * 10;
                const double fromY = height(a, fromX), toY = height(b, toX);
                const double actualRise = fromY - toY;
                bool sharedWall = false, blocked = actualRise <= 6 || actualRise > kJumpRise;
                for (const auto& wall : walls) {
                    if (wall.x == ax && wall.bottom >= height(a, ax) && wall.top <= height(b, bx)) {
                        sharedWall = true;
                        if (wall.top < height(b, bx)) blocked = true;
                    } else if (wall.x > std::min(fromX, toX) && wall.x < std::max(fromX, toX) && wall.top <= fromY
                               && wall.bottom >= toY - kBodyHeight) {
                        blocked = true;
                    }
                    if (wall.x != ax && std::abs(wall.x - toX) < kWallMargin && WallBlocks(wall, b, toX))
                        blocked = true;
                }
                for (int k = 0; k < static_cast<int>(platforms.size()); ++k) {
                    if (k == i || k == j) continue;
                    const auto& ceiling = platforms[static_cast<std::size_t>(k)];
                    const double left = std::max(ceiling.left, std::min(fromX, toX));
                    const double right = std::min(ceiling.right, std::max(fromX, toX));
                    if (left > right) continue;
                    const double y1 = height(ceiling, left), y2 = height(ceiling, right);
                    if (std::min(y1, y2) < fromY && std::max(y1, y2) > toY - kBodyHeight) blocked = true;
                }
                if (sharedWall && !blocked) add(navigation.jumpup, i + 1, j + 1, fromX, toX, actualRise);
            }
            if (gap > 2 && gap <= 40 && rise > 6 && rise <= kJumpRise) {
                const double fromX = inside(a, ax - direction * 6);
                const double toX = inside(b, bx + direction * 10);
                const double fromY = height(a, fromX), toY = height(b, toX);
                if (!CrossesWall(walls, ax, bx, std::min(fromY, toY) - kBodyHeight, std::max(fromY, toY)))
                    add(navigation.step, i + 1, j + 1, fromX, toX, rise);
            }
        }
        for (const double direction : {-1.0, 1.0}) {
            const bool open = direction == -1 ? a.openLeft : a.openRight;
            if (!open) continue;
            const double edgeX = direction == -1 ? a.left : a.right;
            double windowLeft = direction == -1 ? edgeX - kDropMax : edgeX + kDropMin;
            double windowRight = direction == -1 ? edgeX - kDropMin : edgeX + kDropMax;
            windowLeft = std::max(windowLeft, terrainLeft + 30);
            windowRight = std::min(windowRight, terrainRight - 30);
            if (windowRight < windowLeft) continue;
            const double edgeY = height(a, edgeX);
            for (int j = 0; j < static_cast<int>(platforms.size()); ++j) {
                if (j == i) continue;
                const auto& b = platforms[static_cast<std::size_t>(j)];
                const double overlapLeft = std::max(windowLeft, b.left);
                const double overlapRight = std::min(windowRight, b.right);
                if (overlapRight < overlapLeft) continue;
                const double landingX = (overlapLeft + overlapRight) / 2;
                const double landingY = height(b, landingX);
                if (landingY <= edgeY + 6) continue;
                if (CrossesWall(walls, edgeX, landingX, landingY - kBodyHeight, edgeY)) continue;
                add(navigation.drop, i + 1, j + 1, inside(a, edgeX - direction * 8), landingX, landingY - edgeY);
            }
        }
        for (int j = 0; j < static_cast<int>(platforms.size()); ++j) {
            if (j == i) continue;
            const auto& b = platforms[static_cast<std::size_t>(j)];
            const double overlapLeft = std::max(a.left, b.left);
            const double overlapRight = std::min(a.right, b.right);
            if (overlapRight - overlapLeft < 10) continue;
            const double probe = (overlapLeft + overlapRight) / 2;
            const double rise = height(a, probe) - height(b, probe);
            if (rise <= 6 || rise > kJumpRise) continue;
            bool blocked = false;
            for (const auto& wall : walls)
                if (wall.x > overlapLeft - kWallMargin && wall.x < overlapRight + kWallMargin
                    && wall.top <= height(b, probe) && wall.bottom >= height(a, probe) - kBodyHeight) {
                    blocked = true;
                    break;
                }
            if (!blocked) add(navigation.jumpup, i + 1, j + 1, inside(a, probe), inside(b, probe), rise);
        }
    }
    for (auto& rope : navigation.ropes) {
        std::vector<NavigationRopeLayer> touching;
        for (int i = 0; i < static_cast<int>(platforms.size()); ++i) {
            const auto& platform = platforms[static_cast<std::size_t>(i)];
            if (rope.x < platform.left || rope.x > platform.right) continue;
            const double y = height(platform, rope.x);
            if (y >= rope.y1 - 12 && y <= rope.y2 + kRopeGrab) touching.push_back({i + 1, y});
        }
        if (touching.empty()) continue;
        std::sort(touching.begin(), touching.end(),
                  [](const NavigationRopeLayer& a, const NavigationRopeLayer& b) { return a.y < b.y; });
        std::vector<NavigationRopeLayer> layers;
        for (const auto& entry : touching) {
            if (!layers.empty() && std::abs(layers.back().y - entry.y) <= 6)
                layers.back().platform = std::min(layers.back().platform, entry.platform);
            else
                layers.push_back(entry);
        }
        for (std::size_t index = 0; index + 1 < layers.size(); ++index) {
            const auto& lower = layers[index];
            const auto& upper = layers[index + 1];
            navigation.ropeEdges.push_back(
                {lower.platform, upper.platform, rope.x, rope.x, upper.y - lower.y, rope.index});
            navigation.ropeEdges.push_back(
                {upper.platform, lower.platform, rope.x, rope.x, lower.y - upper.y, rope.index});
        }
        rope.platforms = std::move(layers);
    }
}

} // namespace scene_navigation

inline SceneNavigation BuildSceneNavigation(const std::vector<SceneFoothold>& footholds,
                                            const std::vector<SceneRope>& ropes) {
    namespace sn = scene_navigation;
    SceneNavigation navigation;
    navigation.bodyHeight = sn::kBodyHeight;
    navigation.wallMargin = sn::kWallMargin;
    navigation.minPlatformWidth = sn::kMinPlatformWidth;
    navigation.jumpRise = sn::kJumpRise;
    navigation.dropMin = sn::kDropMin;
    navigation.dropMax = sn::kDropMax;
    navigation.ropeGrab = sn::kRopeGrab;
    double left = std::numeric_limits<double>::infinity();
    double right = -std::numeric_limits<double>::infinity();
    for (const auto& foothold : footholds) {
        left = std::min(left, static_cast<double>(std::min(foothold.x1, foothold.x2)));
        right = std::max(right, static_cast<double>(std::max(foothold.x1, foothold.x2)));
    }
    navigation.terrainLeft = std::isfinite(left) ? left : 0;
    navigation.terrainRight = std::isfinite(right) ? right : 0;
    navigation.ropes.resize(ropes.size());
    for (std::size_t index = 0; index < ropes.size(); ++index) {
        navigation.ropes[index].index = ropes[index].index;
        navigation.ropes[index].x = static_cast<double>(ropes[index].x);
        navigation.ropes[index].y1 = static_cast<double>(ropes[index].y1);
        navigation.ropes[index].y2 = static_cast<double>(ropes[index].y2);
    }
    sn::MergeWalls(footholds, navigation.walls);
    sn::MergePlatforms(footholds, navigation.platforms);
    sn::SplitPlatforms(navigation.walls, navigation.platforms);
    sn::CloseOpenEdges(navigation.walls, navigation.platforms);
    if (!navigation.platforms.empty())
        sn::Connect(navigation.walls, navigation.terrainLeft, navigation.terrainRight, navigation);
    return navigation;
}

inline Value SceneNavigationValue(const SceneNavigation& navigation) {
    Value model = Value::Object({{"stand_height", navigation.bodyHeight},
                                 {"wall_margin", navigation.wallMargin},
                                 {"min_platform_width", navigation.minPlatformWidth},
                                 {"jump_rise", navigation.jumpRise},
                                 {"drop_min", navigation.dropMin},
                                 {"drop_max", navigation.dropMax},
                                 {"rope_grab", navigation.ropeGrab}});
    Value platforms = Value::Array();
    for (std::size_t index = 0; index < navigation.platforms.size(); ++index) {
        const auto& platform = navigation.platforms[index];
        Value segments = Value::Array();
        for (const auto& segment : platform.segments) {
            segments.Add(segment.left);
            segments.Add(segment.right);
            segments.Add(segment.y1);
            segments.Add(segment.y2);
        }
        platforms.Add(Value::Object({{"index", static_cast<int>(index + 1)},
                                     {"left", platform.left},
                                     {"right", platform.right},
                                     {"open_left", platform.openLeft},
                                     {"open_right", platform.openRight},
                                     {"segments", std::move(segments)}}));
    }
    Value walls = Value::Array();
    for (const auto& wall : navigation.walls) {
        walls.Add(wall.x);
        walls.Add(wall.top);
        walls.Add(wall.bottom);
    }
    Value ropes = Value::Array();
    for (const auto& rope : navigation.ropes) {
        Value touching = Value::Array();
        for (const auto& layer : rope.platforms) {
            touching.Add(layer.platform);
            touching.Add(layer.y);
        }
        ropes.Add(Value::Object({{"index", rope.index},
                                 {"x", rope.x},
                                 {"y1", rope.y1},
                                 {"y2", rope.y2},
                                 {"platforms", std::move(touching)}}));
    }
    const auto edges = [](const std::vector<NavigationEdge>& source, bool withRope) {
        Value array = Value::Array();
        for (const auto& edge : source) {
            array.Add(edge.from);
            array.Add(edge.to);
            array.Add(edge.x);
            array.Add(edge.destination);
            array.Add(edge.rise);
            if (withRope) array.Add(edge.rope);
        }
        return array;
    };
    Value candidates = Value::Object({{"walk", edges(navigation.walk, false)},
                                      {"step", edges(navigation.step, false)},
                                      {"jumpup", edges(navigation.jumpup, false)},
                                      {"drop", edges(navigation.drop, false)},
                                      {"rope", edges(navigation.ropeEdges, true)}});
    return Value::Object({{"model", std::move(model)},
                          {"terrain_left", navigation.terrainLeft},
                          {"terrain_right", navigation.terrainRight},
                          {"platforms", std::move(platforms)},
                          {"walls", std::move(walls)},
                          {"ropes", std::move(ropes)},
                          {"candidates", std::move(candidates)}});
}

} // namespace MapleControl
