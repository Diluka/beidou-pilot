// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TickNativeAdapter.h"
#include "AutoAp.h"
#include "Net/Packets/PlayerPackets.h"
#include "SharedLuaAdapter.h"
#include "Gameplay/Stage.h"
#include "Net/Packets/GameplayPackets.h"
#include "SceneTerrain.h"
#include <nlnx/nx.hpp>

#include <filesystem>
#include <iomanip>
#include <sstream>

TickNativeAdapter::TickNativeAdapter(SharedLuaAdapter& owner) : host(owner) {}

const MapleControl::State& TickNativeAdapter::Observe() const {
    return host.Observe();
}

MapleControl::Observation TickNativeAdapter::ObserveDomain(const std::string& domain) const {
    if (domain == "terrain") {
        const auto& state = Observe();
        if (!state.ready || !state.mapKnown || !state.characterKnown)
            return {"unavailable", {}, "strategy_scene_unavailable"};
        std::ostringstream name;
        name << std::setfill('0') << std::setw(9) << state.mapId << ".img";
        const auto group = "Map" + std::to_string(state.mapId / 100000000);
        // ImgFiles::init selected this immutable, already decoded directory.
        // Do not reopen the full map catalog in a gameplay frame.
        const auto map = nl::nx::Map002["Map"][group][name.str()];
        const auto root = std::filesystem::current_path();
        const auto directory = std::filesystem::is_directory(root / "Map002") ? "Map002" : "Map";
        const auto source = (root / directory / "Map" / group / name.str()).generic_string();
        return MapleControl::ReadSceneTerrain(map, state.mapId, source, [](const nl::node& node, std::int64_t& value) {
            if (node.data_type() != nl::node::type::integer) return false;
            value = node.get_integer();
            return true;
        });
    }
    auto observation = host.ObserveDomain(domain);
    if (domain == "character" && observation.status == "ok") {
        // Player exposes only has_buff(stat), not a complete list or remaining
        // durations. Do not turn this incomplete native view into an empty list.
        observation.data["buffs"] = {};
        observation.data["buffs_status"] = "unsupported";
        observation.data["buffs_unavailable"] = "native_buff_details_unavailable";
    }
    return observation;
}

bool TickNativeAdapter::Supports(MapleControl::ActionKind kind) const {
    using Kind = MapleControl::ActionKind;
    return kind == Kind::Jump || kind == Kind::Attack || kind == Kind::Pickup || kind == Kind::UseItem
           || kind == Kind::Revive || kind == Kind::AutoAp;
}

bool TickNativeAdapter::SupportsSkill() const {
    return true;
}

bool TickNativeAdapter::SetHeldKeys(const std::vector<std::string>& keys, std::string& error) {
    std::vector<ms::KeyAction::Id> desired;
    for (const auto& key : keys) {
        if (key == "left")
            desired.push_back(ms::KeyAction::LEFT);
        else if (key == "right")
            desired.push_back(ms::KeyAction::RIGHT);
        else if (key == "up")
            desired.push_back(ms::KeyAction::UP);
        else if (key == "down")
            desired.push_back(ms::KeyAction::DOWN);
        else {
            error = "unsupported: tick_held_key";
            return false;
        }
    }
    if (movement != desired) {
        bool pressed = false;
        for (const auto key : desired)
            if (std::find(movement.begin(), movement.end(), key) == movement.end()) pressed = true;
        movement = std::move(desired);
        movementTick = currentTick;
        // A held direction is observed by the next real motion commit; releasing a
        // direction is applied to the native key state synchronously and settles now.
        movementNeedsMotion = pressed;
        if (pressed) motionTick = ms::Stage::get().get_player().get_motion_commit_id();
        movementChanged = true;
        host.SyncKeys();
    }
    return true;
}

bool TickNativeAdapter::HeldKeysSettled() const {
    return !movementNeedsMotion;
}

