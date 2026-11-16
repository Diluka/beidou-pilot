// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Gameplay/Combat/Bullet.h"
#include "Gameplay/MapleMap/Drop.h"
#include "Gameplay/MapleMap/MapObjects.h"
#include "Contract.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string>
#include <type_traits>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

void Near(double actual, double expected, const std::string& message) {
    Check(std::abs(actual - expected) < 1e-10, message);
}

// This fixture exercises the real dispatch/sampling wrapper, not a gameplay model.
class UpdateProbe final : public ms::MapObject {
public:
    explicit UpdateProbe(int id) : MapObject(id) { phobj.hspeed = 0.125; }

    void draw(double, double, float) const override {}

    int8_t update(const ms::Physics&) override {
        phobj.y += 0.25;
        phobj.y += 0.125;
        phobj.move(); // Overwrites Linear::last, which is not a full-update baseline.
        if (jump) set_position(900, 800);
        return phobj.fhlayer;
    }

    bool jump = false;
};

// Only the draw/resource boundary is omitted. Physics and Drop::update are real.
class FloatingDrop final : public ms::Drop {
public:
    FloatingDrop() : Drop(20, 0, {8, 30}, {8, 30}, 0, 2, false) {
        // FIXATED objects with a nonzero foothold do not query the map tree.
        // This is the actual native stationary-drop path, requiring no resource files.
        phobj.fhid = 1;
    }

    void draw(double, double, float) const override {}

    bool integrator_stationary() const { return phobj.hspeed == 0.0 && phobj.vspeed == 0.0; }

    double next_horizontal_speed() const { return phobj.hspeed; }

    void no_foothold() { phobj.onground = false; }
};

void Primitive() {
    ms::MovingObject object;
    object.set_x(10.125);
    object.set_y(20.25);
    object.hspeed = 0.125;
    Check(!object.get_motion().known, "new_native_lifetime_is_unknown");
    object.begin_motion_sample();
    object.move();
    object.end_motion_sample();
    Check(!object.get_motion().known, "first_update_is_not_fabricated_zero");
    object.begin_motion_sample();
    object.y += 0.25;
    object.y += 0.125;
    object.move();
    object.end_motion_sample();
    const auto sample = object.get_motion();
    Check(sample.known && sample.interval_ms == 8, "complete_update_has_8ms_interval");
    Near(sample.x, 10.375, "unrounded_position_is_retained");
    Near(sample.delta_x, 0.125, "subpixel_horizontal_displacement_is_retained");
    Near(sample.delta_y, 0.375, "all_direct_coordinate_writes_are_included");
    Near(object.y.get() - object.y.last(), 0.0, "linear_last_cannot_replace_the_update_sampler");
    object.hspeed = 0.0;
    object.begin_motion_sample();
    object.move();
    object.end_motion_sample();
    Check(object.get_motion().known, "measured_stationary_is_known");
    Near(object.get_motion().delta_x, 0.0, "measured_zero_is_not_unknown");
    Near(object.get_motion().delta_y, 0.0, "measured_vertical_zero_is_not_unknown");
    object.set_x(4000.25);
    Check(!object.get_motion().known, "explicit_reposition_invalidates_previous_sample");
    object.begin_motion_sample();
    object.move();
    object.end_motion_sample();
    Check(!object.get_motion().known, "first_update_after_reposition_stays_unknown");
    object.begin_motion_sample();
    object.move();
    object.end_motion_sample();
    Check(object.get_motion().known, "continuous_sampling_resumes_after_reposition");
    object.begin_motion_sample();
    object.set_y(5000.125);
    object.end_motion_sample();
    Check(!object.get_motion().known, "reposition_inside_update_is_not_charged_as_velocity");
}

void Wrapper() {
    ms::Physics physics;
    ms::MapObjects objects;
    auto probe = std::make_unique<UpdateProbe>(7);
    auto* native = probe.get();
    objects.add(std::move(probe));
    objects.update(physics);
    Check(!native->get_motion().known, "map_collection_dispatches_first_sample");
    objects.update(physics);
    Check(native->get_motion().known, "map_collection_calls_complete_update_wrapper");
    Near(native->get_motion().delta_x, 0.125, "collection_preserves_fractional_horizontal_motion");
    Near(native->get_motion().delta_y, 0.375, "wrapper_includes_post_integration_coordinate_writes");
    native->jump = true;
    objects.update(physics);
    Check(!native->get_motion().known, "mapobject_set_position_invalidates_inflight_sample");
    native->jump = false;
    objects.update(physics);
    Check(native->get_motion().known, "whole_update_after_internal_reposition_is_measurable");
    native->deactivate();
    Check(!native->get_motion().known, "inactive_entity_has_no_current_motion_sample");
    native->makeactive();
    objects.update(physics);
    Check(!native->get_motion().known, "reactivated_entity_starts_unknown");
    objects.remove(7);
    auto replacement = std::make_unique<UpdateProbe>(7);
    auto* fresh = replacement.get();
    objects.add(std::move(replacement));
    objects.update(physics);
    Check(!fresh->get_motion().known, "reused_oid_does_not_reuse_motion_history");
}

