// SPDX-License-Identifier: AGPL-3.0-or-later
// The ordinary local-character 30ms motion on real FootholdTree geometry.
// Expected sequences are #237's literal table and the GUI baseline measurements,
// not a second copy of the production integration.
#include "ImgResourceFile.h"
#include "Gameplay/Physics/FootholdTree.h"
#include "Gameplay/Physics/V17NormalMotion.h"
#include "Gameplay/Physics/V17PhysicsParameters.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {
constexpr double StepSeconds = 0.030;

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

void Sequence(const std::vector<double>& actual, const std::vector<double>& expected, const std::string& message) {
    Check(actual.size() == expected.size(), message + "_size");
    for (std::size_t index = 0; index < expected.size(); ++index) {
        if (std::abs(actual[index] - expected[index]) > 1e-6) {
            std::cerr << message << ": step=" << index << " actual=" << actual[index] << " expected=" << expected[index]
                      << '\n';
            std::exit(1);
        }
    }
}

void Load(const char* physicsDirectory, const char* mapDirectory, ms::FootholdTree& terrain) {
    auto physics = load_img_directory(physicsDirectory);
    ms::V17PhysicsParameters::Init(physics.root()["Physics.img"]);
    auto map = load_img_directory(mapDirectory);
    terrain = ms::FootholdTree(map.root()["Test.img"]["foothold"]);
}

struct Runner {
    const ms::FootholdTree& terrain;
    ms::V17MotionMultipliers multipliers;
    ms::V17NormalMotion motion;

    explicit Runner(const ms::FootholdTree& terrain) : terrain(terrain) {}

    ms::V17MotionStep Step(int direction, bool jumpDownAllowed = false) {
        ms::V17MotionInput input;
        input.direction = direction;
        return motion.Step(terrain, ms::V17PhysicsParameters::Get(), multipliers, input, jumpDownAllowed, StepSeconds);
    }
};

void Ground(const ms::FootholdTree& terrain) {
    Runner runner(terrain);
    runner.motion.Reset(0.0, 1000.0, true, 1);
    std::vector<double> speeds;
    std::vector<double> positions;
    for (int step = 0; step < 4; ++step) {
        const auto result = runner.Step(1);
        speeds.push_back(result.vx);
        positions.push_back(result.x);
        Near(result.y, 1000.0, "ground_flat_y");
        Check(result.onGround && result.footholdId == 1, "ground_stays_attached");
    }
    Sequence(speeds, {42.0, 84.0, 125.0, 125.0}, "ground_acceleration");
    Sequence(positions, {0.63, 2.52, 5.655, 9.405}, "ground_trapezoid_position");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(125.0, 0.0);
    speeds.clear();
    for (int step = 0; step < 6; ++step) speeds.push_back(runner.Step(0).vx);
    Sequence(speeds, {101.0, 77.0, 53.0, 29.0, 5.0, 0.0}, "release_brake_and_zero_crossing");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(125.0, 0.0);
    speeds.clear();
    for (int step = 0; step < 6; ++step) speeds.push_back(runner.Step(-1).vx);
    Sequence(speeds, {83.0, 41.0, -1.0, -43.0, -85.0, -125.0}, "reverse_input_uses_walk_force");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.multipliers.speedRatio = 0.8;
    speeds.clear();
    for (int step = 0; step < 3; ++step) speeds.push_back(runner.Step(1).vx);
    Sequence(speeds, {42.0, 84.0, 100.0}, "speed_ratio_80_caps_at_100");
    runner.multipliers.speedRatio = 1.4;
    runner.motion.Reset(0.0, 1000.0, true, 1);
    speeds.clear();
    for (int step = 0; step < 5; ++step) speeds.push_back(runner.Step(1).vx);
    Sequence(speeds, {42.0, 84.0, 126.0, 168.0, 175.0}, "speed_ratio_140_caps_at_175");
}

