// SPDX-License-Identifier: AGPL-3.0-or-later
// One whole 30ms displacement through real FootholdTree geometry: wall/edge
// limits, chain connections, slope following, air landing and ignore-foothold
// drop-through. Expected geometry is hand-computed from the fixture platforms.
#include "ImgResourceFile.h"
#include "Gameplay/Physics/FootholdTree.h"

#include <cmath>
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

void Near(double actual, double expected, const std::string& message) {
    if (std::abs(actual - expected) > 1e-6) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}

ms::FootholdTree Terrain(const char* directory) {
    const auto file = load_img_directory(directory);
    return ms::FootholdTree(file.root()["Test.img"]["foothold"]);
}

void CheckGround(const ms::LocalSweepResult& result, const std::string& prefix) {
    Check(result.onGround, prefix + "_on_ground");
    Check(!result.leftGround, prefix + "_not_left_ground");
}

void Flat(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    const auto platform = terrain.GetFoothold(1);
    Check(platform.valid && platform.slope == 0.0, "flat_platform_geometry");
    ms::LocalSweepInput input;
    input.x = 0.0;
    input.y = 1000.0;
    input.dx = 3.75;
    input.vx = 125.0;
    input.footholdId = 1;
    input.onGround = true;
    const auto result = terrain.SweepLocalMotion(input);
    CheckGround(result, "flat");
    Near(result.y, 1000.0, "flat_snaps_to_surface");
    Near(result.x, 3.75, "flat_keeps_target_x");
    Near(result.vx, 125.0, "flat_keeps_horizontal_speed");
    Check(result.footholdId == 1 && result.footholdLayer == 1, "flat_keeps_platform_identity");
    Check(!result.hitWall && !result.stoppedAtEdge, "flat_no_false_collision");
}

void Slope(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    const auto platform = terrain.GetFoothold(1);
    Near(platform.slope, -0.04, "slope_is_geometry");
    ms::LocalSweepInput input;
    input.x = 10.0;
    input.y = terrain.GroundBelow(10.0, platform);
    input.dx = 3.75;
    input.vx = 125.0;
    input.footholdId = 1;
    input.onGround = true;
    const auto result = terrain.SweepLocalMotion(input);
    CheckGround(result, "slope");
    Near(result.y, terrain.GroundBelow(13.75, platform), "slope_follows_surface");
    Check(std::abs(result.vy - result.vx * platform.slope) < 1e-6, "slope_velocity_is_tangent_projection");
}

void Wall(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    ms::LocalSweepInput input;
    input.x = 398.0;
    input.y = 1000.0;
    input.dx = 10.0;
    input.vx = 125.0;
    input.footholdId = 1;
    input.onGround = true;
    const auto result = terrain.SweepLocalMotion(input);
    Near(result.x, 400.0, "wall_limits_x");
    Near(result.vx, 0.0, "wall_stops_horizontal_speed");
    Check(result.hitWall, "wall_reports_collision");
    CheckGround(result, "wall");
}

void Edge(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    ms::LocalSweepInput input;
    input.x = 198.0;
    input.y = 1000.0;
    input.dx = 5.0;
    input.vx = 125.0;
    input.footholdId = 1;
    input.onGround = true;
    const auto result = terrain.SweepLocalMotion(input);
    Check(!result.onGround && result.leftGround, "walking_off_the_end_becomes_airborne");
    Check(result.footholdId == 0, "walking_off_the_end_detaches");
    Near(result.y, 1000.0, "walking_off_the_end_keeps_this_step_y");

    input.stopAtEdges = true;
    input.x = 198.0;
    const auto edge = terrain.SweepLocalMotion(input);
    Check(edge.stoppedAtEdge && edge.onGround, "rush_style_edge_stop");
    Near(edge.x, 200.0, "rush_style_edge_stop_x");
    Near(edge.vx, 0.0, "rush_style_edge_stop_speed");
}

