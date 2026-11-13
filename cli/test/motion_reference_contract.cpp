// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Gameplay/Physics/Physics.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

void Walk() {
    Check(ms::Physics::walk_reference_speed(0.0) == 0.0, "zero_force_has_no_walking_speed");
    for (const int speed : {80, 100, 140}) {
        // Effective force inputs follow Player::get_walkforce's float arithmetic.
        const double force = 0.05f + 0.11f * static_cast<float>(speed) / 100;
        const double reference = ms::Physics::walk_reference_speed(force);
        for (const int direction : {-1, 1}) {
            double velocity = 0.0;
            for (int step = 0; step < 1024; ++step) {
                // Independent update from the existing flat-ground drag law:
                // acceleration is input force minus 0.6 * (velocity / 3).
                const double acceleration = direction * force - 0.6 * (velocity / 3.0);
                const double next = velocity + acceleration;
                Check(direction * next >= direction * velocity, "walk_acceleration_is_monotonic_from_rest");
                Check(direction * next <= reference + 1e-12, "walk_does_not_overshoot_reference_from_rest");
                velocity = next;
                if (step == 9) Check(direction * velocity < reference - 1e-4, "reference_is_not_an_immediate_hard_cap");
            }
            Check(std::abs(direction * velocity - reference) < 1e-12,
                  "walk_reference_matches_independent_discrete_steady_state");
        }
        const double expected = speed == 80 ? 0.69 : speed == 100 ? 0.8 : 1.02;
        Check(std::abs(reference - expected) < 1e-7, "walk_reference_units_are_pixels_per_physics_step");
    }
}

void Jump() {
    Check(ms::Physics::jump_reference_height(0.0) == 0.0, "zero_impulse_has_no_jump_height");
    for (const int jump : {100, 123}) {
        // Effective impulse inputs follow Player::get_jumpforce's float arithmetic.
        const double impulse = 1.0f + 3.5f * static_cast<float>(jump) / 100;
        const double reference = ms::Physics::jump_reference_height(impulse);
        double y = 0.0;
        double apex = 0.0;
        double velocity = -impulse;
        for (int step = 0; step < 128; ++step) {
            // The grounded launch step moves by -impulse; only subsequent
            // airborne steps receive the existing +0.14 gravity acceleration.
            y += velocity;
            if (y < apex) apex = y;
            velocity += 0.14;
        }
        Check(std::abs(-apex - reference) < 1e-10, "jump_reference_matches_independent_discrete_apex");
        const double expected = jump == 100 ? 74.58 : 103.17;
        Check(std::abs(reference - expected) < 1e-5, "jump_reference_is_discrete_unrounded_map_pixel_height");
        Check(reference > impulse * impulse / (2.0 * 0.14) + 2.0,
              "continuous_ballistic_height_misses_grounded_launch_step");
    }

    for (const double impulse : {0.07, 0.14, 0.28, 0.42, 4.48}) {
        double height = 0.0;
        // Integrate only ascending steps, including an exact-apex zero step.
        for (double velocity = -impulse; velocity <= 0.0; velocity += 0.14) height -= velocity;
        Check(std::abs(ms::Physics::jump_reference_height(impulse) - height) < 1e-10,
              "jump_reference_handles_substep_and_integral_apex_boundaries");
    }
}
}

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "walk") {
        Walk();
    } else if (argc == 2 && std::string(argv[1]) == "jump") {
        Jump();
    } else {
        std::cerr << "expected walk or jump scenario\n";
        return 2;
    }
}
