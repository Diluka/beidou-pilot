// SPDX-License-Identifier: AGPL-3.0-or-later
#include "SharedLuaAdapter.h"
#include "HeadlessState.h"
#include "LoginState.h"

#include "Character/Player.h"
#include "Data/EquipData.h"
#include "Gameplay/Stage.h"
#include "Gameplay/MapleMap/Mob.h"
#include "Gameplay/MapleMap/Npc.h"
#include "Gameplay/MapleMap/ItemDrop.h"
#include "Gameplay/MapleMap/MesoDrop.h"
#include "IO/KeyType.h"
#include "Net/Session.h"
#include "Net/Packets/InventoryPackets.h"
#include "Net/Packets/GameplayPackets.h"

#include <array>
#include <cmath>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <unistd.h>

namespace {
using Json = nlohmann::json;
using Fact = MapleControl::Fact;

MapleControl::Value ObservationValue(const Json& value) {
    using Value = MapleControl::Value;
    if (value.is_object()) {
        auto result = Value::Object();
        for (const auto& entry : value.items()) result[entry.key()] = ObservationValue(entry.value());
        return result;
    }
    if (value.is_array()) {
        auto result = Value::Array();
        for (const auto& entry : value) result.Add(ObservationValue(entry));
        return result;
    }
    if (value.is_null()) return {};
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_string()) return value.get<std::string>();
    if (value.is_number_unsigned()) return value.get<std::uint64_t>();
    if (value.is_number_integer()) return value.get<std::int64_t>();
    return value.get<double>();
}

std::uint64_t MonotonicMs() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

std::uint64_t UnixMs() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch())
        .count();
}

Json FactValue(Fact fact) {
    return fact == Fact::Unknown ? Json(nullptr) : Json(fact == Fact::True);
}

Json ScriptDocument(const MapleControl::Status* script) {
    if (script == nullptr) return nullptr;
    Json tasks = Json::array();
    for (const auto& task : script->tasks)
        tasks.push_back({{"name", task.name},
                         {"revision", task.revision},
                         {"priority", task.priority},
                         {"status", task.status},
                         {"wait", task.wait},
                         {"reason", task.reason.empty() ? Json(nullptr) : Json(task.reason)},
                         {"error", task.error.empty() ? Json(nullptr) : Json(task.error)}});
    const auto& control = script->control;
    return {{"id", script->id},
            {"status", script->status},
            {"reason", script->reason.empty() ? Json(nullptr) : Json(script->reason)},
            {"error", script->error.empty() ? Json(nullptr) : Json(script->error)},
            {"resumes", script->resumes},
            {"budget_yields", script->budgetYields},
            {"last_resume_us", script->lastResumeUs},
            {"max_resume_us", script->maxResumeUs},
            {"tasks", std::move(tasks)},
            {"control",
             {{"owner", control.owner.empty() ? Json(nullptr) : Json(control.owner)},
              {"pending", control.pending.empty() ? Json(nullptr) : Json(control.pending)},
              {"from", control.from.empty() ? Json(nullptr) : Json(control.from)},
              {"to", control.to.empty() ? Json(nullptr) : Json(control.to)},
              {"reason", control.reason.empty() ? Json(nullptr) : Json(control.reason)}}}};
}
}

SharedLuaAdapter::SharedLuaAdapter(std::filesystem::path bridgeDirectory, std::string registeredRun)
    : directory(std::move(bridgeDirectory)), runId(std::move(registeredRun)), runtime(*this),
      taskTransport(directory.string(), runId) {
    state.instanceId = std::to_string(getpid()) + "-" + std::to_string(UnixMs()) + "-" + std::to_string(MonotonicMs());
    if (!directory.empty()) std::filesystem::create_directories(directory);
}

const char* SharedLuaAdapter::Backend() const {
    return "headless";
}

const MapleControl::State& SharedLuaAdapter::Observe() const {
    return state;
}

MapleControl::Observation SharedLuaAdapter::ObserveDomain(const std::string& domain) const {
    MapleControl::Observation observation;
    observation.data = ObservationValue(ObservationData(domain, observation.status, observation.error));
    return observation;
}

bool SharedLuaAdapter::Supports(MapleControl::ActionKind) const {
    return true;
}

bool SharedLuaAdapter::SupportsSkill() const {
    return true;
}

bool SharedLuaAdapter::SupportsMonsterHpPercent() const {
    return true;
}