void Chain(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    ms::LocalSweepInput input;
    input.x = 198.0;
    input.y = 1000.0;
    input.dx = 5.0;
    input.vx = 125.0;
    input.footholdId = 1;
    input.onGround = true;
    const auto result = terrain.SweepLocalMotion(input);
    CheckGround(result, "chain");
    Check(result.footholdId == 2, "chain_switches_to_next_segment");
    Near(result.y, 1000.0, "chain_flat_height");
}

void Landing(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    ms::LocalSweepInput input;
    input.x = 0.0;
    input.y = 900.0;
    input.dy = 150.0;
    input.vy = 670.0;
    const auto result = terrain.SweepLocalMotion(input);
    Check(result.landed && result.onGround, "air_lands_inside_the_step");
    Near(result.y, 1000.0, "landing_snaps_to_surface");
    Near(result.x, 0.0, "landing_keeps_vertical_drop_x");
    Near(result.vy, 0.0, "landing_flat_vertical_speed");
    Check(result.footholdId == 1, "landing_reports_platform");

    // No downward displacement means no landing scan.
    input.dy = 0.0;
    input.y = 990.0;
    const auto rising = terrain.SweepLocalMotion(input);
    Check(!rising.landed && !rising.onGround, "no_landing_without_downward_crossing");
}

void Earliest(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    ms::LocalSweepInput input;
    input.x = 0.0;
    input.y = 900.0;
    input.dy = 250.0;
    input.vy = 670.0;
    const auto result = terrain.SweepLocalMotion(input);
    Check(result.landed, "earliest_lands");
    Near(result.y, 1000.0, "earliest_crossing_wins");
    Check(result.footholdId == 1, "earliest_crossing_platform");

    input.ignoreFootholdId = 1;
    const auto skipped = terrain.SweepLocalMotion(input);
    Check(skipped.landed && skipped.footholdId == 2, "ignored_platform_is_skipped");
    Near(skipped.y, 1100.0, "ignored_platform_lands_lower");
}

void Queries(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    const auto hit = terrain.QueryGroundBelow(0.0, 950.0, 60.0);
    Check(hit.found && hit.footholdId == 1 && hit.groundY == 1000.0, "ground_query_finds_surface");
    Check(!terrain.QueryGroundBelow(0.0, 900.0, 60.0).found, "ground_query_respects_max_drop");
    Check(!terrain.QueryGroundBelow(500.0, 900.0, 600.0).found, "ground_query_respects_x_range");

    double groundbelow = 0.0;
    Check(terrain.JumpDownAvailable(0.0, 1000.0, groundbelow), "jump_down_available");
    Near(groundbelow, 1001.0, "jump_down_groundbelow");
    Check(!terrain.JumpDownAvailable(0.0, 1100.0, groundbelow), "jump_down_needs_lower_platform");
}

void Borders(const char* directory) {
    const ms::FootholdTree terrain = Terrain(directory);
    const auto borders = terrain.get_borders();
    ms::LocalSweepInput input;
    input.x = 0.0;
    input.y = 900.0;
    input.dy = 1000.0;
    input.vy = 670.0;
    const auto result = terrain.SweepLocalMotion(input);
    Near(result.y, borders.second(), "border_clamps_airborne_y");
    Check(result.vy == 0.0, "border_stops_vertical_speed");
}
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "scenario_and_directory_required\n";
        return 2;
    }
    const std::string scenario = argv[1];
    const char* directory = argv[2];
    if (scenario == "flat")
        Flat(directory);
    else if (scenario == "slope")
        Slope(directory);
    else if (scenario == "wall")
        Wall(directory);
    else if (scenario == "edge")
        Edge(directory);
    else if (scenario == "chain")
        Chain(directory);
    else if (scenario == "landing")
        Landing(directory);
    else if (scenario == "earliest")
        Earliest(directory);
    else if (scenario == "queries")
        Queries(directory);
    else if (scenario == "borders")
        Borders(directory);
    else {
        std::cerr << "unknown_scenario\n";
        return 2;
    }
    std::cout << "ok\n";
    return 0;
}
