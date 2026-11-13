// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TickNativeAdapter.h"
#include "SharedLuaAdapter.h"
#include "Gameplay/Stage.h"

#include <chrono>

namespace {
std::uint64_t NowMs() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}
}

TickNativeAdapter::TickNativeAdapter(SharedLuaAdapter& owner) : host(owner) {}

const char* TickNativeAdapter::Backend() const {
    return "headless";
}

const MapleControl::State& TickNativeAdapter::Observe() const {
    return host.Observe();
}

MapleControl::Observation TickNativeAdapter::ObserveDomain(const std::string& domain) const {
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
    return kind == Kind::Move || kind == Kind::Stop || kind == Kind::Jump || kind == Kind::Attack
           || kind == Kind::Pickup || kind == Kind::UseItem;
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

bool TickNativeAdapter::Begin(const MapleControl::Action& action, std::string& error) {
    using Kind = MapleControl::ActionKind;
    if (!Supports(action.kind)) {
        error = "unsupported: tick_action";
        return false;
    }
    if (action.kind == Kind::Stop) {
        Release();
        return true;
    }
    const auto& state = Observe();
    if (!state.ready || state.dead == MapleControl::Fact::True) {
        error = "state_unavailable_or_dead";
        return false;
    }
    if (!Released()) {
        error = "busy";
        return false;
    }
    auto& stage = ms::Stage::get();
    auto& player = stage.get_player();
    result = {};
    result.sessionId = action.sessionId;
    result.reason = "native_action_dispatched";
    if (action.kind == Kind::Jump)
        actionKeys = {ms::KeyAction::JUMP};
    else if (action.kind == Kind::Pickup)
        actionKeys = {ms::KeyAction::PICKUP};
    else if (action.kind == Kind::Attack && action.skillId == 0) {
        if (!player.can_attack()) {
            result.controlReleased = true;
            result.reason = "native_attack_not_allowed";
            return true;
        }
        actionKeys = {ms::KeyAction::ATTACK};
    } else if (action.kind == Kind::Attack) {
        const auto reason = stage.get_combat().use_move(static_cast<std::int32_t>(action.skillId));
        result.skillRequested = true;
        result.skill.nativeResult = static_cast<int>(reason);
        result.skill.dispatched = reason == ms::SpecialMove::FBR_NONE;
        result.skill.reason = result.skill.dispatched ? "native_skill_dispatched" : "native_skill_rejected";
        result.dispatched = result.skill.dispatched;
        result.reason = result.skill.reason;
    } else if (action.kind == Kind::UseItem) {
        if (action.itemId / 10000 != 200 && action.itemId / 10000 != 201) {
            error = "unsupported: ordinary_potion_or_food_required";
            return false;
        }
        if (player.get_inventory().get_total_item_count(action.itemId) <= 0) {
            error = "item_not_in_inventory";
            return false;
        }
        player.use_item(action.itemId);
        result.reason = "item_use_requested";
        result.dispatched = true;
    } else {
        error = "unsupported: tick_action";
        return false;
    }
    if (!actionKeys.empty()) result.dispatched = true;
    active = true;
    pulseReleased = false;
    actionKind = action.kind;
    result.controlReleased = false;
    deadlineMs = NowMs() + action.durationMs;
    host.SyncKeys();
    return true;
}

MapleControl::ActionResult TickNativeAdapter::Result() const {
    return result;
}

bool TickNativeAdapter::Released() const {
    return !active && !releasing;
}

bool TickNativeAdapter::ReleasePending() const {
    return releasing;
}

void TickNativeAdapter::Release() {
    if (!movement.empty()) {
        movementTick = currentTick;
        movementChanged = true;
    }
    movement.clear();
    ReleaseAction();
}

void TickNativeAdapter::ReleaseAction() {
    actionKeys.clear();
    active = false;
    releasing = true;
    releaseTick = currentTick;
    host.SyncKeys();
}

void TickNativeAdapter::Advance(std::uint64_t nativeTick, bool sceneChanged) {
    currentTick = nativeTick;
    if (releasing && currentTick > releaseTick) {
        releasing = false;
        result.controlReleased = true;
        result.settled = Observe().settled;
    }
    if (sceneChanged || !Observe().ready || Observe().dead == MapleControl::Fact::True) {
        if (active || !movement.empty()) Release();
    } else if (active && !pulseReleased && NowMs() >= deadlineMs) {
        // Release the pulse once. A later logic step must consume the key-up;
        // only an attack animation may continue to own the action slot.
        actionKeys.clear();
        pulseReleased = true;
        releasing = true;
        releaseTick = currentTick;
        host.SyncKeys();
    }
    if (active && pulseReleased && !releasing) {
        auto& player = ms::Stage::get().get_player();
        if (actionKind == MapleControl::ActionKind::Attack)
            active = player.is_attacking();
        else
            // Jump completes its input lifecycle here; flight and landing are
            // physical facts, not ownership of the one-shot input slot.
            active = false;
    }
}

void TickNativeAdapter::Shutdown() {
    Release();
    releasing = false;
    movementChanged = false;
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