bool SharedLuaAdapter::Skill(std::uint32_t id, MapleControl::SkillResult& skill, std::string& error) {
    if (id != 1001004 && id != 1001005) {
        error = "unsupported: skill_type";
        return false;
    }
    if (!state.ready || state.character.values[6] == 0) {
        error = "state_unavailable_or_dead";
        return false;
    }
    if (!Released()) {
        error = "action_in_progress";
        return false;
    }
    using Move = ms::SpecialMove;
    const auto reason = ms::Stage::get().get_combat().use_move(static_cast<std::int32_t>(id));
    skill.nativeResult = static_cast<int>(reason);
    skill.dispatched = reason == Move::FBR_NONE;
    switch (reason) {
    case Move::FBR_NONE:
        skill.reason = "skill_dispatched";
        break;
    case Move::FBR_WEAPONTYPE:
        skill.reason = "native_skill_weapon_mismatch";
        break;
    case Move::FBR_HPCOST:
        skill.reason = "native_skill_insufficient_hp";
        break;
    case Move::FBR_MPCOST:
        skill.reason = "native_skill_insufficient_mp";
        break;
    case Move::FBR_BULLETCOST:
        skill.reason = "native_skill_insufficient_ammunition";
        break;
    case Move::FBR_COOLDOWN:
        skill.reason = "native_skill_cooldown";
        break;
    case Move::FBR_NOT_LEARNED:
        skill.reason = "native_skill_not_learned";
        break;
    case Move::FBR_JOB:
        skill.reason = "native_skill_job_mismatch";
        break;
    case Move::FBR_ATTACKING:
        skill.reason = "native_attacking";
        break;
    case Move::FBR_CLIMBING:
        skill.reason = "native_climbing";
        break;
    case Move::FBR_SITTING:
        skill.reason = "native_sitting";
        break;
    case Move::FBR_NO_WEAPON:
        skill.reason = "native_no_weapon";
        break;
    case Move::FBR_SKILL_STATE:
        skill.reason = "native_skill_state_not_allowed";
        break;
    case Move::FBR_OTHER:
        skill.reason = "native_skill_not_allowed";
        break;
    }
    lastSkill = LastSkill{id, skill};
    return true;
}

MapleControl::ActionResult SharedLuaAdapter::Result() const {
    return result;
}

bool SharedLuaAdapter::Released() const {
    return !active && !releasePending;
}

bool SharedLuaAdapter::ReleasePending() const {
    return releasePending;
}

bool SharedLuaAdapter::Running() const {
    return runtime.Running();
}

void SharedLuaAdapter::Cancel(const std::string& reason) {
    runtime.Cancel(reason);
}

void SharedLuaAdapter::Capture(std::uint64_t nativeTick) {
    currentTick = nativeTick;
    ++state.sequence;
    state.observedAtMs = UnixMs();
    state.sceneGeneration = ms::headless_state().map_generation;
    state.inGame = ms::headless_state().in_game && ms::Session::get().is_connected();
    state.ready = state.inGame && ms::Stage::get().is_active();
    state.mapKnown = state.characterKnown = state.positionKnown = state.facingKnown = state.ready;
    state.monstersKnown = state.inventoryKnown = state.dropsKnown = state.ready;
    state.monsters.clear();
    state.inventory.clear();
    state.drops.clear();
    state.dead = state.reviveRequestable = Fact::Unknown;
    if (!state.ready) {
        state.settled = Fact::Unknown;
        return;
    }
    auto& stage = ms::Stage::get();
    auto& player = stage.get_player();
    const auto& stats = player.get_stats();
    const auto& ph = player.get_phobj();
    const auto pos = player.get_position();
    const auto& inventory = player.get_inventory();
    state.mapId = stage.get_mapid();
    state.character.id = player.get_oid();
    state.character.name = player.get_name();
    state.character.values = {player.get_level(),
                              stats.get_job().get_id(),
                              stats.get_stat(ms::MapleStat::STR),
                              stats.get_stat(ms::MapleStat::DEX),
                              stats.get_stat(ms::MapleStat::INT),
                              stats.get_stat(ms::MapleStat::LUK),
                              stats.get_stat(ms::MapleStat::HP),
                              stats.get_stat(ms::MapleStat::MAXHP),
                              stats.get_stat(ms::MapleStat::MP),
                              stats.get_stat(ms::MapleStat::MAXMP),
                              stats.get_stat(ms::MapleStat::AP),
                              stats.get_stat(ms::MapleStat::SP),
                              static_cast<std::uint32_t>(stats.get_exp())};
    state.character.known.fill(true);
    state.dead = state.character.values[6] == 0 ? Fact::True : Fact::False;
    state.reviveRequestable = state.dead == Fact::True && Released() ? Fact::True : Fact::False;
    state.x = pos.x();
    state.y = pos.y();
    state.facingLeft = !player.getflip();
    const bool settled =
        !player.is_attacking() && !ph.mobile() && (ph.onground || player.is_climbing() || player.is_underwater());
    state.settled = settled ? Fact::True : Fact::False;
    for (const auto& entry : *stage.get_mobs().get_mobs()) {
        const auto& mob = static_cast<const ms::Mob&>(*entry.second);
        const auto p = mob.get_position();
        MapleControl::Monster projected;
        projected.objectId = entry.first;
        projected.templateId = mob.get_template_id();
        projected.templateKnown = true;
        projected.name = mob.get_name();
        projected.x = p.x();
        projected.y = p.y();
        projected.active = mob.is_active() && mob.is_alive();
        projected.hpSequence = mob.get_hp_update_sequence();
        if (projected.hpSequence != 0) projected.hpPercent = mob.get_hp_percent();
        state.monsters.push_back(std::move(projected));
    }
    for (int type = 1; type <= 5; ++type) {
        const auto inventoryType = static_cast<ms::InventoryType::Id>(type);
        for (int slot = 1; slot <= inventory.get_slotmax(inventoryType); ++slot) {
            const auto id = inventory.get_item_id(inventoryType, slot);
            if (!id) continue;
            MapleControl::Item item;
            item.inventoryType = type;
            item.slot = slot;
            item.itemId = id;
            item.quantity = inventory.get_item_count(inventoryType, slot);
            item.quantityKnown = true;
            state.inventory.push_back(item);
        }
    }
    for (const auto& entry : stage.get_drops().get_drops()) {
        if (!entry.second->is_active()) continue;
        const auto p = entry.second->get_position();
        MapleControl::Drop drop;
        drop.objectId = entry.first;
        drop.x = p.x();
        drop.y = p.y();
        const auto& nativeDrop = static_cast<const ms::Drop&>(*entry.second);
        const auto* item = dynamic_cast<const ms::ItemDrop*>(&nativeDrop);
        if (item) {
            drop.itemId = item->get_item_id();
            drop.itemKnown = true;
        }
        drop.landed = nativeDrop.is_landed() ? Fact::True : Fact::False;
        state.drops.push_back(drop);
    }
}

