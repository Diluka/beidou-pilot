// SPDX-License-Identifier: AGPL-3.0-or-later
// The original attached-climb 30ms branch on plain geometry. Expected values are
// the literal BeiDou.exe rules from docs/V17_EXTENDED_MOTION_RULES.md §2:
// K=3.0 per 30ms, top exit y=top-5 vs top clamp, bottom exit y=bottom+1, and the
// 0x9B1D3D jump-off velocities for the ordinary SPEED/JUMP=100 profile.
#include "ImgResourceFile.h"
#include "Gameplay/Physics/V17ClimbMotion.h"
#include "Gameplay/Physics/V17PhysicsParameters.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>

namespace {
constexpr double StepSeconds = 0.030;

void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

void Near(double actual, double expected, const std::string& message) {
    if (std::abs(actual - expected) > 1e-9) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}

void Load(const char* physicsDirectory) {
    auto physics = load_img_directory(physicsDirectory);
    ms::V17PhysicsParameters::Init(physics.root()["Physics.img"]);
}

ms::V17ClimbGeometry Rope(bool exitsAtTop) {
    ms::V17ClimbGeometry geometry;
    geometry.x = 100.0;
    geometry.top = 100;
    geometry.bottom = 900;
    geometry.exitsAtTop = exitsAtTop;
    return geometry;
}

ms::V17ClimbStep Step(const ms::V17ClimbGeometry& geometry, double y, int vertical, int horizontal = 0,
                      bool jumpRequested = false) {
    ms::V17MotionMultipliers multipliers;
    return ms::V17ClimbMotion::Step(geometry, 100.0, y, vertical, horizontal, jumpRequested,
                                    ms::V17PhysicsParameters::Get(), multipliers);
}

void Up() {
    const auto geometry = Rope(true);
    double y = 500.0;
    for (int step = 0; step < 3; ++step) {
        const auto result = Step(geometry, y, -1);
        Check(result.attached && !result.exitedTop && !result.exitedBottom, "up_stays_attached");
        Near(result.x, 100.0, "up_x");
        y = result.y;
    }
    Near(y, 491.0, "up_three_steps");
}

void Down() {
    const auto geometry = Rope(true);
    auto result = Step(geometry, 894.0, 1);
    Near(result.y, 897.0, "down_not_yet_at_bottom");
    Check(result.attached, "down_attached_before_bottom");
    result = Step(geometry, 900.0, 1);
    Near(result.y, 901.0, "down_bottom_exit_plus_one");
    Check(!result.attached && result.exitedBottom, "down_bottom_detaches");
}

void Stop() {
    const auto geometry = Rope(true);
    const auto result = Step(geometry, 500.0, 0);
    Near(result.y, 500.0, "stop_keeps_position");
    Check(result.attached, "stop_stays_attached");
}

void TopExit() {
    const auto geometry = Rope(true);
    auto result = Step(geometry, 104.0, -1);
    Near(result.y, 101.0, "top_exit_not_yet");
    Check(result.attached, "top_exit_attached_before_top");
    result = Step(geometry, 101.0, -1);
    Near(result.y, 95.0, "top_exit_top_minus_five");
    Check(!result.attached && result.exitedTop, "top_exit_detaches");
}

void TopClamp() {
    const auto geometry = Rope(false);
    auto result = Step(geometry, 101.0, -1);
    Near(result.y, 100.0, "top_clamp_to_top");
    Check(result.attached && result.clampedAtTop, "top_clamp_stays_attached");
    result = Step(geometry, 100.0, -1);
    Near(result.y, 100.0, "top_clamp_holds");
}

void Jump() {
    const auto geometry = Rope(true);
    const auto result = Step(geometry, 500.0, 0, 1, true);
    Check(result.jumped && !result.attached, "jump_detaches");
    Near(result.vx, 162.5, "jump_vx_speed_ratio_and_1_3");
    Near(result.vy, -277.5, "jump_vy_half_jump_speed");
    Near(result.y, 500.0, "jump_keeps_position_until_air_step");
    const auto left = Step(geometry, 500.0, 0, -1, true);
    Near(left.vx, -162.5, "jump_vx_follows_horizontal_input");
}

void JumpWithoutDirection() {
    const auto geometry = Rope(true);
    const auto result = Step(geometry, 500.0, 0, 0, true);
    Check(!result.jumped && result.jumpDropped && result.attached, "jump_without_direction_is_dropped");
    Near(result.y, 500.0, "dropped_jump_keeps_position");
}
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: v17_climb_contract <scenario> <physics-directory>\n";
        return 2;
    }
    Load(argv[2]);
    const std::string scenario = argv[1];
    if (scenario == "up")
        Up();
    else if (scenario == "down")
        Down();
    else if (scenario == "stop")
        Stop();
    else if (scenario == "top-exit")
        TopExit();
    else if (scenario == "top-clamp")
        TopClamp();
    else if (scenario == "jump")
        Jump();
    else if (scenario == "jump-no-direction")
        JumpWithoutDirection();
    else {
        std::cerr << "unknown scenario: " << scenario << '\n';
        return 2;
    }
    return 0;
}
