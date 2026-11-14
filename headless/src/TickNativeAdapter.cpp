// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TickNativeAdapter.h"
#include "SharedLuaAdapter.h"
#include "Gameplay/Stage.h"
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
    return kind == Kind::Jump || kind == Kind::Attack || kind == Kind::Pickup || kind == Kind::UseItem;
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
        movement = std::move(desired);
        movementTick = currentTick;
        movementChanged = true;
        host.SyncKeys();
    }
    return true;
}

bool TickNativeAdapter::HeldKeysSettled() const {
    return !movementChanged || currentTick > movementTick;
}

bool TickNativeAdapter::SetActionIntent(const MapleControl::Action& action, std::string& error) {
    using Kind = MapleControl::ActionKind;
    if (action.kind == Kind::Stop) {
        ReleaseAction();
        return true;
    }
    if (action.kind != Kind::Jump && action.kind != Kind::Attack && action.kind != Kind::Pickup
        && action.kind != Kind::UseItem) {
        error = "unsupported: tick_action";
        return false;
    }
    if (!Observe().ready || Observe().dead == MapleControl::Fact::True) {
        error = "state_unavailable_or_dead";
        return false;
    }
    if (intent.kind == action.kind && intent.skillId == action.skillId && intent.itemId == action.itemId) {
        // Ownership may change, but an unchanged semantic hold emits no edges
        // and must not rearm a no-action skill or a consumable repeat timer.
        intent.sessionId = action.sessionId;
        return true;
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
    return true;
}

const MapleControl::Action* TickNativeAdapter::ActiveAction() const {
    return nativeActive ? &activeAction : nullptr;
}

bool TickNativeAdapter::ActionIntentSettled() const {
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
    const auto& player = ms::Stage::get().get_player();
    const auto& combat = ms::Stage::get().get_combat();
    if (sceneChanged || !Observe().ready) {
        Release();
        nativeActive = false;
        moveSequence = combat.get_move_sequence();
        itemSequence = player.get_held_item_sequence();
        result.controlReleased = ActionIntentSettled();
        return;
    }
    if (Observe().dead == MapleControl::Fact::True) Release();
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
