// SPDX-License-Identifier: AGPL-3.0-or-later
// V17 inbound path playback contract (docs/V17_EXTENDED_MOTION_RULES.md §10):
// segments carry durations and endpoint position/velocity constraints; unfinished
// segments use cubic Hermite interpolation; catch-up selects 33ms while the buffer
// is above 1100ms and 30ms otherwise.
#include "Gameplay/MovementReplay.h"

#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

void Near(double actual, double expected, const std::string& message, double tolerance = 1e-6) {
    if (std::abs(actual - expected) > tolerance) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}

ms::Movement Absolute(int16_t x, int16_t y, int16_t vx, int16_t vy, int16_t duration) {
    ms::Movement move;
    move.command = 0;
    move.type = ms::Movement::ABSOLUTE;
    move.xpos = x;
    move.ypos = y;
    move.lastx = vx;
    move.lasty = vy;
    move.vx = vx;
    move.vy = vy;
    move.fh = 1;
    move.newstate = 2;
    move.duration = duration;
    return move;
}

ms::Movement Relative(int16_t vx, int16_t vy, int16_t duration) {
    ms::Movement move;
    move.command = 1;
    move.type = ms::Movement::RELATIVE;
    move.vx = vx;
    move.vy = vy;
    move.newstate = 3;
    move.duration = duration;
    return move;
}
}

int main() {
    // Linear absolute segment: 0 -> (100,0) over 1000ms with zero endpoint speeds.
    {
        ms::MovementReplay replay;
        std::vector<ms::Movement> path{Absolute(100, 0, 0, 0, 1000)};
        replay.Reset(ms::Point<int16_t>(0, 0), std::move(path));
        Check(!replay.Empty(), "path_not_empty");
        Check(replay.StepMs() == 30, "short_buffer_uses_30ms");
        auto sample = replay.Advance(300);
        Near(sample.x, 21.6, "linear_x_at_300ms");
        Near(sample.y, 0.0, "linear_y_at_300ms");
        Check(sample.fh == 1 && sample.state == 2, "segment_state_and_fh");
        Check(replay.RemainingMs() == 700, "remaining_after_300ms");
        sample = replay.Advance(700);
        Near(sample.x, 100.0, "segment_endpoint");
        Check(sample.finished && replay.Empty(), "segment_completed");
    }

    // Velocity endpoint: two segments where the second inherits the endpoint position
    // and carries a velocity constraint (Hermite h11 term).
    {
        ms::MovementReplay replay;
        std::vector<ms::Movement> path{Absolute(100, 0, 0, 0, 1000), Relative(125, 0, 500)};
        replay.Reset(ms::Point<int16_t>(0, 0), std::move(path));
        Near(replay.RemainingMs(), 1500, "two_segment_remaining");
        auto sample = replay.Advance(1000);
        Near(sample.x, 100.0, "first_segment_end");
        sample = replay.Advance(250);
        Near(sample.x, 92.1875, "relative_velocity_hermite_half_segment");
        sample = replay.Advance(250);
        Near(sample.x, 100.0, "relative_segment_returns_to_inherited_endpoint");
        Check(sample.finished, "relative_segment_finished");
    }

    // Catch-up: long buffers advance 33ms, short buffers 30ms.
    {
        ms::MovementReplay replay;
        std::vector<ms::Movement> path{Absolute(200, 0, 0, 0, 3000)};
        replay.Reset(ms::Point<int16_t>(0, 0), std::move(path));
        Check(replay.StepMs() == 33, "long_buffer_uses_33ms");
        replay.Advance(2000);
        Check(replay.StepMs() == 30, "remaining_1000_uses_30ms");
    }

    // Zero-duration command entries are skipped without stalling the following one.
    {
        ms::MovementReplay replay;
        ms::Movement instant;
        instant.command = 21;
        instant.newstate = 4;
        instant.duration = 0;
        std::vector<ms::Movement> path{instant, Absolute(50, 10, 0, 0, 500)};
        replay.Reset(ms::Point<int16_t>(0, 0), std::move(path));
        auto sample = replay.Advance(500);
        Near(sample.x, 50.0, "zero_duration_then_absolute_x");
        Near(sample.y, 10.0, "zero_duration_then_absolute_y");
        Check(sample.finished, "zero_duration_path_finished");
    }

    std::cout << "ok\n";
    return 0;
}