bool TickNativeAdapter::SetActionIntent(const MapleControl::Action& action, std::string& error) {
    using Kind = MapleControl::ActionKind;
    if (action.kind == Kind::Stop) {
        ReleaseAction();
        return true;
    }
    const auto& state = Observe();
    if (action.kind != Kind::Jump && action.kind != Kind::Attack && action.kind != Kind::Pickup
        && action.kind != Kind::UseItem && action.kind != Kind::Revive && action.kind != Kind::AutoAp) {
        error = "unsupported: tick_action";
        return false;
    }
    if (!state.ready || (state.dead == MapleControl::Fact::True && action.kind != Kind::Revive)) {
        error = "state_unavailable_or_dead";
        return false;
    }
    if (action.kind == Kind::Revive) {
        if (!state.characterKnown || !state.character.known[6]) {
            error = "character_unavailable";
            return false;
        }
        if (state.character.values[6] != 0) {
            error = "already_alive";
            return false;
        }
        if (state.reviveRequestable == MapleControl::Fact::False) {
            error = "revive_not_requestable";
            return false;
        }
    }
    if (autoApPending && state.characterKnown && !autoApIdentity.Observe(state.character.id)
        && action.kind == Kind::AutoAp) {
        result.effect = "unknown";
        result.reason = error = "auto_ap_identity_changed";
        return false;
    }
    if (action.kind == Kind::AutoAp) {
        if (!state.characterKnown || action.autoApInstanceId != state.instanceId
            || action.autoApCharacterId != state.character.id
            || action.autoApSceneGeneration != state.sceneGeneration) {
            error = "auto_ap_identity_changed";
            return false;
        }
        const auto admission =
            CheckAutoApAdmission(intent.kind == Kind::AutoAp, autoApPending, intent.sessionId, action.sessionId);
        if (admission == AutoApAdmission::Pending) {
            error = autoApIdentity.changed ? "auto_ap_identity_changed"
                    : autoApPending        ? "auto_ap_confirmation_pending"
                                           : "auto_ap_action_owned";
            return false;
        }
        if (admission == AutoApAdmission::SameSession) return true;
    }
    if (intent.kind == action.kind && intent.skillId == action.skillId && intent.itemId == action.itemId) {
        // Ownership may change, but an unchanged semantic hold emits no edges
        // and must not rearm a no-action skill or a consumable repeat timer.
        intent.sessionId = action.sessionId;
        return true;
    }
    AutoApPlan autoAp;
    if (action.kind == Kind::AutoAp) {
        if (!state.characterKnown || !state.character.known[0] || !state.character.known[1] || !state.character.known[2]
            || !state.character.known[3] || !state.character.known[4] || !state.character.known[5]
            || !state.character.known[10]) {
            error = "character_unavailable";
            return false;
        }
        const auto& v = state.character.values;
        if (!PlanAutoAp({v[0], v[1], v[2], v[3], v[4], v[5], v[10]}, autoAp)) {
            error = "unsupported: auto_ap_job";
            return false;
        }
        if (v[10] == 0) {
            error = "no_ability_points";
            return false;
        }
        for (int i = 0; i < 4; ++i) autoApExpected[i] = v[2 + i];
        for (int i = 0; i < 2; ++i) {
            int index = autoAp.codes[i] == 0x40 ? 0 : autoAp.codes[i] == 0x80 ? 1 : autoAp.codes[i] == 0x100 ? 2 : 3;
            autoApExpected[index] += autoAp.amounts[i];
        }
        autoApExpected[4] = 0;
    }
    auto& stage = ms::Stage::get();
    auto& player = stage.get_player();
    if (action.kind == Kind::UseItem) {
        if (action.itemId / 10000 != 200 && action.itemId / 10000 != 201) {
            error = "unsupported: ordinary_potion_or_food_required";
            return false;
        }
        if (player.get_inventory().get_total_item_count(action.itemId) <= 0) {
            error = "item_not_in_inventory";
            return false;
        }
    }

    intent = action;
    intentTick = currentTick;
    intentChanged = true;
    // A jump press is consumed by the next motion commit; replacing it before then
    // drops the edge instead of queuing a delayed jump.
    jumpNeedsMotion = action.kind == MapleControl::ActionKind::Jump;
    if (jumpNeedsMotion) motionTick = ms::Stage::get().get_player().get_motion_commit_id();
    result = {};
    result.sessionId = action.sessionId;
    result.reason = "native_input_intent_accepted";
    actionKeys.clear();
    if (action.kind == Kind::Jump)
        actionKeys = {ms::KeyAction::JUMP};
    else if (action.kind == Kind::Pickup)
        actionKeys = {ms::KeyAction::PICKUP};
    else if (action.kind == Kind::Attack && action.skillId == 0)
        actionKeys = {ms::KeyAction::ATTACK};
    stage.get_combat().hold_move(
        action.kind == Kind::Attack && action.skillId != 0 ? std::optional<int32_t>(action.skillId) : std::nullopt);
    player.hold_item(action.kind == Kind::UseItem ? action.itemId : 0);
    host.SyncKeys();
    if (action.kind == Kind::AutoAp) {
        const auto& current = Observe();
        if (!current.ready || !current.characterKnown || current.instanceId != action.autoApInstanceId
            || current.character.id != action.autoApCharacterId
            || current.sceneGeneration != action.autoApSceneGeneration) {
            error = "auto_ap_identity_changed";
            return false;
        }
        autoApPending = true;
        autoApIdentity = {state.character.id, false};
        result.dispatched = true;
        result.reason = "auto_ap_request_dispatched";
        ms::AutoApPacket(autoAp.codes[0], autoAp.amounts[0], autoAp.codes[1], autoAp.amounts[1]).dispatch();
    }
    if (action.kind == Kind::Revive) {
        // Mirrors V17's normal death-confirm route: died=true, no map/portal target, no wheel.
        result.dispatched = true;
        result.reason = "revive_request_dispatched";
        ms::ChangeMapPacket(true, 0, "", false).dispatch();
    }
    return true;
}