void Slope(const ms::FootholdTree& terrain) {
    Runner runner(terrain);
    const auto platform = terrain.GetFoothold(1);
    runner.motion.Reset(10.0, terrain.GroundBelow(10.0, platform), true, 1);
    ms::V17MotionStep result;
    for (int step = 0; step < 3; ++step) result = runner.Step(1);
    const double length = std::sqrt(1.0 + platform.slope * platform.slope);
    Near(result.vx, 125.0 / length, "slope_world_vx");
    Near(result.vy, 125.0 * platform.slope / length, "slope_world_vy");
    Near(result.y, terrain.GroundBelow(result.x, platform), "slope_follows_surface");
    Check(result.onGround, "slope_on_ground");
}

void Jump(const ms::FootholdTree& terrain) {
    Runner runner(terrain);

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.RequestJump();
    auto result = runner.Step(1);
    Check(result.jumped && !result.onGround, "direction_jump_leaves_ground");
    Near(result.vx, 100.0, "direction_jump_boost_from_rest");
    Near(result.vy, -495.0, "jump_first_sample_includes_gravity");
    Near(result.y, 983.25, "jump_first_step_relative_standing_foot_point");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.RequestJump();
    result = runner.Step(0);
    Near(result.vx, 0.0, "stationary_jump_keeps_zero_horizontal_speed");
    Near(result.vy, -495.0, "stationary_jump_vertical");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(20.0, 0.0);
    runner.motion.RequestJump();
    result = runner.Step(1);
    Near(result.vx, 120.0, "jump_boost_adds_to_existing_speed");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(110.0, 0.0);
    runner.motion.RequestJump();
    result = runner.Step(1);
    Near(result.vx, 110.0, "jump_boost_threshold_is_not_a_minimum");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(130.0, 0.0);
    runner.motion.RequestJump();
    result = runner.Step(1);
    Near(result.vx, 125.0, "jump_clamp_after_boost");

    // Leftward jump cases: a leftward run-up must keep its signed speed. The boost
    // adds in the input direction; it must never clamp the tangent speed magnitude
    // back to 0.8*Vmax or collapse negative motion (the dual-end comparison caught
    // that regression, so both directions stay in this contract).
    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(-125.0, 0.0);
    runner.motion.RequestJump();
    result = runner.Step(-1);
    Near(result.vx, -125.0, "left_jump_keeps_full_runup_speed");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.RequestJump();
    result = runner.Step(-1);
    Near(result.vx, -100.0, "left_jump_boost_from_rest");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(-20.0, 0.0);
    runner.motion.RequestJump();
    result = runner.Step(-1);
    Near(result.vx, -120.0, "left_jump_boost_adds_to_existing_speed");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(-110.0, 0.0);
    runner.motion.RequestJump();
    result = runner.Step(-1);
    Near(result.vx, -110.0, "left_jump_boost_threshold_is_not_a_minimum");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(-130.0, 0.0);
    runner.motion.RequestJump();
    result = runner.Step(-1);
    Near(result.vx, -125.0, "left_jump_clamp_after_boost");

    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.multipliers.jumpRatio = 1.23;
    runner.motion.RequestJump();
    result = runner.Step(0);
    Near(result.vy, -622.65, "jump_ratio_123_launch");
}

