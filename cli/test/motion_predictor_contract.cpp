// SPDX-License-Identifier: AGPL-3.0-or-later
// #243 pure ordinary-motion predictor: explicit state in, bounded 30ms steps,
// collision/landing out; no live character, world or input writes.
#include "ImgResourceFile.h"
#include "MotionPredictor.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {
using MapleControl::MotionPredictionInput;
using MapleControl::MotionPredictionLimits;
using MapleControl::MotionPredictionState;
using MapleControl::MotionPredictor;

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

struct Fixture {
    ms::FootholdTree terrain;
    ms::V17MotionMultipliers multipliers;
};

Fixture Load(const char* physicsDirectory, const char* mapDirectory) {
    auto physics = load_img_directory(physicsDirectory);
    ms::V17PhysicsParameters::Init(physics.root()["Physics.img"]);
    auto map = load_img_directory(mapDirectory);
    Fixture fixture{ms::FootholdTree(map.root()["Test.img"]["foothold"]), {}};
    return fixture;
}

MotionPredictionState Ground(const Fixture& fixture, double x, double y, std::uint16_t footholdId, double vx = 0.0) {
    MotionPredictionState state;
    state.x = x;
    state.y = y;
    state.vx = vx;
    state.vy = 0.0;
    state.onGround = true;
    state.footholdId = footholdId;
    return state;
}