const MapleControl::Action* TickNativeAdapter::ActiveAction() const {
    return nativeActive ? &activeAction : nullptr;
}

bool TickNativeAdapter::ActionIntentSettled() const {
    // Stop releases the native key path synchronously; jump is confirmed by a real
    // motion commit; other held actions keep their own native world-tick facts.
    if (intent.kind == MapleControl::ActionKind::Stop) return true;
    if (intent.kind == MapleControl::ActionKind::Jump) return !jumpNeedsMotion;
    return !intentChanged || currentTick > intentTick;
}

MapleControl::ActionResult TickNativeAdapter::Result() const {
    return result;
}

bool TickNativeAdapter::Released() const {
    return intent.kind == MapleControl::ActionKind::Stop && ActionIntentSettled();
}

bool TickNativeAdapter::ReleasePending() const {
    return intent.kind == MapleControl::ActionKind::Stop && !ActionIntentSettled();
}

void TickNativeAdapter::Release() {
    if (!movement.empty()) {
        movementTick = currentTick;
        movementNeedsMotion = false;
        movementChanged = true;
    }
    movement.clear();
    ReleaseAction();
    host.SyncKeys();
}

void TickNativeAdapter::ReleaseAction() {
    if (intent.kind == MapleControl::ActionKind::Stop) return;
    intent = {};
    actionKeys.clear();
    intentTick = currentTick;
    intentChanged = true;
    jumpNeedsMotion = false;
    result.controlReleased = false;
    auto& stage = ms::Stage::get();
    stage.get_combat().hold_move(std::nullopt);
    stage.get_player().hold_item(0);
    host.SyncKeys();
    // Releasing input never interrupts or relabels an already playing action.
}