void Drop() {
    ms::Physics physics;
    ms::MapObjects objects;
    auto drop = std::make_unique<FloatingDrop>();
    auto* native = drop.get();
    objects.add(std::move(drop));
    objects.update(physics);
    Check(!native->get_motion().known, "actual_drop_first_sample_is_unknown");
    const auto first = native->get_motion();
    const auto rounded = native->get_position();
    objects.update(physics);
    const auto second = native->get_motion();
    Check(second.known && native->is_landed(), "landed_drop_still_has_measured_motion");
    Check(native->integrator_stationary(), "actual_drop_hover_does_not_change_integrator_velocity");
    Check(second.delta_y != 0.0, "actual_drop_hover_is_not_reported_as_zero_velocity");
    Near(second.delta_y, second.y - first.y, "sample_covers_the_entire_real_drop_update");
    Check(native->get_position() == rounded, "integer_position_would_hide_low_speed_hover");
    Near(second.delta_y, (std::cos(0.025) - 1.0) * 2.5, "real_drop_cosine_displacement_is_captured");
    native->expire(0, nullptr); // Real stationary fade path; not mode-2 pickup trajectory.
    objects.update(physics);
    Check(!native->is_landed() && native->get_motion().known, "pickup_fade_remains_a_current_entity");
    Near(native->get_motion().delta_y, 0.0, "real_stationary_fade_has_measured_zero");
    for (int step = 0; step < 64 && objects.contains(20); ++step) objects.update(physics);
    Check(!objects.contains(20), "real_drop_fade_returns_minus_one_and_removes_entity");
}

void PickupPhase() {
    ms::Physics physics;
    FloatingDrop drop;
    drop.sampled_update(physics);
    drop.sampled_update(physics);
    ms::PhysicsObject looter;
    looter.set_x(200.0);
    looter.set_y(0.0);
    // No map assets are loaded: exercise the airborne/no-foothold branch and
    // only assert the real update's horizontal sampling phase, not a map trajectory.
    drop.no_foothold();
    drop.expire(2, &looter);
    const auto before = drop.get_motion();
    drop.sampled_update(physics);
    const auto sample = drop.get_motion();
    Check(sample.known, "real_mode2_pickup_has_a_complete_update_sample");
    Near(sample.delta_x, sample.x - before.x, "real_pickup_sample_matches_completed_horizontal_displacement");
    Near(sample.delta_x, 0.0, "first_pickup_step_used_the_previous_horizontal_speed");
    Check(drop.next_horizontal_speed() > 0.0, "real_pickup_prepares_nonzero_speed_after_moving");
    Check(sample.delta_x != drop.next_horizontal_speed(), "next_step_speed_is_not_mislabeled_as_current_displacement");
}

void Bullet() {
    ms::Bullet bullet(ms::Animation{}, {0, 0}, false);
    const ms::Point<int16_t> target(400, -13);
    Check(!bullet.get_motion().known, "new_flight_is_unknown_without_inventing_an_identity");
    Check(!bullet.settarget(target), "test_target_is_not_immediate_arrival");
    bullet.update(target);
    Check(!bullet.get_motion().known, "first_real_bullet_update_is_unknown");
    const auto before = bullet.get_motion();
    bullet.update(target);
    const auto sample = bullet.get_motion();
    Check(sample.known && sample.interval_ms == 8, "actual_bullet_update_samples_its_own_movingobject");
    Near(sample.delta_x, sample.x - before.x, "bullet_horizontal_sample_matches_real_flight");
    Near(sample.delta_y, sample.y - before.y, "bullet_fractional_vertical_sample_matches_real_flight");
    Near(sample.delta_x, 6.0, "existing_bullet_integration_behavior_is_unchanged");
}

void Contract() {
    static_assert(std::is_base_of_v<MapleControl::MovableObject, MapleControl::Character>);
    static_assert(std::is_base_of_v<MapleControl::MovableObject, MapleControl::Monster>);
    static_assert(std::is_base_of_v<MapleControl::MovableObject, MapleControl::Drop>);
    static_assert(std::is_base_of_v<MapleControl::MovableObject, MapleControl::OtherPlayer>);
    static_assert(std::is_base_of_v<MapleControl::MovableObject, MapleControl::Npc>);
    static_assert(std::is_base_of_v<MapleControl::MovableObject, MapleControl::Projectile>);
    MapleControl::MovableObject object;
    object.SetPosition(12.125, -7.0625);
    Check(object.velocity.Document().Type() == MapleControl::Value::Kind::Null, "unknown_velocity_serializes_as_null");
    object.velocity.source = MapleControl::MotionVector::Source::NativeUpdateDelta;
    object.velocity.intervalMs = 8;
    object.velocity.x = 0.125 * 1000.0 / 8;
    const auto document = object.MotionDocument().Dump();
    Check(document.find("native_update_delta") != std::string::npos, "interval_mean_is_not_claimed_as_server_velocity");
    Check(document.find("\"interval_ms\":8") != std::string::npos, "sampling_interval_is_explicit");
    Check(document.find("15.625") != std::string::npos, "delta_converts_to_map_pixels_per_second");
}
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string scenario = argv[1];
    if (scenario == "primitive")
        Primitive();
    else if (scenario == "wrapper")
        Wrapper();
    else if (scenario == "drop")
        Drop();
    else if (scenario == "pickup-phase")
        PickupPhase();
    else if (scenario == "bullet")
        Bullet();
    else if (scenario == "contract")
        Contract();
    else
        return 2;
}