bool SharedLuaAdapter::Begin(const MapleControl::Action& action, std::string& error) {
    using Kind = MapleControl::ActionKind;
    if (action.kind == Kind::Stop) {
        Release();
        return true;
    }
    if (!state.ready || (action.kind != Kind::Revive && state.character.values[6] == 0)) {
        error = "state_unavailable_or_dead";
        return false;
    }
    if (!Released()) {
        error = "action_in_progress";
        return false;
    }
    auto& stage = ms::Stage::get();
    auto& player = stage.get_player();
    result = {};
    result.reason = "native_action_dispatched";
    if (action.kind == Kind::Revive) {
        if (state.character.values[6] > 0) {
            result.effect = "confirmed";
            result.reason = "already_alive";
            result.controlReleased = true;
            result.settled = state.settled;
            return true;
        }
        // The verified server handles death only when target_id != -1; zero selects its normal return map.
        // The wheel flag stays false. Map arrival can precede the server HP update.
        ms::ChangeMapPacket(true, 0, "", false).dispatch();
        reviveCharacter = state.character.id;
        result.reason = "revive_requested";
    } else if (action.kind == Kind::Face) {
        player.set_direction(action.direction == "right");
    } else if (action.kind == Kind::UseItem) {
        if (action.itemId / 10000 != 200 && action.itemId / 10000 != 201) {
            error = "unsupported: ordinary potion or food required";
            return false;
        }
        if (player.get_inventory().get_total_item_count(action.itemId) <= 0) {
            error = "item_not_in_inventory";
            return false;
        }
        player.use_item(action.itemId);
        result.reason = "item_use_requested";
    } else if (action.kind == Kind::Equip || action.kind == Kind::Unequip) {
        const bool equipping = action.kind == Kind::Equip;
        const auto& inventory = player.get_inventory();
        const int backpackSlot = equipping ? action.sourceSlot : action.destinationSlot;
        const int equippedSignedSlot = equipping ? action.destinationSlot : action.sourceSlot;
        if (equippedSignedSlot < -ms::EquipSlot::BELT) {
            error = "unsupported: ordinary_equipment_slot_required";
            return false;
        }
        const int equippedSlot = -equippedSignedSlot;
        if (backpackSlot > inventory.get_slotmax(ms::InventoryType::EQUIP)) {
            error = "equipment_backpack_slot_out_of_range";
            return false;
        }
        const auto source = inventory.get_equip(equipping ? ms::InventoryType::EQUIP : ms::InventoryType::EQUIPPED,
                                                equipping ? backpackSlot : equippedSlot);
        const auto destination = inventory.get_equip(equipping ? ms::InventoryType::EQUIPPED : ms::InventoryType::EQUIP,
                                                     equipping ? equippedSlot : backpackSlot);
        if (!source) {
            error = "equipment_source_missing";
            return false;
        }
        if (!equipping && destination) {
            error = "equipment_destination_occupied";
            return false;
        }
        const auto& data = ms::EquipData::get(source->get_item_id());
        if (!data.is_valid() || data.get_itemdata().is_cashitem() || data.get_eqslot() == ms::EquipSlot::NONE) {
            error = "unsupported: ordinary_equipment_required";
            return false;
        }
        const bool ringSlot = data.get_eqslot() == ms::EquipSlot::RING1
                              && (equippedSlot == ms::EquipSlot::RING1 || equippedSlot == ms::EquipSlot::RING2
                                  || equippedSlot == ms::EquipSlot::RING3 || equippedSlot == ms::EquipSlot::RING4);
        if (equippedSlot != data.get_eqslot() && !ringSlot) {
            error = "equipment_slot_mismatch";
            return false;
        }
        if (player.get_look().get_alerted()) {
            error = "equipment_change_while_alerted";
            return false;
        }
        if (equipping) {
            if (destination && ms::EquipData::get(destination->get_item_id()).get_itemdata().is_cashitem()) {
                error = "unsupported: ordinary_equipment_required";
                return false;
            }
            const auto& stats = player.get_stats();
            const auto gender = data.get_itemdata().get_gender();
            if ((gender == 0 && stats.get_female()) || (gender == 1 && !stats.get_female())) {
                error = "equipment_gender_requirement";
                return false;
            }
            const auto job = stats.get_job().get_id() / 100;
            const auto requiredJob = data.get_reqstat(ms::MapleStat::JOB);
            const bool allowedJob =
                requiredJob == 0 || ((requiredJob == 1 || requiredJob == 3) && (job == 1 || job >= 20))
                || ((requiredJob == 2 || requiredJob == 3) && job == 2) || (requiredJob == 4 && job == 3)
                || (requiredJob == 8 && job == 4) || (requiredJob == 16 && job == 5);
            if (!allowedJob) {
                error = "equipment_job_requirement";
                return false;
            }
            if (data.get_reqstat(ms::MapleStat::LEVEL) > stats.get_stat(ms::MapleStat::LEVEL)) {
                error = "equipment_level_requirement";
                return false;
            }
            for (const auto& [base, total] : std::array{std::pair{ms::MapleStat::STR, ms::EquipStat::STR},
                                                        std::pair{ms::MapleStat::DEX, ms::EquipStat::DEX},
                                                        std::pair{ms::MapleStat::INT, ms::EquipStat::INT},
                                                        std::pair{ms::MapleStat::LUK, ms::EquipStat::LUK}}) {
                if (data.get_reqstat(base) > stats.get_total(total)) {
                    error = "equipment_attribute_requirement";
                    return false;
                }
            }
        }
        equipmentChange = EquipmentChange{action.sourceSlot, action.destinationSlot, source.get(),
                                          destination.get(), state.character.id,     state.sceneGeneration};
        if (equipping)
            ms::EquipItemPacket(backpackSlot, static_cast<ms::EquipSlot::Id>(equippedSlot)).dispatch();
        else {
            // EQUIPPED is an internal container (7); MOVE_ITEM uses EQUIP and a negative source slot.
            ms::MoveItemPacket(ms::InventoryType::EQUIP, action.sourceSlot, backpackSlot, 1).dispatch();
        }
        result.reason = "equipment_change_requested";
    } else {
        ms::KeyAction::Id key = ms::KeyAction::LENGTH;
        if (action.kind == Kind::Move) {
            if (action.direction == "left")
                key = ms::KeyAction::LEFT;
            else if (action.direction == "right")
                key = ms::KeyAction::RIGHT;
            else if (action.direction == "up")
                key = ms::KeyAction::UP;
            else if (action.direction == "down")
                key = ms::KeyAction::DOWN;
        } else if (action.kind == Kind::Jump)
            key = ms::KeyAction::JUMP;
        else if (action.kind == Kind::Attack) {
            if (!action.direction.empty()) player.set_direction(action.direction == "right");
            if (action.skillId != 0) {
                result.skillRequested = true;
                if (!Skill(action.skillId, result.skill, error)) return false;
                result.reason = result.skill.reason;
            } else if (action.direction.empty() && !player.can_attack()) {
                result.controlReleased = true;
                result.settled = state.settled;
                result.reason = "native_attack_not_allowed";
                return true;
            } else {
                key = ms::KeyAction::ATTACK;
            }
            if (!action.direction.empty())
                heldActions.push_back(action.direction == "left" ? ms::KeyAction::LEFT : ms::KeyAction::RIGHT);
        } else if (action.kind == Kind::Pickup)
            key = ms::KeyAction::PICKUP;
        if (key == ms::KeyAction::LENGTH && !(action.kind == Kind::Attack && action.skillId != 0)) {
            error = "unsupported: action";
            return false;
        }
        if (key != ms::KeyAction::LENGTH) heldActions.push_back(key);
        for (const auto held : heldActions) {
            stage.send_key(ms::KeyType::ACTION, held, true);
            ++inputEvents;
        }
    }
    result.dispatched = !result.skillRequested || result.skill.dispatched || !heldActions.empty();
    result.controlReleased = false;
    active = true;
    actionUntilMs = MonotonicMs() + action.durationMs;
    if (heldActions.empty() && !equipmentChange && !reviveCharacter && action.kind != Kind::Attack) ApplyRelease();
    return true;
}

