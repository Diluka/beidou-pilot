// SPDX-License-Identifier: AGPL-3.0-or-later
// Offline fixture: private access only seeds an empty native stage and reads its
// real adapter/counters. No production test mode, asset files, sockets or account.
#include <bits/stdc++.h>
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
    host.Capture(0);
    Check(host.Observe().ready, "fixture_is_ready_without_a_network_or_resource_file");
    Check(player.can_attack(), "actual_player_native_admission_has_a_weapon");
}

void Consume(SharedLuaAdapter& host, std::uint64_t tick) {
    ms::Stage::get().update();
    host.Tick(tick, false);
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
    const auto edges = host.inputEvents;
    Check(player.is_key_down(ms::KeyAction::RIGHT) && player.is_key_down(ms::KeyAction::JUMP), "real_native_down_keys");
    const auto launch = player.get_phobj().vforce;
    Check(launch < 0, "real_jump_down_executes_the_native_launch");
    player.get_phobj().vforce = 0;
    for (int i = 0; i < 20; ++i) {
        Check(adapter.SetActionIntent(jump, error), error);
        adapter.Advance(i + 1, false);
    }
    Check(host.inputEvents == edges && player.get_phobj().vforce == 0, "same_hold_never_replays_jump_down");
    Check(adapter.ActionIntentSettled() && !adapter.Released(), "a_still_held_input_can_be_settled");
    Check(adapter.Result().dispatched && adapter.Result().reason == "native_jump_input_consumed",
          "jump_reports_confirmed_native_input_not_a_fabricated_game_effect");
    adapter.ReleaseAction();
    Check(!player.is_key_down(ms::KeyAction::JUMP) && player.is_key_down(ms::KeyAction::RIGHT),
          "action_withdrawal_keeps_direction");
    Check(adapter.ReleasePending(), "real_key_up_requires_a_later_native_frame");
    adapter.Advance(21, false);
    Check(adapter.Released(), "native_frame_confirms_key_up");
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
    auto& stage = ms::Stage::get();
    auto& combat = stage.get_combat();
    std::string error;
    Check(adapter.SetActionIntent(Attack(SkillA), error), error);
    Check(combat.use_move(SkillA) == ms::SpecialMove::FBR_NONE, "direct_native_move_starts");
    host.Capture(1);
    adapter.Advance(1, false);
    Check(adapter.ActiveAction() && adapter.ActiveAction()->skillId == SkillA
              && adapter.ActiveAction()->sessionId.empty() && !adapter.Result().dispatched,
          "matching_direct_skill_is_a_global_action_but_not_this_tick_request");
    adapter.ReleaseAction();
    FinishAnimation();
    adapter.Advance(2, false);

    Check(adapter.SetActionIntent(Attack(SkillB), error), error);
    MapleControl::Action movement;
    movement.kind = MapleControl::ActionKind::Move;
    movement.direction = "right";
    movement.durationMs = 100;
    Check(host.Begin(movement, error), error);
    host.Release();
    Consume(host, 3);
    Check(adapter.Result().dispatched && adapter.ActiveAction()
              && adapter.ActiveAction()->sessionId == "native-contract",
          "coroutine_release_does_not_clear_the_tick_semantic_skill_hold");
    adapter.ReleaseAction();
    FinishAnimation();
    adapter.Advance(4, false);

    Check(adapter.SetActionIntent(Attack(), error), error);
    Check(host.Begin(Attack(), error), error);
    Consume(host, 5);
    Check(adapter.ActiveAction() && adapter.ActiveAction()->sessionId.empty() && !adapter.Result().dispatched,
          "shared_ordinary_key_does_not_fabricate_an_exclusive_tick_owner");
    host.Release();
    Check(stage.get_player().is_key_down(ms::KeyAction::ATTACK),
          "coroutine_release_preserves_tick_physical_hold_at_the_union_boundary");
    adapter.ReleaseAction();
    FinishAnimation();
    adapter.Advance(6, false);
}

void Lifecycle(SharedLuaAdapter& host) {
    auto& adapter = host.tickAdapter;
    auto& player = ms::Stage::get().get_player();
    auto& combat = ms::Stage::get().get_combat();
    std::string error;
    player.get_phobj().onground = false;
    player.get_phobj().hspeed = 1.5;
    host.Capture(1);
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
    host.Capture(5);
    Check(host.Observe().actionIdle == MapleControl::Fact::Unknown,
          "unavailable_player_has_unknown_not_fabricated_idle");
}
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
    Check(argc == 2, "scenario_required");
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
    else
        Check(false, "unknown_scenario");
    host.Shutdown();
}
