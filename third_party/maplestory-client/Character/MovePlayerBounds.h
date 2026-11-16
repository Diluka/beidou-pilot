// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "../Template/Point.h"

#include <algorithm>
#include <cstdint>

namespace ms
{
// V17 MOVE_PLAYER tail bounding box (docs/V17_EXTENDED_MOTION_RULES.md §10):
// four words minX/minY/maxX/maxY, initialized with the path start and updated by
// absolute coordinates. For a single absolute fragment it is the component-wise
// min/max of start and endpoint.
struct MovePlayerBounds
{
    int16_t minX = 0;
    int16_t minY = 0;
    int16_t maxX = 0;
    int16_t maxY = 0;
};

inline MovePlayerBounds MovePlayerPathBounds(Point<int16_t> start, Point<int16_t> end)
{
    MovePlayerBounds bounds;
    bounds.minX = std::min(start.x(), end.x());
    bounds.minY = std::min(start.y(), end.y());
    bounds.maxX = std::max(start.x(), end.x());
    bounds.maxY = std::max(start.y(), end.y());
    return bounds;
}
}