void SharedLuaAdapter::ApplyRelease() {
    for (const auto held : heldActions) {
        ms::Stage::get().send_key(ms::KeyType::ACTION, held, false);
        ++inputEvents;
    }
    heldActions.clear();
    if (equipmentChange && result.reason == "equipment_change_requested")
        result.reason = "equipment_confirmation_stopped";
    equipmentChange.reset();
    if (reviveCharacter && result.reason == "revive_requested") result.reason = "revive_confirmation_stopped";
    reviveCharacter.reset();
    active = false;
    releasePending = true;
    releaseTick = currentTick;
}

void SharedLuaAdapter::Release() {
    ApplyRelease();
}

void SharedLuaAdapter::ReadCommand(bool externalActionBusy) {
    if (directory.empty()) return;
    const auto path = directory / "command.txt";
    std::ifstream input(path);
    if (!input) return;
    std::string line;
    std::getline(input, line);
    input.close();
    std::filesystem::remove(path);
    std::istringstream stream(line);
    unsigned int protocol = 0;
    std::uint64_t generation = 0;
    std::uint64_t value = 0;
    std::string instance, id, operation, scriptId, extra;
    const bool header = line.size() <= 1024
                        && static_cast<bool>(stream >> protocol >> instance >> generation >> id >> operation >> value);
    if (!header) {
        rejectedId = id;
        rejectedReason = "invalid_command";
        return;
    }
    if (id == lastConsumedId) return;
    lastConsumedId = id;
    rejectedId.clear();
    rejectedReason.clear();
    const bool identity = protocol == 1 && instance == state.instanceId && !id.empty() && id.size() <= 64
                          && id.find_first_not_of("0123456789abcdefABCDEF-") == std::string::npos;
    bool valid = identity;
    if (operation == "script") {
        stream >> scriptId;
        valid = valid && generation == state.sceneGeneration && value <= 0xffffffffULL && scriptId.size() == 32
                && scriptId.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos && !(stream >> extra)
                && state.ready;
    } else
        valid = valid && operation == "stop" && value == 0 && !(stream >> extra);
    const bool busy = operation != "stop" && (runtime.Running() || !Released() || externalActionBusy);
    if (!valid || busy) {
        rejectedId = id;
        rejectedReason = busy ? "busy" : "invalid_or_stale_command";
        if (!runtime.Running() && Released()) {
            commandId = id;
            commandStatus = "rejected";
            commandReason = rejectedReason;
        }
        return;
    }
    commandId = id;
    commandStatus = "running";
    commandReason.clear();
    if (operation == "stop") {
        runtime.Cancel("stopped");
        Release();
        scriptCommand = false;
        return;
    }
    const auto sourcePath = directory / "scripts" / (scriptId + ".lua");
    std::ifstream sourceFile(sourcePath, std::ios::binary);
    std::string source;
    bool sourceValid = false;
    if (sourceFile) {
        sourceFile.seekg(0, std::ios::end);
        const auto length = sourceFile.tellg();
        if (length >= 0 && length <= 1024 * 1024) {
            source.resize(static_cast<std::size_t>(length));
            sourceFile.seekg(0);
            sourceFile.read(source.data(), static_cast<std::streamsize>(source.size()));
            sourceValid = static_cast<bool>(sourceFile);
        }
    }
    std::string error;
    if (!sourceValid || !runtime.Start(scriptId, source, static_cast<std::uint32_t>(value), error)) {
        scriptCommand = false;
        commandStatus = "rejected";
        commandReason = error.empty() ? "script_file_unavailable" : "script_load_error";
    } else
        scriptCommand = true;
}