void GroundSequence(const Fixture& fixture) {
    MotionPredictor predictor(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    std::string error;
    Check(predictor.Reset(Ground(fixture, 0.0, 1000.0, 1), error), error);
    Check(predictor.Ready(), "predictor_ready");
    const auto start = predictor.State();
    Near(start.vx, 0.0, "initial_vx");
    MotionPredictionInput input;
    input.direction = 1;
    const std::vector<double> speeds{42.0, 84.0, 125.0, 125.0};
    const std::vector<double> positions{0.63, 2.52, 5.655, 9.405};
    for (std::size_t index = 0; index < speeds.size(); ++index) {
        const auto step = predictor.Step(input);
        Check(step.progressed, "ground_step_progressed");
        Near(step.stepMs, 30.0, "ground_step_ms");
        Near(step.before.x, index == 0 ? 0.0 : positions[index - 1], "ground_before_x");
        Near(step.after.x, positions[index], "ground_x");
        Near(step.after.vx, speeds[index], "ground_vx");
        Near(step.after.vx, predictor.State().vx, "predictor_state_tracks_step");
        Check(step.after.onGround && step.after.footholdId == 1, "ground_collision_state");
        Check(!step.jumped && !step.landed && !step.leftGround, "ground_events");
    }
    Near(predictor.State().y, 1000.0, "ground_y");

    MotionPredictor repeated(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    Check(repeated.Reset(Ground(fixture, 0.0, 1000.0, 1, 125.0), error), error);
    input.direction = 0;
    const std::vector<double> braking{101.0, 77.0, 53.0, 29.0, 5.0, 0.0};
    for (const double speed : braking) {
        const auto step = repeated.Step(input);
        Check(step.progressed, "brake_step_progressed");
        Near(step.after.vx, speed, "brake_vx");
    }
    Near(repeated.State().vx, 0.0, "brake_stops");

    // Bounded advance must equal the same deterministic step sequence.
    MotionPredictor direct(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    MotionPredictor batched(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    Check(direct.Reset(Ground(fixture, 0.0, 1000.0, 1), error), error);
    Check(batched.Reset(Ground(fixture, 0.0, 1000.0, 1), error), error);
    MotionPredictionInput right;
    right.direction = 1;
    MotionPredictionLimits limits;
    limits.maxSteps = 3;
    const auto advance = batched.Advance(right, limits);
    Check(advance.progressed && advance.steps == 3 && advance.stoppedByLimit, "bounded_advance_limit");
    for (int index = 0; index < 3; ++index) direct.Step(right);
    Near(direct.State().x, batched.State().x, "bounded_advance_matches_steps");
    Near(direct.State().vx, batched.State().vx, "bounded_advance_matches_speed");

    // Copies are independent branches.
    auto branch = batched;
    MotionPredictionInput left;
    left.direction = -1;
    branch.Step(left);
    Near(batched.State().vx, 125.0, "copy_branch_keeps_original");
    Near(branch.State().vx, 83.0, "copy_branch_diverges");
}

void JumpAndLanding(const Fixture& fixture) {
    MotionPredictor predictor(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    std::string error;
    Check(predictor.Reset(Ground(fixture, 0.0, 1000.0, 1), error), error);
    MotionPredictionInput jump;
    jump.direction = 1;
    jump.jump = true;
    const auto first = predictor.Step(jump);
    Check(first.progressed && first.jumped, "jump_event");
    Check(first.leftGround && !first.after.onGround, "jump_leaves_ground");
    Near(first.after.vx, 100.0, "jump_horizontal_boost");
    Near(first.after.vy, -495.0, "jump_first_vy");
    Near(first.after.y, 983.25, "jump_first_y");
    // A withdrawn jump is not consumed by the next step.
    MotionPredictionInput noInput;
    const auto second = predictor.Step(noInput);
    Check(second.progressed && !second.jumped && !second.after.onGround, "jump_edge_not_replayed");
    Near(second.after.vy, -435.0, "jump_gravity_second");

    MotionPredictionState air;
    air.x = 0.0;
    air.y = 900.0;
    air.onGround = false;
    MotionPredictor falling(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    Check(falling.Reset(air, error), error);
    MotionPredictionInput idle;
    MotionPredictionLimits limits;
    limits.maxSteps = 120;
    limits.stopOnLanded = true;
    const auto landing = falling.Advance(idle, limits);
    Check(landing.progressed && landing.stoppedByCondition, "air_landing_stops_on_land");
    Check(landing.last.landed, "air_landing_event");
    Check(landing.last.after.onGround && landing.last.after.footholdId == 1, "air_landing_ground_state");
    Check(landing.last.after.y <= 1000.0 && landing.last.after.y > 990.0, "air_landing_surface");
}

void WallAndUnsupported(const Fixture& fixture) {
    MotionPredictor predictor(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    std::string error;
    Check(predictor.Reset(Ground(fixture, 390.0, 1000.0, 1, 125.0), error), error);
    MotionPredictionInput right;
    right.direction = 1;
    bool hit = false;
    for (int index = 0; index < 3; ++index) {
        const auto step = predictor.Step(right);
        Check(step.progressed, "wall_step_progressed");
        if (step.hitWall) hit = true;
    }
    Check(hit, "wall_event");
    Near(predictor.State().x, 400.0, "wall_x_limit");
    Near(predictor.State().vx, 0.0, "wall_speed_zero");

    auto unknown = Ground(fixture, 0.0, 1000.0, 0);
    MotionPredictor rejected(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    Check(!rejected.Reset(unknown, error), "unknown_foothold_is_unsupported");
    Check(error == "motion_state_foothold_unknown", "unknown_foothold_error");

    MotionPredictionState invalid = Ground(fixture, 0.0, 1000.0, 1);
    invalid.x = std::nan("");
    Check(!rejected.Reset(invalid, error), "nan_state_is_unsupported");
    Check(error == "motion_state_invalid", "nan_state_error");

    MotionPredictionInput downJump;
    downJump.jumpDown = true;
    downJump.jumpDownAllowed = false;
    MotionPredictor unset(fixture.terrain, ms::V17PhysicsParameters::Get(), fixture.multipliers);
    const auto before = unset.Step(right);
    Check(!before.progressed, "unset_predictor_does_not_step");
    Check(predictor.Reset(Ground(fixture, 0.0, 1000.0, 1), error), error);
    const auto rejectedStep = predictor.Step(downJump);
    Check(!rejectedStep.progressed, "down_jump_without_grant_is_unsupported");
    Near(predictor.State().x, 0.0, "rejected_step_keeps_state");
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: motion_predictor_contract SCENARIO PHYSICS_DIR MAP_DIR\n";
        return 2;
    }
    const auto fixture = Load(argv[2], argv[3]);
    const std::string scenario = argv[1];
    if (scenario == "ground")
        GroundSequence(fixture);
    else if (scenario == "jump-landing")
        JumpAndLanding(fixture);
    else if (scenario == "wall-unsupported")
        WallAndUnsupported(fixture);
    else {
        std::cerr << "unknown scenario: " << scenario << '\n';
        return 2;
    }
    std::cout << "ok\n";
    return 0;
}
