// SPDX-License-Identifier: AGPL-3.0-or-later
// Offline fixture: private access only seeds an empty native stage and reads its
// real adapter/counters. No production test mode, asset files, sockets or account.
#include <bits/stdc++.h>
#include "ImgResourceFile.h"
#include "Gameplay/Physics/V17PhysicsParameters.h"
#include <nlohmann/json.hpp>
#define private public
#include "SharedLuaAdapter.h"
#include "Gameplay/Stage.h"
#include "Net/Session.h"
#include "Net/OutPacket.h"
#include "HeadlessState.h"
#undef private

namespace {
constexpr int SkillA = 1001001;
constexpr int SkillB = 1001002;
constexpr int NoActionSkill = 1001003;
constexpr int PotionA = 2000000;
constexpr int PotionB = 2000001;
std::vector<std::vector<int8_t>> packets;

void Check(bool value, const std::string& message) {
    if (!value) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

std::size_t PacketCount(int opcode) {
    return std::count_if(packets.begin(), packets.end(), [opcode](const auto& bytes) {
        return bytes.size() >= 2 && (static_cast<uint8_t>(bytes[0]) | (static_cast<uint8_t>(bytes[1]) << 8)) == opcode;
    });
}

std::vector<std::vector<int8_t>> PacketsOf(int opcode) {
    std::vector<std::vector<int8_t>> found;
    for (const auto& bytes : packets)
        if (bytes.size() >= 2 && (static_cast<uint8_t>(bytes[0]) | (static_cast<uint8_t>(bytes[1]) << 8)) == opcode)
            found.push_back(bytes);
    return found;
}

MapleControl::Action Attack(int skill = 0) {
    MapleControl::Action action;
    action.kind = MapleControl::ActionKind::Attack;
    action.skillId = skill;
    action.sessionId = "native-contract";
    return action;
}

MapleControl::Action Item(int id) {
    MapleControl::Action action;
    action.kind = MapleControl::ActionKind::UseItem;
    action.itemId = id;
    action.sessionId = "native-contract";
    return action;
}

void Prepare(SharedLuaAdapter& host) {
    auto& stage = ms::Stage::get();
    ms::CharEntry entry{};
    entry.id = 1;
    entry.stats.name = "offline-contract";
    entry.stats.stats[ms::MapleStat::LEVEL] = 10;
    entry.stats.stats[ms::MapleStat::HP] = 50;
    entry.stats.stats[ms::MapleStat::MAXHP] = 50;
    entry.stats.stats[ms::MapleStat::MP] = 50;
    entry.stats.stats[ms::MapleStat::MAXMP] = 50;
    entry.look.equips[ms::EquipSlot::WEAPON] = 1302000;
    stage.loadplayer(entry);
    stage.state = ms::Stage::ACTIVE;
    auto& player = stage.get_player();
    player.get_skills().set_skill(SkillA, 1, 1, 0);
    player.get_skills().set_skill(SkillB, 1, 1, 0);
    player.get_skills().set_skill(NoActionSkill, 1, 1, 0);
    player.get_inventory().add_item(ms::InventoryType::USE, 1, PotionA, false, 0, 10, "", 0);
    player.get_inventory().add_item(ms::InventoryType::USE, 2, PotionB, false, 0, 10, "", 0);
    player.get_phobj().onground = true;
    ms::headless_state().in_game = true;
    host.Capture();
    Check(host.Observe().ready, "fixture_is_ready_without_a_network_or_resource_file");
    Check(player.can_attack(), "actual_player_native_admission_has_a_weapon");
}

void Consume(SharedLuaAdapter& host, std::uint64_t tick) {
    ms::Stage::get().update();
    host.Tick(tick);
}

void FinishAnimation() {
    auto& player = ms::Stage::get().get_player();
    ms::Physics physics;
    for (int i = 0; i < 250 && player.is_attacking(); ++i) player.update(physics);
    Check(!player.is_attacking(), "real_player_update_completes_the_native_animation");
}

void Keys(SharedLuaAdapter& host) {
    auto& adapter = host.tickAdapter;
    auto& player = ms::Stage::get().get_player();
    std::string error;
    Check(adapter.SetHeldKeys({"right"}, error), error);
    auto jump = Attack();
    jump.kind = MapleControl::ActionKind::Jump;
    Check(adapter.SetActionIntent(jump, error), error);
    Check(player.is_key_down(ms::KeyAction::RIGHT) && player.is_key_down(ms::KeyAction::JUMP), "real_native_down_keys");
    Check(player.get_motion_state().HasPendingJump(), "jump_keydown_records_a_motion_edge");
    Check(!adapter.HeldKeysSettled() && !adapter.ActionIntentSettled(), "move_and_jump_wait_for_the_real_motion_layer");

    // Three world ticks do not reach a 30ms commit; the fourth does. The empty
    // fixture stage has no foothold, so the recorded jump edge cannot launch and is
    // dropped at the commit instead of being queued for later.
    for (std::uint64_t tick = 1; tick <= 3; ++tick) {
        Consume(host, tick);
        Check(!adapter.HeldKeysSettled() && !adapter.ActionIntentSettled(),
              "world_ticks_without_a_commit_do_not_settle_movement_or_jump");
    }
    Consume(host, 4);
    Check(adapter.HeldKeysSettled(), "movement_settles_on_the_real_motion_commit");
    Check(!player.get_motion_state().HasPendingJump(), "jump_edge_is_consumed_or_dropped_at_the_commit");
    Consume(host, 5);
    Check(adapter.ActionIntentSettled() && !adapter.Released(), "a_still_held_jump_intent_can_be_settled");
    Check(adapter.Result().dispatched && adapter.Result().reason == "native_jump_input_consumed",
          "jump_reports_confirmed_native_input_not_a_fabricated_game_effect");
    const auto edges = host.inputEvents;
    for (std::uint64_t tick = 6; tick <= 20; ++tick) {
        Check(adapter.SetActionIntent(jump, error), error);
        Consume(host, tick);
    }
    Check(host.inputEvents == edges, "same_hold_never_replays_jump_down");

    adapter.ReleaseAction();
    Check(!player.is_key_down(ms::KeyAction::JUMP) && player.is_key_down(ms::KeyAction::RIGHT),
          "action_withdrawal_keeps_direction");
    Check(adapter.ActionIntentSettled() && !adapter.ReleasePending() && adapter.Released(),
          "key_up_is_confirmed_immediately_by_the_native_release_path");

    Check(adapter.SetActionIntent(Attack(), error), error);
    const auto attackEdges = host.inputEvents;
    for (int i = 0; i < 20; ++i) Check(adapter.SetActionIntent(Attack(), error), error);
    Check(host.inputEvents == attackEdges && player.is_key_down(ms::KeyAction::ATTACK),
          "ordinary_attack_remains_a_native_hold");
    Consume(host, 22);
    Check(ms::Stage::get().get_combat().get_move_sequence() == 1 && adapter.ActiveAction(),
          "stage_update_consumes_ordinary_attack_without_another_lua_call");
    FinishAnimation();
    Consume(host, 23);
    Check(ms::Stage::get().get_combat().get_move_sequence() == 2 && host.inputEvents == attackEdges,
          "native_ordinary_attack_repeats_after_animation_without_replaying_down");
    MapleControl::Action pickup;
    pickup.kind = MapleControl::ActionKind::Pickup;
    Check(adapter.SetActionIntent(pickup, error), error);
    Check(!player.is_key_down(ms::KeyAction::ATTACK) && player.is_key_down(ms::KeyAction::PICKUP),
          "replacement_releases_old_key_before_current_key");
    adapter.Advance(24, false);
    Check(adapter.Result().dispatched && adapter.Result().reason == "native_pickup_input_consumed",
          "pickup_reports_confirmed_key_input_without_claiming_loot");
    adapter.Release();
    Check(!player.is_key_down(ms::KeyAction::PICKUP) && !player.is_key_down(ms::KeyAction::RIGHT),
          "stop_releases_action_and_movement");
    adapter.Advance(25, false);
    Check(adapter.Released() && adapter.HeldKeysSettled(), "all_releases_are_confirmed");
    Check(adapter.SetHeldKeys({"left"}, error), error);
    adapter.Release();
    Check(!player.is_key_down(ms::KeyAction::LEFT), "stop_also_releases_direction_when_action_was_already_empty");
}

void Skills(SharedLuaAdapter& host) {
    auto& adapter = host.tickAdapter;
    auto& player = ms::Stage::get().get_player();
    auto& combat = ms::Stage::get().get_combat();
    std::string error;
    player.get_stats().set_stat(ms::MapleStat::MP, 0);
    Check(adapter.SetActionIntent(Attack(SkillA), error), "skill_intent_admitted_before_native_use_admission");
    Consume(host, 1);
    Check(combat.get_move_sequence() == 0 && adapter.ActiveAction() == nullptr, "real_can_use_blocks_mp_starved_skill");
    player.get_stats().set_stat(ms::MapleStat::MP, 50);
    player.add_cooldown(SkillA, 1000);
    combat.update_held_move();
    Check(combat.get_move_sequence() == 0, "real_native_skill_cooldown_blocks_a_valid_hold");
    player.add_cooldown(SkillA, 0);
    Consume(host, 2);
    Check(combat.get_move_sequence() == 1 && player.is_attacking(),
          "native_consumer_starts_admitted_skill_without_shortcut");
    Check(adapter.ActiveAction() && adapter.ActiveAction()->skillId == SkillA, "current_action_reports_actual_a");
    Check(adapter.SetActionIntent(Attack(SkillB), error), "intent_b_replaces_a_even_while_a_is_active");
    Check(adapter.ActiveAction()->skillId == SkillA, "desired_b_does_not_rename_a");
    Consume(host, 3);
    Check(combat.get_move_sequence() == 1 && adapter.ActionIntentSettled(),
          "a_blocks_b_dispatch_but_not_input_confirmation");
    adapter.ReleaseAction();
    Check(adapter.ActiveAction()->skillId == SkillA, "clear_does_not_interrupt_or_hide_native_a");
    Consume(host, 4);
    Check(adapter.Released() && adapter.ActiveAction()->skillId == SkillA,
          "release_confirmation_is_independent_of_animation");
    FinishAnimation();
    Consume(host, 5);
    Check(combat.get_move_sequence() == 1 && adapter.ActiveAction() == nullptr,
          "withdrawn_b_is_not_a_historical_pending_dispatch");
    Check(adapter.SetActionIntent(Attack(SkillA), error), error);
    Consume(host, 6);
    Check(adapter.SetActionIntent(Attack(SkillB), error), error);
    Check(adapter.ActiveAction()->skillId == SkillA, "still_valid_b_waits_for_actual_a_completion");
    FinishAnimation();
    Consume(host, 7);
    Check(combat.get_move_sequence() == 3 && adapter.ActiveAction()->skillId == SkillB,
          "current_valid_b_starts_after_native_admission");
    for (int i = 0; i < 10; ++i) combat.update_held_move();
    Check(player.is_attacking() && combat.get_move_sequence() == 3,
          "held_skill_never_restarts_an_incomplete_native_animation");
    FinishAnimation();
    Consume(host, 8);
    Check(combat.get_move_sequence() == 4, "unchanged_held_skill_repeats_after_real_animation_completion");
    adapter.ReleaseAction();
    FinishAnimation();
    Consume(host, 9);
    Check(combat.get_move_sequence() == 4, "cancelled_skill_never_repeats");
}

void NoAction(SharedLuaAdapter& host) {
    auto& adapter = host.tickAdapter;
    auto& combat = ms::Stage::get().get_combat();
    std::string error;
    Check(adapter.SetActionIntent(Attack(NoActionSkill), error), error);
    for (int i = 0; i < 100; ++i) {
        Check(adapter.SetActionIntent(Attack(NoActionSkill), error), error);
        Consume(host, i + 1);
    }
    Check(combat.get_move_sequence() == 1 && PacketCount(ms::OutPacket::USE_SKILL) == 1,
          "successful_no_action_skill_is_consumed_once_per_uninterrupted_hold");
    Check(adapter.ActiveAction() == nullptr && host.Observe().actionIdle == MapleControl::Fact::True,
          "a_no_action_skill_does_not_fabricate_a_busy_animation");
    adapter.ReleaseAction();
    Check(adapter.SetActionIntent(Attack(NoActionSkill), error), error);
    Consume(host, 101);
    Check(combat.get_move_sequence() == 2, "a_genuine_release_then_down_rearms_no_action_skill");
}

void Potions(SharedLuaAdapter& host) {
    auto& adapter = host.tickAdapter;
    auto& player = ms::Stage::get().get_player();
    using Clock = std::chrono::steady_clock;
    const auto start = Clock::time_point{} + std::chrono::seconds(1);
    std::string error;
    Check(adapter.SetHeldKeys({"right"}, error), error);
    Check(adapter.SetActionIntent(Item(PotionA), error), error);
    player.update_held_item(start);
    adapter.Advance(1, false);
    Check(adapter.Result().dispatched && adapter.Result().reason == "item_use_requested"
              && adapter.Result().effect == "unknown",
          "potion_result_uses_a_real_request_counter_not_a_claimed_hp_effect");
    Check(PacketCount(ms::OutPacket::USE_ITEM) == 1, "first_held_potion_is_native_dispatched");
    Check(adapter.SetActionIntent(Item(PotionB), error), error);
    player.update_held_item(start + std::chrono::milliseconds(50));
    adapter.ReleaseAction();
    Check(adapter.SetActionIntent(Item(PotionA), error), error);
    player.update_held_item(start + std::chrono::milliseconds(99));
    Check(PacketCount(ms::OutPacket::USE_ITEM) == 1, "replacement_and_clear_cannot_bypass_potion_only_100ms_guard");
    player.update_held_item(start + std::chrono::milliseconds(100));
    Check(PacketCount(ms::OutPacket::USE_ITEM) == 2, "held_potion_repeats_at_its_own_guard_not_lua_frequency");
    Check(player.is_key_down(ms::KeyAction::RIGHT), "potion_does_not_pause_native_direction");
    adapter.ReleaseAction();
    player.update_held_item(start + std::chrono::seconds(2));
    Check(PacketCount(ms::OutPacket::USE_ITEM) == 2, "cleared_potion_never_dispatches_later");
    Check(adapter.SetActionIntent(Attack(NoActionSkill), error), error);
    Consume(host, 1);
    Check(PacketCount(ms::OutPacket::USE_SKILL) == 1, "potion_guard_never_delays_an_independent_skill");
}

void Provenance(SharedLuaAdapter& host) {
    auto& adapter = host.tickAdapter;
    auto& combat = ms::Stage::get().get_combat();
    std::string error;
    Check(adapter.SetActionIntent(Attack(SkillA), error), error);
    Check(combat.use_move(SkillA) == ms::SpecialMove::FBR_NONE, "direct_native_move_starts");
    host.Capture();
    adapter.Advance(1, false);
    Check(adapter.ActiveAction() && adapter.ActiveAction()->skillId == SkillA
              && adapter.ActiveAction()->sessionId.empty() && !adapter.Result().dispatched,
          "matching_direct_skill_is_a_global_action_but_not_this_tick_request");
    adapter.ReleaseAction();
    FinishAnimation();
    adapter.Advance(2, false);

    // Only the action this tick owner actually started carries its session.
    Check(adapter.SetActionIntent(Attack(SkillB), error), error);
    Consume(host, 3);
    Check(adapter.Result().dispatched && adapter.ActiveAction()
              && adapter.ActiveAction()->sessionId == "native-contract",
          "native_consumer_starts_the_current_tick_held_skill");
    adapter.ReleaseAction();
    FinishAnimation();
    adapter.Advance(4, false);
}

void Lifecycle(SharedLuaAdapter& host) {
    auto& adapter = host.tickAdapter;
    auto& player = ms::Stage::get().get_player();
    auto& combat = ms::Stage::get().get_combat();
    std::string error;
    player.get_phobj().onground = false;
    player.get_phobj().hspeed = 1.5;
    host.Capture();
    Check(host.Observe().actionIdle == MapleControl::Fact::True && host.Observe().settled == MapleControl::Fact::False,
          "native_action_idle_is_true_while_physically_unsettled");
    Check(adapter.SetHeldKeys({"left"}, error), error);
    Check(adapter.SetActionIntent(Attack(SkillA), error), error);
    Consume(host, 2);
    Check(host.Observe().actionIdle == MapleControl::Fact::False, "native_animation_has_real_busy_fact");
    adapter.Advance(3, true);
    Check(adapter.Keys().empty(), "scene_transition_clears_all_owned_keys");
    FinishAnimation();
    Consume(host, 4);
    Check(combat.get_move_sequence() == 1 && adapter.Released(), "scene_transition_clears_semantic_skill_hold");
    Check(adapter.SetActionIntent(Item(PotionA), error), error);
    ms::Stage::get().stop_actions();
    player.update_held_item(std::chrono::steady_clock::now());
    Check(PacketCount(ms::OutPacket::USE_ITEM) == 0, "native_stage_stop_clears_potion_even_before_lua_observation");
    adapter.Shutdown();
    Check(adapter.Keys().empty() && adapter.Released(), "shutdown_releases_owned_input");
    ms::headless_state().in_game = false;
    host.Capture();
    Check(host.Observe().actionIdle == MapleControl::Fact::Unknown,
          "unavailable_player_has_unknown_not_fabricated_idle");
}
}

void physics_pose_shape(const MapleControl::State& state, bool known) {
    Check(state.character.physics.known == known, "pose sample existence is explicit");
    Check(state.character.physics.updateIdKnown, "ready local player exposes a motion commit identity");
}

void Physics(SharedLuaAdapter& host) {
    auto& player = ms::Stage::get().get_player();
    auto& phobj = player.get_phobj();
    if (player.is_climbing()) player.set_state(ms::Char::State::STAND);
    phobj.onground = true;

    // A freshly loaded player has no motion commit yet: the whole pose stays unknown
    // instead of reusing the constructor position as a physical sample.
    host.Capture();
    physics_pose_shape(host.Observe(), false);

    // Four world ticks commit one ordinary 30ms step.
    for (int tick = 0; tick < 4; ++tick) ms::Stage::get().update();
    host.Capture();
    const auto& state = host.Observe();
    physics_pose_shape(state, true);
    const std::uint64_t updateId = player.get_motion_commit_id();
    Check(state.character.physics.updateId == updateId, "physics update id is the real motion commit number");
    Check(state.character.physics.stepMsKnown && state.character.physics.stepMs == 30,
          "ordinary motion reports the real simulated step, not a publish interval");
    const auto& step = player.get_motion_state().LastStep();
    Check(state.character.physics.positionKnown && state.character.physics.x == step.x
              && state.character.physics.y == step.y,
          "physics point is the unrounded same-step physical foot point");
    Check(state.character.physics.velocityKnown && state.character.physics.velocityX == step.vx
              && state.character.physics.velocityY == step.vy,
          "physics velocity is the same-step world instantaneous speed");
    Check(state.character.physics.Document().Dump().find("native_update_delta") == std::string::npos,
          "physics velocity is not the old interval-mean vector");

    // The bridge state and the character observation domain read one record.
    const auto document = host.StateDocument();
    const auto& character = document["character"];
    Check(character["physics"]["update_id"] == updateId, "bridge state exposes the same commit identity");
    Check(document["character_updates"] == updateId, "old character_updates aliases the real motion commit");
    Check(character["physics"]["step_ms"] == 30, "bridge state exposes the real step time");
    Check(character["physics"]["velocity"]["x"] == step.vx, "bridge state exposes the canonical velocity");
    const auto observed = host.ObserveDomain("character");
    Check(observed.status == "ok" && observed.data.Dump().find("\"physics\":{") != std::string::npos,
          "character observation domain exposes the same whole record");

    // A legacy attached mode commits on the 8ms clock and keeps instantaneous
    // velocity unknown; the motion record and identity rotate with that commit.
    player.set_state(ms::Char::State::LADDER);
    host.Capture();
    Check(!host.Observe().character.physics.stepMsKnown, "a suspended ownership has no current motion sample");
    ms::Stage::get().update();
    host.Capture();
    Check(host.Observe().character.physics.known && host.Observe().character.physics.stepMs == 8,
          "legacy mode reports its own 8ms step");
    Check(host.Observe().character.physics.updateId == player.get_motion_commit_id(),
          "legacy step keeps the real commit identity");
    Check(host.Observe().character.physics.positionKnown && !host.Observe().character.physics.velocityKnown,
          "legacy per-step motion keeps instantaneous velocity unknown");

    // Sitting has no motion owner at all until motion resumes.
    player.set_state(ms::Char::State::SIT);
    host.Capture();
    Check(!host.Observe().character.physics.known, "static mode has no fabricated motion sample");
    player.set_state(ms::Char::State::STAND);

    // Without a ready local player there is no physics sample at all.
    ms::headless_state().in_game = false;
    host.Capture();
    Check(!host.Observe().character.physics.known
              && host.Observe().character.physics.Document().Type() == MapleControl::Value::Kind::Null,
          "not-ready local player has no fabricated physics record");
    ms::headless_state().in_game = true;
}

void Ground(SharedLuaAdapter& host, const char* mapDirectory) {
    auto map = load_img_directory(mapDirectory);
    auto& stage = ms::Stage::get();
    stage.physics = ms::Physics(map.root()["Test.img"]["foothold"]);
    auto& player = stage.get_player();
    auto& adapter = host.tickAdapter;

    player.respawn(ms::Point<int16_t>(0, 1000), false);
    for (std::uint64_t tick = 1; tick <= 4; ++tick) Consume(host, tick);
    Check(player.get_phobj().onground, "respawn_attaches_to_the_platform");
    Check(std::abs(player.get_phobj().crnt_y() - 1000.0) < 1e-9, "respawn_foot_point_is_the_surface");

    std::string error;
    Check(adapter.SetHeldKeys({"right"}, error), error);
    std::vector<double> speeds;
    for (std::uint64_t tick = 5; tick <= 16; ++tick) {
        const auto before = player.get_motion_commit_id();
        Consume(host, tick);
        if (player.get_motion_commit_id() != before) speeds.push_back(player.get_motion_state().LastStep().vx);
    }
    const std::vector<double> walk = {42.0, 84.0, 125.0};
    Check(speeds == walk, "ground_walk_uses_real_30ms_commits");
    Check(player.get_phobj().crnt_x() > 4.0, "ground_walk_moves_the_character");
    Check(std::abs(player.get_phobj().hspeed - 1.0) < 1e-9, "animation_projection_uses_per_8ms_units_not_px_s");
    const auto sample = player.get_motion();
    Check(sample.known && sample.interval_ms == 30 && sample.delta_x > 0.0,
          "player_interval_mean_covers_the_real_30ms_commit");
    Check(player.get_phobj().get_last_x() == player.get_phobj().get_x(),
          "touch_sweep_segment_is_collapsed_after_consumption");

    Check(adapter.SetHeldKeys({}, error), error);
    speeds.clear();
    for (std::uint64_t tick = 17; tick <= 44 && speeds.size() < 6; ++tick) {
        const auto before = player.get_motion_commit_id();
        Consume(host, tick);
        if (player.get_motion_commit_id() != before) speeds.push_back(player.get_motion_state().LastStep().vx);
    }
    const std::vector<double> brake = {101.0, 77.0, 53.0, 29.0, 5.0, 0.0};
    Check(speeds == brake, "ground_release_brakes_by_24_per_commit");

    auto jump = Attack();
    jump.kind = MapleControl::ActionKind::Jump;
    Check(adapter.SetActionIntent(jump, error), error);
    bool launched = false;
    bool landed = false;
    for (std::uint64_t tick = 45; tick <= 160 && !landed; ++tick) {
        Consume(host, tick);
        if (player.get_motion_state().LastStep().jumped) launched = true;
        if (launched && player.get_motion_state().LastStep().onGround) landed = true;
    }
    Check(launched, "jump_edge_is_consumed_by_a_real_motion_commit");
    Check(landed, "jump_lands_on_the_same_platform");
    Check(std::abs(player.get_phobj().crnt_y() - 1000.0) < 1e-9, "landing_commits_the_ground_contact");
}

void Schedule(SharedLuaAdapter& host) {
    auto& player = ms::Stage::get().get_player();
    player.get_phobj().onground = true;
    std::vector<std::pair<std::uint64_t, std::uint32_t>> commits;
    std::uint64_t last = player.get_motion_commit_id();
    for (std::uint64_t tick = 1; tick <= 8; ++tick) {
        Consume(host, tick);
        if (player.get_motion_commit_id() != last) {
            commits.emplace_back(tick, player.get_last_motion_step_ms());
            last = player.get_motion_commit_id();
        }
    }
    Check(commits.size() == 2, "two_30ms_commits_in_eight_world_ticks");
    Check(commits[0] == std::make_pair(std::uint64_t{4}, std::uint32_t{30}), "first_commit_after_four_world_ticks");
    Check(commits[1] == std::make_pair(std::uint64_t{8}, std::uint32_t{30}), "second_commit_after_next_four_ticks");

    std::uint64_t simulatedMs = 0;
    for (const auto& commit : commits) simulatedMs += commit.second;

    // Entering a legacy attached mode hands the same accumulated clock to 8ms steps.
    player.set_state(ms::Char::State::LADDER);
    for (std::uint64_t tick = 9; tick <= 11; ++tick) {
        const auto before = player.get_motion_commit_id();
        Consume(host, tick);
        Check(player.get_motion_commit_id() == before + 1 && player.get_last_motion_step_ms() == 8,
              "legacy_commits_each_8ms_step");
        simulatedMs += 8;
    }

    // Back to ordinary motion: the remaining world time is not lost and the next
    // commit is again a fixed 30ms step.
    player.set_state(ms::Char::State::STAND);
    bool committed = false;
    std::uint64_t committedAt = 0;
    for (std::uint64_t tick = 12; tick <= 16 && !committed; ++tick) {
        const auto before = player.get_motion_commit_id();
        Consume(host, tick);
        if (player.get_motion_commit_id() != before) {
            committed = true;
            committedAt = tick;
            Check(player.get_last_motion_step_ms() == 30, "ordinary_step_after_handoff_is_30ms");
        }
    }
    Check(committed && committedAt == 15, "handoff_consumes_time_once_and_resumes_after_four_ticks");
    simulatedMs += 30;

    // Long-run invariant: every world millisecond is consumed by exactly one commit
    // or remains in the single remainder (no 32ms integration step and no lost time).
    for (std::uint64_t tick = 16; tick <= 400; ++tick) {
        const auto before = player.get_motion_commit_id();
        Consume(host, tick);
        if (player.get_motion_commit_id() != before) simulatedMs += player.get_last_motion_step_ms();
        if (tick % 50 == 0)
            Check(simulatedMs + player.motionRemainderMs == tick * 8, "8ms_and_30ms_accumulation_never_drifts");
    }
    Check(simulatedMs + player.motionRemainderMs == 400 * 8, "mixed_clock_time_is_conserved");
}

void Packets(SharedLuaAdapter& host) {
    auto& player = ms::Stage::get().get_player();
    if (player.is_climbing()) player.set_state(ms::Char::State::STAND);
    player.get_phobj().onground = true;
    packets.clear();
    for (int tick = 0; tick < 4; ++tick) ms::Stage::get().update();
    const auto moves = PacketsOf(ms::OutPacket::MOVE_PLAYER);
    Check(moves.size() == 1, "one_position_packet_for_one_motion_commit");
    const auto& bytes = moves.front();
    // V17 layout: opcode 2 + context 1+4 + start 2+2 + count 1 + fragment 14 +
    // direction-record count 1 + bounding box 8 = 35.
    Check(bytes.size() == 35, "move_player_wire_layout_matches_v17");
    for (int index = 2; index < 7; ++index) Check(bytes[index] == 0, "unknown_context_fields_stay_zero");
    Check(bytes[11] == 1, "single_fragment");
    Check(bytes[12] == 0, "fragment_command_zero");
    Check(bytes[26] == 0, "no_direction_records");
    const auto duration =
        static_cast<std::uint16_t>(static_cast<std::uint8_t>(bytes[24]) | (static_cast<std::uint8_t>(bytes[25]) << 8));
    Check(duration == 1, "duration_value_stays_unchanged_until_dynamic_capture");
    const auto word = [&bytes](int low) {
        return static_cast<std::int16_t>(
            static_cast<std::uint16_t>(static_cast<std::uint8_t>(bytes[low]))
            | (static_cast<std::uint16_t>(static_cast<std::uint8_t>(bytes[low + 1])) << 8));
    };
    const auto startX = word(7);
    const auto startY = word(9);
    const auto x = word(13);
    const auto y = word(15);
    Check(word(27) == std::min(startX, x) && word(31) == std::max(startX, x), "bounds_x");
    Check(word(29) == std::min(startY, y) && word(33) == std::max(startY, y), "bounds_y");
    for (int tick = 0; tick < 3; ++tick) ms::Stage::get().update();
    Check(PacketsOf(ms::OutPacket::MOVE_PLAYER).size() == 1, "no_packet_without_a_new_commit_or_state_change");
}

void MotionInput(SharedLuaAdapter& host) {
    auto& adapter = host.tickAdapter;
    auto& player = ms::Stage::get().get_player();
    std::string error;
    Check(adapter.SetHeldKeys({"right"}, error), error);
    for (std::uint64_t tick = 40; tick <= 42; ++tick) adapter.Advance(tick, false);
    Check(!adapter.HeldKeysSettled(), "world_ticks_without_commit_do_not_settle_held_direction");
    for (std::uint64_t tick = 43; tick <= 47; ++tick) Consume(host, tick);
    Check(adapter.HeldKeysSettled(), "held_direction_settles_on_a_real_motion_commit");
    adapter.Release();
    Check(adapter.HeldKeysSettled() && !player.is_key_down(ms::KeyAction::RIGHT),
          "direction_release_is_confirmed_immediately");

    auto jump = Attack();
    jump.kind = MapleControl::ActionKind::Jump;
    Check(adapter.SetActionIntent(jump, error), error);
    Check(player.get_motion_state().HasPendingJump(), "jump_keydown_records_a_motion_edge");
    Check(!adapter.ActionIntentSettled(), "jump_is_not_settled_by_world_ticks_alone");
    adapter.ReleaseAction();
    Check(adapter.ActionIntentSettled() && adapter.Released(), "jump_release_settles_immediately");
    Check(!player.get_motion_state().HasPendingJump(), "withdrawn_jump_is_cleared_not_queued");
}

// Resource boundary: deterministic skill metadata, using the real native action
// implementation and the real Player::can_use level/MP/cooldown checks.
namespace ms {
Skill::Skill(int32_t id) : skillid(id) {
    if (id == NoActionSkill)
        action = std::make_unique<NoAction>();
    else
        action = std::make_unique<RegularAction>();
}

void Skill::apply_useeffects(Char&) const {}

void Skill::apply_actions(Char& user, Attack::Type type) const {
    action->apply(user, type);
}

void Skill::apply_stats(const Char&, Attack&) const {}

void Skill::apply_hiteffects(const AttackUser&, Mob&) const {}

Animation Skill::get_bullet(const Char&, int32_t) const {
    return {};
}

bool Skill::is_attack() const {
    return false;
}

bool Skill::is_skill() const {
    return true;
}

int32_t Skill::get_id() const {
    return skillid;
}

SpecialMove::ForbidReason Skill::can_use(int32_t level, Weapon::Type, const Job&, uint16_t, uint16_t mp,
                                         uint16_t) const {
    if (level == 0) return FBR_NOT_LEARNED;
    return mp >= 5 ? FBR_NONE : FBR_MPCOST;
}

// Network boundary only: no connection, handshake or real writes.
SocketAsio::SocketAsio() = default;
SocketAsio::~SocketAsio() = default;
Cryptography::Cryptography() = default;
Cryptography::~Cryptography() = default;
PacketSwitch::PacketSwitch() = default;
Session::Session() = default;
Session::~Session() = default;

bool Session::is_connected() const {
    return true;
}

void Session::write(int8_t* bytes, size_t size) {
    packets.emplace_back(bytes, bytes + size);
}
}

int main(int argc, char** argv) {
    Check(argc == 4, "scenario_physics_and_map_resource_required");
    // Physics.img is a required resource for real local-character motion; the map
    // fixture supplies foothold geometry for the integrated ground scenarios.
    auto physics = load_img_directory(argv[2]);
    ms::V17PhysicsParameters::Init(physics.root()["Physics.img"]);
    SharedLuaAdapter host({}, "offline-contract");
    Prepare(host);
    const std::string scenario = argv[1];
    if (scenario == "keys")
        Keys(host);
    else if (scenario == "skills")
        Skills(host);
    else if (scenario == "no-action")
        NoAction(host);
    else if (scenario == "potions")
        Potions(host);
    else if (scenario == "lifecycle")
        Lifecycle(host);
    else if (scenario == "provenance")
        Provenance(host);
    else if (scenario == "physics")
        Physics(host);
    else if (scenario == "ground")
        Ground(host, argv[3]);
    else if (scenario == "schedule")
        Schedule(host);
    else if (scenario == "packets")
        Packets(host);
    else if (scenario == "motion-input")
        MotionInput(host);
    else
        Check(false, "unknown_scenario");
    host.Shutdown();
}