void SharedLuaAdapter::Tick(std::uint64_t nativeTick, bool externalActionBusy) {
    const auto generation = state.sceneGeneration;
    Capture(nativeTick);
    const bool changed = generation != state.sceneGeneration;
    if (releasePending && nativeTick > releaseTick) {
        releasePending = false;
        result.controlReleased = true;
        result.settled = state.settled;
        if (!scriptCommand && commandStatus == "running" && !runtime.Running()) {
            commandStatus = "completed";
            commandReason = "stopped";
        }
    }
    if (active && reviveCharacter) {
        if (!state.ready || state.character.id != *reviveCharacter) {
            result.reason = "revive_context_changed";
            ApplyRelease();
        } else if (state.dead == Fact::False && state.mapKnown && state.positionKnown) {
            result.effect = "confirmed";
            result.reason = "revive_confirmed";
            ApplyRelease();
        } else if (MonotonicMs() >= actionUntilMs) {
            result.reason = "revive_not_confirmed";
            ApplyRelease();
        }
    } else if (active && equipmentChange) {
        const auto& change = *equipmentChange;
        if (!state.ready || state.character.values[6] == 0 || state.character.id != change.characterId
            || state.sceneGeneration != change.sceneGeneration) {
            result.reason = "equipment_context_changed";
            ApplyRelease();
        } else {
            const auto& inventory = ms::Stage::get().get_player().get_inventory();
            const bool equipping = change.sourceSlot > 0;
            const auto source = inventory.get_equip(equipping ? ms::InventoryType::EQUIP : ms::InventoryType::EQUIPPED,
                                                    equipping ? change.sourceSlot : -change.sourceSlot);
            const auto destination =
                inventory.get_equip(equipping ? ms::InventoryType::EQUIPPED : ms::InventoryType::EQUIP,
                                    equipping ? -change.destinationSlot : change.destinationSlot);
            if (destination.get() == change.source && source.get() == change.destination) {
                result.effect = "confirmed";
                result.reason = "equipment_change_confirmed";
                ApplyRelease();
            } else if (MonotonicMs() >= actionUntilMs) {
                result.reason = "equipment_not_confirmed";
                ApplyRelease();
            }
        }
    } else if (active && (changed || !state.ready || state.character.values[6] == 0 || MonotonicMs() >= actionUntilMs))
        ApplyRelease();
    ReadCommand(externalActionBusy);
    runtime.Tick(changed);
    if (!taskTransport.Tick(runtime, state)) runtime.Cancel("task_result_write_failed");
    if (scriptCommand && !runtime.Running()) {
        const auto* script = runtime.CurrentStatus();
        commandStatus = script->status;
        commandReason = script->reason;
        scriptCommand = false;
    }
    if (!scriptCommand && commandStatus == "running" && Released() && !runtime.Running()) {
        commandStatus = "completed";
        commandReason = "stopped";
    }
    if (!directory.empty() && MonotonicMs() - lastPublishMs >= 25) {
        Publish();
        lastPublishMs = MonotonicMs();
    }
    ReadObservation();
}