void Air(const ms::FootholdTree& terrain) {
    Runner runner(terrain);

    // Exact trapezoid sequence relative to the detached foot point.
    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.RequestJump();
    std::vector<double> relativeY;
    relativeY.push_back(runner.Step(0).y - 1000.0);
    for (int step = 0; step < 9; ++step) relativeY.push_back(runner.Step(0).y - 1000.0);
    const std::vector<double> expected = {-16.75, -30.70, -42.85, -53.20, -61.75,
                                          -68.50, -73.45, -76.60, -77.95, -77.50};
    Sequence(relativeY, expected, "jump_trapezoid_and_apex");

    // Air starts above a far platform so no landing interrupts the sequences.
    runner.motion.Reset(0.0, 900.0, false, 0);
    runner.motion.ApplyImpulse(100.0, -555.0);
    std::vector<double> reversed;
    for (int step = 0; step < 5; ++step) reversed.push_back(runner.Step(-1).vx);
    Sequence(reversed, {94.0, 88.0, 82.0, 76.0, 70.0}, "air_reverse_200px_s2");
    for (int step = 0; step < 14; ++step) reversed.push_back(runner.Step(-1).vx);
    Near(reversed.back(), -8.928571428571429, "air_reverse_stops_at_helper_limit");

    runner.motion.Reset(0.0, 900.0, false, 0);
    runner.motion.ApplyImpulse(100.0, -555.0);
    std::vector<double> released;
    for (int step = 0; step < 3; ++step) released.push_back(runner.Step(0).vx);
    Sequence(released, {99.97, 99.94, 99.91}, "air_release_1px_s2_drag");

    runner.motion.Reset(0.0, 0.0, false, 0);
    runner.motion.ApplyImpulse(0.0, 0.0);
    std::vector<double> falling;
    for (int step = 0; step < 14; ++step) falling.push_back(runner.Step(0).vy);
    Near(falling.back(), 670.0, "air_fall_speed_is_terminal");

    runner.motion.Reset(0.0, 0.0, false, 0);
    runner.motion.ApplyImpulse(0.0, 0.0);
    std::vector<double> gravity;
    for (int step = 0; step < 4; ++step) gravity.push_back(runner.Step(0).vy);
    Sequence(gravity, {60.0, 120.0, 180.0, 240.0}, "air_gravity_step");
}

void ImpulseWrite(const ms::FootholdTree& terrain) {
    // Ladder jump-off writes velocities and ends that update; the next update
    // integrates the air step (GUI samples 539 then 540).
    Runner runner(terrain);
    runner.motion.Reset(0.0, 1000.0, false, 0);
    runner.motion.ApplyImpulse(162.5, -277.5);
    runner.motion.CommitExternalWrite(30);
    Check(runner.motion.HasSample(), "written_state_is_a_committed_sample");
    const auto& written = runner.motion.LastStep();
    Near(written.x, 0.0, "written_state_keeps_position_x");
    Near(written.y, 1000.0, "written_state_keeps_position_y");
    Near(written.vx, 162.5, "written_state_reports_branch_vx");
    Near(written.vy, -277.5, "written_state_reports_branch_vy");
    Check(written.stepMs == 30, "written_state_uses_the_committed_step");

    const auto after = runner.Step(0);
    // GUI jump-off writes vx=162.5 and its first air step moves 4.875px; this
    // ordinary air model starts its tiny release drag on the same step (4.87455px).
    Near(after.x, 4.875, "first_air_step_x_is_trapezoid_from_written_vx", 1e-3);
    Near(after.y, 992.575, "first_air_step_y_is_trapezoid_from_written_vy");
    Near(after.vy, -217.5, "first_air_step_adds_one_gravity_step");
}

