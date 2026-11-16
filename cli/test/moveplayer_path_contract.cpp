// SPDX-License-Identifier: AGPL-3.0-or-later
// V17 MOVE_PLAYER path recorder contract: merge rules, direction records, 500ms
// gate and bounding box (docs/V17_EXTENDED_MOTION_RULES.md §10).
#include "Character/MovePlayerPath.h"

#include <cstdlib>
#include <iostream>

namespace {
void Check(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

ms::Movement Fragment(int16_t x, int16_t y, int16_t vx, int16_t vy) {
    ms::Movement move;
    move.command = 0;
    move.type = ms::Movement::ABSOLUTE;
    move.xpos = x;
    move.ypos = y;
    move.lastx = vx;
    move.lasty = vy;
    move.fh = 1;
    move.newstate = 2;
    move.duration = 1;
    return move;
}
}

int main() {
    ms::MovePlayerPath path;
    path.Reset(ms::Point<int16_t>(100, 200));
    for (int step = 0; step < 16; ++step) path.Append(30, Fragment(100 + step * 3, 200, 125, 0), 4);
    Check(path.DurationMs() == 480, "duration_accumulates");
    Check(!path.ShouldSend(), "gate_holds_under_500ms");
    path.Append(30, Fragment(148, 200, 125, 0), 4);
    Check(path.DurationMs() == 510, "gate_reached_at_510ms");
    Check(path.ShouldSend(), "gate_sends_at_500ms");
    Check(path.Fragments().size() == 1, "same_sign_fragments_merge");
    Check(path.Fragments().front().duration == 510, "merged_duration_sums");
    Check(path.Fragments().front().xpos == 148, "merged_endpoint_updates");
    Check(path.Directions().size() == 17, "one_direction_record_per_step");

    const auto bounds = path.Bounds();
    Check(bounds.minX == 100 && bounds.maxX == 148 && bounds.minY == 200 && bounds.maxY == 200, "bounds_cover_path");

    // A velocity sign crossing starts a new node.
    path.Reset(path.LastEndpoint());
    path.Append(30, Fragment(150, 200, 125, 0), 4);
    path.Append(30, Fragment(140, 200, -125, 0), 8);
    Check(path.Fragments().size() == 2, "sign_crossing_starts_new_node");
    Check(path.Directions().size() == 2, "direction_records_stay_per_step");

    std::cout << "ok\n";
    return 0;
}