Json SharedLuaAdapter::ObservationData(const std::string& domain, std::string& status, std::string& error) const {
    if (domain == "stage") {
        const auto& login = ms::login_state();
        return {{"stage", state.ready ? "IN_GAME" : "STARTING"},
                {"running", true},
                {"channel", login.channel + 1},
                {"world_id", login.world},
                {"character", state.characterKnown ? Json{{"id", state.character.id}, {"name", state.character.name}}
                                                   : Json(nullptr)},
                {"login", nullptr},
                {"channel_panel", nullptr},
                {"phase", login.phase},
                {"unavailable", state.ready ? Json::array() : Json::array({"native_client_not_ready"})}};
    }
    if (domain != "scene" && domain != "inventory" && domain != "character" && domain != "quests") {
        status = "unsupported";
        error = "unsupported_observation_domain";
        return nullptr;
    }
    if (!state.ready) {
        status = "unavailable";
        error = "native_client_not_in_game";
        return nullptr;
    }
    auto& stage = ms::Stage::get();
    auto& player = stage.get_player();
    const auto& inventory = player.get_inventory();
    if (domain == "scene") {
        Json monsters = Json::array();
        for (const auto& monster : state.monsters) {
            monsters.push_back({{"object_id", monster.objectId},
                                {"template_id", monster.templateKnown ? Json(monster.templateId) : Json(nullptr)},
                                {"name", monster.name.empty() ? Json(nullptr) : Json(monster.name)},
                                {"x", monster.x},
                                {"y", monster.y},
                                {"active", monster.active},
                                {"hp_percent", monster.hpSequence != 0 ? Json(monster.hpPercent) : Json(nullptr)},
                                {"hp_sequence", monster.hpSequence != 0 ? Json(monster.hpSequence) : Json(nullptr)},
                                {"hp_source", monster.hpSequence != 0 ? Json("server_mob_hp") : Json(nullptr)}});
        }
        Json npcs = Json::array();
        for (const auto& entry : *stage.get_npcs().get_npcs()) {
            auto& npc = static_cast<ms::Npc&>(*entry.second);
            if (!npc.is_active()) continue;
            const auto position = npc.get_position();
            npcs.push_back({{"object_id", npc.get_oid()},
                            {"template_id", npc.get_template_id()},
                            {"name", npc.get_name()},
                            {"x", position.x()},
                            {"y", position.y()}});
        }
        Json drops = Json::array();
        for (const auto& entry : stage.get_drops().get_drops()) {
            if (!entry.second->is_active()) continue;
            const auto& drop = static_cast<const ms::Drop&>(*entry.second);
            const auto position = drop.get_position();
            const auto* item = dynamic_cast<const ms::ItemDrop*>(&drop);
            const bool money = dynamic_cast<const ms::MesoDrop*>(&drop) != nullptr;
            drops.push_back({{"object_id", drop.get_oid()},
                             {"x", position.x()},
                             {"y", position.y()},
                             {"item_id", item ? Json(item->get_item_id()) : Json(nullptr)},
                             {"money", nullptr},
                             {"kind", item    ? "item"
                                      : money ? "meso"
                                              : "unknown"},
                             {"landed", drop.is_landed()}});
        }
        return {{"map_id", state.mapId},
                {"player", {{"x", state.x}, {"y", state.y}}},
                {"monsters", std::move(monsters)},
                {"npcs", std::move(npcs)},
                {"drops", std::move(drops)},
                {"player_facing", state.facingKnown ? Json(state.facingLeft ? "Left" : "Right") : Json(nullptr)},
                {"raw_flags", nullptr},
                {"pending_dynamic", false},
                {"unavailable", Json::array()},
                {"not_covered", Json::array({"drop_money_amount", "original_client_raw_flags"})}};
    }
    if (domain == "inventory") {
        Json items = Json::array();
        for (const auto& item : state.inventory)
            items.push_back({{"inventory_type", item.inventoryType},
                             {"slot", item.slot},
                             {"item_id", item.itemId},
                             {"quantity", item.quantityKnown ? Json(item.quantity) : Json(nullptr)}});
        Json equipped = Json::array();
        for (int slot = 1; slot <= 51; ++slot) {
            const auto itemId = inventory.get_item_id(ms::InventoryType::EQUIPPED, slot);
            if (itemId)
                equipped.push_back({{"inventory_type", 1}, {"slot", -slot}, {"item_id", itemId}, {"quantity", 1}});
        }
        Json capacities = Json::object();
        for (int type = 1; type <= 5; ++type)
            capacities[std::to_string(type)] = inventory.get_slotmax(static_cast<ms::InventoryType::Id>(type));
        return {{"items", std::move(items)},
                {"equipped", std::move(equipped)},
                {"capacities", std::move(capacities)},
                {"checksums_valid", nullptr},
                {"native_values_valid", true},
                {"validation_source", "native_objects"},
                {"unavailable", Json::array()},
                {"not_covered", Json::array({"cash_equipped_items", "original_client_secure_checksums"})}};
    }
    if (domain == "character") {
        const auto& skills = player.get_skills();
        Json knownSkills = Json::object();
        for (const auto& entry : skills.collect_levels()) {
            const bool hasMasterLevel = ((entry.first % 100000) / 10000 == 2);
            knownSkills[std::to_string(entry.first)] = {
                {"level", entry.second},
                {"master_level", hasMasterLevel ? Json(skills.get_masterlevel(entry.first)) : Json(nullptr)}};
        }
        return {{"character_id", player.get_oid()},
                {"mesos", inventory.get_meso()},
                {"mesos_checksum_valid", nullptr},
                {"native_values_valid", true},
                {"validation_source", "native_objects"},
                {"skills", std::move(knownSkills)},
                {"skills_complete", true},
                {"dead", FactValue(state.dead)},
                {"revive_requestable", FactValue(state.reviveRequestable)},
                {"unavailable", Json::array()},
                {"not_covered",
                 Json::array({"skill_names", "skill_requirements", "skill_effects", "skill_expirations",
                              "master_level_when_absent_from_client_records", "original_client_secure_checksums"})}};
    }
    const auto& quests = player.get_quests();
    std::map<std::uint16_t, Json> entries;
    for (const auto& entry : quests.get_started()) {
        const auto id = static_cast<std::uint16_t>(entry.first);
        entries.emplace(id, Json{{"quest_id", id}, {"state", "started"}, {"progress", entry.second}});
    }
    for (const auto& entry : quests.get_completed()) {
        const auto id = static_cast<std::uint16_t>(entry.first);
        entries.emplace(id, Json{{"quest_id", id}, {"state", "completed"}, {"progress", nullptr}});
    }
    Json records = Json::array();
    for (const auto& entry : entries) records.push_back(entry.second);
    Json linkedProgress = Json::array();
    for (const auto& entry : quests.get_in_progress())
        linkedProgress.push_back({{"quest_id", static_cast<std::uint16_t>(entry.first)},
                                  {"linked_quest_id", static_cast<std::uint16_t>(entry.second.first)},
                                  {"progress", entry.second.second}});
    return {{"quests", std::move(records)},
            {"linked_progress", std::move(linkedProgress)},
            {"source", "character_data_snapshot"},
            {"live_updates", false},
            {"unavailable", Json::array()},
            {"not_covered", Json::array({"quest_names", "quest_requirements", "progress_string_semantics",
                                         "available_quests", "linked_progress_semantics", "live_quest_updates"})}};
}