void HurtImpulse(const ms::FootholdTree& terrain) {
    // Original 0x7A6353 queue -> 0x9B222A consume: detach foothold, directional-limited
    // merge into world velocity, truncate toward zero (0xA62018), then air integration.
    Runner runner(terrain);
    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.QueueImpulse(-187.5, -437.5);
    auto result = runner.Step(0);
    Check(!result.onGround && result.footholdId == 0, "hurt_impulse_detaches_foothold");
    Check(result.leftGround && !result.landed, "hurt_impulse_records_ground_exit");
    Near(result.vy, -377.0, "hurt_impulse_truncates_vy_then_adds_gravity");
    Near(result.y, 987.79, "hurt_impulse_first_air_trapezoid_y", 1e-6);
    Check(result.vx > -188.0 && result.vx < -186.0, "hurt_impulse_keeps_negative_vx");

    // Directional limit cancels only up to zero; existing 125px/s becomes -75, not -200.
    runner.motion.Reset(0.0, 1000.0, true, 1);
    for (int step = 0; step < 3; ++step) runner.Step(1);
    runner.motion.QueueImpulse(-200.0, -200.0);
    result = runner.Step(0);
    Check(result.vx > -76.0 && result.vx < -74.0, "hurt_impulse_directional_merge_x");
    Near(result.vy, -140.0, "hurt_impulse_directional_merge_vy_truncated");

    // Larger same-direction speed is not reduced by a smaller impulse.
    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.ApplyImpulse(-300.0, 0.0);
    runner.motion.QueueImpulse(-200.0, 0.0);
    result = runner.Step(0);
    Check(result.vx > -301.0 && result.vx < -299.0, "hurt_impulse_does_not_weaken_larger_speed");

    // Two same-direction queue calls merge without stacking (-200 stays -200).
    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.QueueImpulse(-200.0, -200.0);
    runner.motion.QueueImpulse(-200.0, -200.0);
    result = runner.Step(0);
    Near(result.vy, -140.0, "hurt_impulse_queue_does_not_stack_same_direction");
    Check(result.vx > -201.0 && result.vx < -199.0, "hurt_impulse_queue_vx_kept");
}

void JumpDown(const ms::FootholdTree& terrain) {
    Runner runner(terrain);
    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.RequestJumpDown();
    auto result = runner.Step(0, true);
    Check(result.jumpedDown && !result.onGround, "down_jump_leaves_ground");
    Near(result.vy, -136.22213245, "down_jump_native_impulse_plus_first_gravity");
    Near(result.vx, 0.0, "down_jump_zero_horizontal");
    Near(result.y, 999.0 - 4.98666347175, "down_jump_first_step_position");

    bool landed = false;
    for (int step = 0; step < 20 && !landed; ++step) {
        result = runner.Step(0, true);
        landed = result.onGround;
    }
    Check(landed, "down_jump_lands_on_lower_platform");
    Near(result.y, 1100.0, "down_jump_drop_through_upper_platform");
    Check(result.footholdId == 2, "down_jump_ignores_departed_platform");
}

void NoLateJump(const ms::FootholdTree& terrain) {
    Runner runner(terrain);
    runner.motion.Reset(0.0, 1000.0, true, 1);
    runner.motion.RequestJump();
    runner.motion.ClearJumpRequests();
    const auto result = runner.Step(1);
    Check(!result.jumped, "withdrawn_jump_is_not_consumed_later");
    Near(result.vx, 42.0, "withdrawn_jump_leaves_ordinary_walk");
}
}

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "scenario_physics_map_required\n";
        return 2;
    }
    const std::string scenario = argv[1];
    ms::FootholdTree terrain;
    Load(argv[2], argv[3], terrain);
    const ms::V17MotionMultipliers baseline;
    if (scenario == "ground")
        Ground(terrain);
    else if (scenario == "slope")
        Slope(terrain);
    else if (scenario == "jump")
        Jump(terrain);
    else if (scenario == "air")
        Air(terrain);
    else if (scenario == "impulse-write")
        ImpulseWrite(terrain);
    else if (scenario == "hurt-impulse")
        HurtImpulse(terrain);
    else if (scenario == "jumpdown")
        JumpDown(terrain);
    else if (scenario == "no-late-jump")
        NoLateJump(terrain);
    else if (scenario == "reference") {
        Near(ms::V17NormalMotion::ReferenceWalkSpeed(ms::V17PhysicsParameters::Get(), baseline), 125.0,
             "reference_walk_speed");
        Near(ms::V17NormalMotion::ReferenceJumpHeight(ms::V17PhysicsParameters::Get(), baseline), 77.00625,
             "reference_jump_height");
        Near(ms::V17NormalMotion::ReferenceJumpHeight(ms::V17PhysicsParameters::Get(), baseline) * 2.0 / 2000.0,
             0.07700625, "reference_jump_height_matches_ballistic_model");
    } else {
        std::cerr << "unknown_scenario\n";
        return 2;
    }
    std::cout << "ok\n";
    return 0;
}