void TickNativeAdapter::Advance(std::uint64_t nativeTick, bool sceneChanged) {
    using Kind = MapleControl::ActionKind;
    currentTick = nativeTick;
    auto& player = ms::Stage::get().get_player();
    const auto& combat = ms::Stage::get().get_combat();
    const auto motionId = player.get_motion_commit_id();
    if (movementNeedsMotion && motionId > motionTick) movementNeedsMotion = false;
    if (jumpNeedsMotion && motionId > motionTick) jumpNeedsMotion = false;
    if (autoApPending && Observe().characterKnown && !autoApIdentity.Observe(Observe().character.id)) {
        if (intent.kind == Kind::AutoAp) {
            result.effect = "unknown";
            result.reason = "auto_ap_identity_changed";
        }
    }
    if (sceneChanged || !Observe().ready) {
        player.clear_motion_requests();
        Release();
        nativeActive = false;
        moveSequence = combat.get_move_sequence();
        itemSequence = player.get_held_item_sequence();
        result.controlReleased = ActionIntentSettled();
        return;
    }
    if (autoApPending && !autoApIdentity.changed && Observe().characterKnown) {
        const auto& character = Observe().character;
        bool confirmed = character.known[10] && character.values[10] == autoApExpected[4];
        for (int i = 0; i < 4; ++i)
            confirmed = confirmed && character.known[2 + i] && character.values[2 + i] == autoApExpected[i];
        if (confirmed) {
            autoApPending = false;
            if (intent.kind == Kind::AutoAp) {
                result.effect = "confirmed";
                result.reason = "auto_ap_server_confirmed";
            }
        }
    }
    if (Observe().dead == MapleControl::Fact::True && intent.kind != Kind::Revive) Release();
    if (ActionIntentSettled()) {
        if (intentChanged && (intent.kind == Kind::Jump || intent.kind == Kind::Pickup)) {
            // Confirm native input consumption, not a launch, landing or loot.
            result.dispatched = true;
            result.sessionId = intent.sessionId;
            result.reason = intent.kind == Kind::Jump ? "native_jump_input_consumed" : "native_pickup_input_consumed";
        }
        intentChanged = false;
        result.controlReleased = intent.kind == Kind::Stop;
        result.settled = Observe().settled;
    }
    if (!player.is_attacking()) nativeActive = false;
    if (combat.get_move_sequence() != moveSequence) {
        moveSequence = combat.get_move_sequence();
        const auto skillId = static_cast<std::uint32_t>(combat.get_last_move());
        const auto source = combat.get_last_move_input();
        const bool owned =
            intent.kind == Kind::Attack && intent.skillId == skillId
            && ((skillId != 0 && source == ms::Combat::MoveInput::HeldSkill)
                || (skillId == 0 && source == ms::Combat::MoveInput::HeldKey
                    && std::find(actionKeys.begin(), actionKeys.end(), ms::KeyAction::ATTACK) != actionKeys.end()));
        // This identity comes from an admitted native dispatch, not the desired
        // slot. A replacement B cannot turn an unfinished native A into B.
        if (player.is_attacking()) {
            activeAction = {};
            activeAction.kind = Kind::Attack;
            activeAction.skillId = skillId;
            if (owned) activeAction.sessionId = intent.sessionId;
            nativeActive = true;
        }
        // A direct native move can be the global current action, but is not
        // evidence that this tick owner's input was dispatched.
        if (owned) {
            result.dispatched = true;
            result.sessionId = intent.sessionId;
            result.skillRequested = skillId != 0;
            result.skill.dispatched = skillId != 0;
            result.skill.reason = skillId != 0 ? "native_skill_dispatched" : "";
            result.reason = skillId != 0 ? "native_skill_dispatched" : "native_attack_dispatched";
        }
    }
    if (player.get_held_item_sequence() != itemSequence) {
        itemSequence = player.get_held_item_sequence();
        if (intent.kind == Kind::UseItem && intent.itemId == static_cast<std::uint32_t>(player.get_last_held_item())) {
            result.dispatched = true;
            result.sessionId = intent.sessionId;
            result.reason = "item_use_requested";
        }
    }
}

void TickNativeAdapter::Shutdown() {
    Release();
    intentChanged = false;
    movementChanged = false;
    movementNeedsMotion = false;
    jumpNeedsMotion = false;
    nativeActive = false;
    result.controlReleased = true;
    result.settled = MapleControl::Fact::Unknown;
}

bool TickNativeAdapter::Logs(const std::string& id, const std::vector<std::string>& lines) {
    return host.Logs(id, lines);
}

std::vector<ms::KeyAction::Id> TickNativeAdapter::Keys() const {
    auto keys = movement;
    keys.insert(keys.end(), actionKeys.begin(), actionKeys.end());
    return keys;
}