void SharedLuaAdapter::ReadObservation() {
    if (directory.empty()) return;
    const auto path = directory / "observation-request.txt";
    std::ifstream input(path);
    if (!input) return;
    std::string line;
    std::getline(input, line);
    input.close();
    std::filesystem::remove(path);
    std::istringstream fields(line);
    unsigned int protocol = 0;
    std::string instance, requestId, domain, extra;
    const bool valid = line.size() <= 1024 && static_cast<bool>(fields >> protocol >> instance >> requestId >> domain)
                       && !(fields >> extra) && protocol == 1 && instance == state.instanceId && requestId.size() == 32
                       && requestId.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos;
    std::string status = "ok";
    std::string error;
    Json data;
    if (!valid) {
        status = "unavailable";
        error = "invalid_or_foreign_observation_request";
    } else
        data = ObservationData(domain, status, error);
    const Json response = {{"protocol", 1},
                           {"instance_id", state.instanceId},
                           {"run_id", runId},
                           {"request_id", requestId},
                           {"domain", domain},
                           {"seq", state.sequence},
                           {"scene_generation", state.sceneGeneration},
                           {"observed_at_ms", state.observedAtMs},
                           {"status", status},
                           {"data", std::move(data)},
                           {"error", error.empty() ? Json(nullptr) : Json(error)}};
    const auto temporary = directory / "observation.tmp";
    {
        std::ofstream output(temporary);
        if (!output) {
            std::cerr << "Cannot publish native observation response\n";
            return;
        }
        output << response.dump(-1, ' ', false, Json::error_handler_t::replace) << '\n';
        if (!output) {
            std::cerr << "Cannot write native observation response\n";
            return;
        }
    }
    std::error_code failure;
    std::filesystem::rename(temporary, directory / "observation.json", failure);
    if (failure) std::cerr << "Cannot replace native observation response: " << failure.message() << '\n';
}

void SharedLuaAdapter::Shutdown() {
    runtime.Cancel("session_closing");
    ApplyRelease();
    // The process is leaving the native game: no successor script can reuse its controls.
    releasePending = false;
    result.controlReleased = true;
    result.settled = Fact::Unknown;
    state.ready = state.inGame = false;
    state.dead = state.reviveRequestable = Fact::Unknown;
    state.observedAtMs = UnixMs();
    ++state.sequence;
    runtime.Tick();
    if (scriptCommand) {
        const auto* script = runtime.CurrentStatus();
        commandStatus = script->status;
        commandReason = script->reason;
        scriptCommand = false;
    }
    Publish();
}

bool SharedLuaAdapter::Logs(const std::string& scriptId, const std::vector<std::string>& lines) {
    if (directory.empty()) return true;
    std::ofstream output(directory / "script-events.jsonl", std::ios::app);
    if (!output) return false;
    for (const auto& line : lines)
        output << Json{{"script_id", scriptId}, {"at_ms", MonotonicMs()}, {"text", line}}.dump() << '\n';
    return static_cast<bool>(output);
}

Json SharedLuaAdapter::StateDocument() const {
    Json document = {
        {"protocol", 1},
        {"backend", "headless"},
        {"instance_id", state.instanceId},
        {"pid", getpid()},
        {"run_id", runId},
        {"seq", state.sequence},
        {"observed_at_ms", state.observedAtMs},
        {"scene_generation", state.sceneGeneration},
        {"ready", state.ready},
        {"dead", FactValue(state.dead)},
        {"revive_requestable", FactValue(state.reviveRequestable)},
        {"map_id", state.mapKnown ? Json(state.mapId) : Json(nullptr)},
        {"held_keys", Json::array()},
        {"held_actions", Json::array()},
        {"command",
         {{"id", commandId.empty() ? Json(nullptr) : Json(commandId)},
          {"status", commandStatus},
          {"reason", commandReason.empty() ? Json(nullptr) : Json(commandReason)}}},
        {"rejected_command", rejectedReason.empty()
                                 ? Json(nullptr)
                                 : Json{{"id", rejectedId}, {"status", "rejected"}, {"reason", rejectedReason}}},
        {"script", ScriptDocument(runtime.CurrentStatus())},
        {"last_skill", nullptr},
        {"input_events", inputEvents},
        {"capabilities",
         {{"move", true},
          {"face", true},
          {"jump", true},
          {"attack", true},
          {"attack_move", true},
          {"pickup", true},
          {"use_item", true},
          {"equip", true},
          {"unequip", true},
          {"revive", true},
          {"stop", true},
          {"raw_keys", false},
          {"skill", true},
          {"monster_hp_percent", true}}},
        {"action_result",
         {{"dispatched", result.dispatched},
          {"control_released", result.controlReleased},
          {"settled", FactValue(result.settled)},
          {"effect", result.effect},
          {"reason", result.reason}}}};
    if (lastSkill)
        document["last_skill"] = {{"skill_id", lastSkill->id},
                                  {"native_result", lastSkill->result.nativeResult},
                                  {"dispatched", lastSkill->result.dispatched},
                                  {"reason", lastSkill->result.reason}};
    if (result.skillRequested) {
        document["action_result"]["skill_dispatched"] = result.skill.dispatched;
        document["action_result"]["skill_native_result"] = result.skill.nativeResult;
        document["action_result"]["skill_reason"] = result.skill.reason;
    }
    for (const auto key : heldActions) {
        switch (key) {
        case ms::KeyAction::LEFT:
            document["held_actions"].push_back("Left");
            break;
        case ms::KeyAction::RIGHT:
            document["held_actions"].push_back("Right");
            break;
        case ms::KeyAction::UP:
            document["held_actions"].push_back("Up");
            break;
        case ms::KeyAction::DOWN:
            document["held_actions"].push_back("Down");
            break;
        case ms::KeyAction::ATTACK:
            document["held_actions"].push_back("Attack");
            break;
        case ms::KeyAction::JUMP:
            document["held_actions"].push_back("Jump");
            break;
        case ms::KeyAction::PICKUP:
            document["held_actions"].push_back("Pickup");
            break;
        default:
            break;
        }
    }
    document["character"] = nullptr;
    if (state.characterKnown) {
        Json character = {{"id", state.character.id}, {"name", state.character.name}};
        const std::array<const char*, 13> names{
            "level",  "job", "strength", "dexterity",      "intelligence", "luck",      "hp",
            "max_hp", "mp",  "max_mp",   "ability_points", "skill_points", "experience"};
        for (std::size_t i = 0; i < names.size(); ++i)
            character[names[i]] = state.character.known[i] ? Json(state.character.values[i]) : Json(nullptr);
        document["character"] = std::move(character);
    }
    document["position"] = state.positionKnown ? Json{{"x", state.x}, {"y", state.y}} : Json(nullptr);
    document["facing"] = state.facingKnown ? Json(state.facingLeft ? "Left" : "Right") : Json(nullptr);
    document["monsters"] = state.monstersKnown ? Json::array() : Json(nullptr);
    for (const auto& mob : state.monsters)
        document["monsters"].push_back({{"object_id", mob.objectId},
                                        {"template_id", mob.templateKnown ? Json(mob.templateId) : Json(nullptr)},
                                        {"name", mob.name.empty() ? Json(nullptr) : Json(mob.name)},
                                        {"x", mob.x},
                                        {"y", mob.y},
                                        {"active", mob.active},
                                        {"hp_percent", mob.hpSequence != 0 ? Json(mob.hpPercent) : Json(nullptr)},
                                        {"hp_sequence", mob.hpSequence != 0 ? Json(mob.hpSequence) : Json(nullptr)},
                                        {"hp_source", mob.hpSequence != 0 ? Json("server_mob_hp") : Json(nullptr)}});
    document["inventory"] = state.inventoryKnown ? Json::array() : Json(nullptr);
    for (const auto& item : state.inventory)
        document["inventory"].push_back({{"inventory_type", item.inventoryType},
                                         {"slot", item.slot},
                                         {"item_id", item.itemId},
                                         {"quantity", item.quantityKnown ? Json(item.quantity) : Json(nullptr)}});
    document["drops"] = state.dropsKnown ? Json::array() : Json(nullptr);
    for (const auto& drop : state.drops)
        document["drops"].push_back({{"object_id", drop.objectId},
                                     {"x", drop.x},
                                     {"y", drop.y},
                                     {"item_id", drop.itemKnown ? Json(drop.itemId) : Json(nullptr)},
                                     {"money", drop.moneyKnown ? Json(drop.money) : Json(nullptr)},
                                     {"landed", FactValue(drop.landed)}});
    return document;
}

void SharedLuaAdapter::Publish() {
    if (directory.empty()) return;
    const auto temporary = directory / "state.tmp";
    {
        std::ofstream output(temporary);
        if (!output) throw std::runtime_error("cannot publish bridge state");
        output << StateDocument().dump(-1, ' ', false, Json::error_handler_t::replace) << '\n';
        if (!output) throw std::runtime_error("cannot write bridge state");
    }
    std::filesystem::rename(temporary, directory / "state.json");
}
