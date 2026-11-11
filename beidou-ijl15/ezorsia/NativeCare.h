// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Runtime.h"
#include "NativeMouseInput.h"

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace BeiDouBridge {

struct CareRect {
    int x = 0, y = 0, width = 0, height = 0;

    bool Contains(int px, int py) const { return px >= x && py >= y && px < x + width && py < y + height; }
};

struct CareButton {
    unsigned id = 0;
    CareRect rect;
    bool enabledKnown = false;
    bool enabled = false;
};

struct CareWindow {
    std::uint32_t address = 0;
    std::string identity;
    std::string name;
    CareRect rect;
    bool geometryKnown = false;
    bool sceneLayer = false;
    std::vector<CareButton> buttons;
    bool skillsKnown = false;
    std::vector<unsigned> skills;
    int firstIndex = 0, selectedTab = 0, tabCount = 0;
    bool inventoryKnown = false, expanded = false;
    int firstSlot = 0, inventoryType = 0;
};

struct CareEquipment {
    unsigned itemId = 0;
    std::string reference;
    bool ordinaryKnown = false, ordinary = false;
    std::vector<int> bodySlots;
};

struct CareView {
    bool known = false;
    bool blocked = false;
    bool gameFocused = false;
    std::uint32_t focusedWindow = 0;
    std::uint32_t nativeUser = 0;
    std::uint32_t characterId = 0;
    std::uint64_t sceneGeneration = 0;
    std::uint32_t dragObject = 0;
    int dragInventoryType = 0, dragSlot = 0;
    int width = 0, height = 0;
    std::vector<CareWindow> windows;
    std::vector<std::pair<int, int>> npcs;
    bool sceneKnown = false;
    bool skillsKnown = false;
    unsigned skillLevel = 0;
    unsigned skillMaximum = 0;
    bool inventoryKnown = false;
    std::map<int, CareEquipment> inventory;
};

// The native host supplies current facts and bounded native input primitives.
// This GUI-only workflow shares Allocation's per-point confirmation with headless.
class NativeCare {
public:
    bool Begin(const MapleControl::Action& request, const MapleControl::State& state, const CareView& view,
               std::uint64_t now) {
        if (active || CleanupPending()) return false;
        action = request;
        character = state.character.id;
        job = state.character.values[1];
        generation = state.sceneGeneration;
        nativeUser = view.nativeUser;
        windowName = request.kind == MapleControl::ActionKind::AllocateAp   ? "stats"
                     : request.kind == MapleControl::ActionKind::AllocateSp ? "skills"
                     : request.kind == MapleControl::ActionKind::Equip      ? "inventory"
                                                                            : request.reference;
        active = true;
        allocationFinishing = false;
        cancelReason.clear();
        scopeFinished = false;
        allocationStarted = request.kind == MapleControl::ActionKind::AllocateAp
                            || request.kind == MapleControl::ActionKind::AllocateSp;
        equipmentStarted = request.kind == MapleControl::ActionKind::Equip;
        sourceEquipment = destinationEquipment = CareEquipment{};
        equipmentBaselineKnown = false;
        equipmentQueued = equipmentInputStarted = mouseStopRequested = escapeSent = false;
        cleanupSettled = true;
        ownedDrag = 0;
        toggleSent = focusSent = false;
        activation = 0;
        windowAddress = 0;
        windowIdentity.clear();
        tabs.clear();
        expectedTab = oldFirst = -1;
        scrollDirection = 0;
        result = {};
        result.sessionId = request.sessionId;
        deadline = now + (allocationStarted ? 6000 : request.durationMs);
        if (allocationStarted) {
            allocation.Start(request.allocation, Facts(state, view));
            ProjectAllocation();
            if (!allocation.Active()) {
                active = false;
                return true;
            }
        }
        if (equipmentStarted) {
            const auto source = view.inventory.find(request.sourceSlot);
            const auto destination = view.inventory.find(request.destinationSlot);
            equipmentBaselineKnown = EquipmentFactsKnown(view);
            if (source != view.inventory.end()) sourceEquipment = source->second;
            if (destination != view.inventory.end()) destinationEquipment = destination->second;
            ProjectEquipment(view);
            if (!equipmentBaselineKnown)
                Stop("equipment_inventory_unavailable");
            else if (source == view.inventory.end())
                Stop("equipment_source_missing");
            else if (request.destinationSlot < -19 || request.destinationSlot >= 0)
                Stop("unsupported: ordinary_equipment_slot_required");
            else if (!source->second.ordinaryKnown || !source->second.ordinary || source->second.reference.empty())
                Stop("unsupported: ordinary_equipment_required");
            else if (!request.reference.empty() && request.reference != source->second.reference)
                Stop("equipment_reference_expired");
            else if (source->second.bodySlots.size() != 1 || source->second.bodySlots[0] != request.destinationSlot)
                Stop("unsupported: equipment_destination_ambiguous_or_mismatched");
            else if (destination != view.inventory.end()
                     && (!destination->second.ordinaryKnown || !destination->second.ordinary
                         || destination->second.reference.empty()))
                Stop("unsupported: ordinary_equipment_required");
            else {
                sourceEquipment = source->second;
                destinationEquipment = destination == view.inventory.end() ? CareEquipment{} : destination->second;
                ProjectEquipment(view);
            }
        }
        if (active && view.dragObject != 0) Cancel(state, view, now, "care_drag_open");
        return true;
    }

    template <class Mouse, class Key>
    void Tick(const MapleControl::State& state, const CareView& view, std::uint64_t now, bool inputReleased,
              const Mouse& mouse, const Key& key) {
        if (!active) return;
        if (!ContextMatches(state, view) || state.character.values[6] == 0) {
            Cancel(state, view, now, "care_context_changed");
            return;
        }
        if (!view.known || view.blocked) {
            Cancel(state, view, now, view.blocked ? "care_dialog_or_drag_open" : "care_ui_unavailable", inputReleased);
            return;
        }
        if (equipmentStarted && equipmentQueued) {
            ObserveCleanup(state, view);
            ProjectEquipment(view);
            if (!EquipmentFactsKnown(view)) {
                Stop("equipment_inventory_unavailable");
                mouseStopRequested = true;
                return;
            }
            if (EquipmentConfirmed(view)) {
                result.effect = "confirmed";
                Stop("equipment_change_confirmed");
                return;
            }
            if (!EquipmentUnchanged(view)) mouseStopRequested = true;
            if (now >= deadline) {
                Stop("equipment_not_confirmed");
                mouseStopRequested = true;
            }
            return;
        }
        if (allocationStarted && allocation.Pending()) {
            if (!inputReleased) {
                if (now >= pointDeadline) Cancel(state, view, now, "allocation_input_not_released", false);
                return;
            }
            const auto before = allocation.Allocated();
            allocation.Tick(Facts(state, view), now);
            if (allocation.Allocated() != before) deadline = now + 6000;
            ProjectAllocation();
            if (!allocation.Active()) active = false;
            return;
        }
        if (!inputReleased) return;
        if (view.dragObject != 0) {
            Cancel(state, view, now, "care_drag_open");
            return;
        }
        if (now >= deadline) {
            Cancel(state, view, now, "care_window_not_confirmed");
            return;
        }
        if (windowName == "game") {
            if (FocusGame(view, mouse)) FinishWindow(view, "game_focus_confirmed");
            return;
        }
        const CareWindow* window = nullptr;
        for (const auto& item : view.windows)
            if (item.name == windowName) {
                if (window != nullptr) {
                    Stop("care_window_ambiguous");
                    return;
                }
                window = &item;
            }
        if (window != nullptr && windowAddress != 0
            && (window->address != windowAddress || window->identity != windowIdentity)) {
            Cancel(state, view, now, "care_window_changed");
            return;
        }
        if (!allocationStarted && !equipmentStarted && action.direction == "close") {
            if (window == nullptr) {
                FinishWindow(view, "window_closed");
                return;
            }
            Remember(*window);
            if (!toggleSent && FocusGame(view, mouse)) {
                toggleSent = true;
                if (!key(WindowKey())) Stop("care_key_unavailable");
            }
            return;
        }
        if (window == nullptr) {
            if (windowAddress != 0) {
                Cancel(state, view, now, "care_window_changed");
                return;
            }
            if (!toggleSent && FocusGame(view, mouse)) {
                toggleSent = true;
                if (!key(WindowKey())) Stop("care_key_unavailable");
            }
            return;
        }
        Remember(*window);
        const int expectedWidth = windowName == "stats" ? 210 : 175;
        const int expectedHeight = windowName == "stats" ? 348 : 289;
        if (!window->geometryKnown || window->rect.width != expectedWidth || window->rect.height != expectedHeight) {
            Stop("care_layout_unverified");
            return;
        }
        if (view.focusedWindow != window->address) {
            if (activation == window->address) {
                Stop("care_window_focus_not_confirmed");
                return;
            }
            activation = window->address;
            for (int x = 20; x < expectedWidth - 30; x += 10)
                if (Visible(view, *window, x, 12)) {
                    Click(view, *window, x, 12, mouse);
                    return;
                }
            Stop("care_window_occluded");
            return;
        }
        if (equipmentStarted) {
            EquipmentInput(view, *window, mouse);
            return;
        }
        if (!allocationStarted) {
            FinishWindow(view, "window_open_confirmed");
            return;
        }
        const CareButton* button = nullptr;
        if (action.allocation.skill) {
            if (!SkillButton(view, *window, mouse, button)) return;
        } else {
            const auto id = 2002 + MapleControl::Allocation::AttributeIndex(action.allocation.stat);
            button = Button(*window, id);
        }
        auto facts = Facts(state, view);
        if (button == nullptr || !button->enabledKnown)
            facts.refusal = "allocation_button_unavailable";
        else if (!button->enabled)
            facts.refusal = "allocation_not_enabled";
        allocation.Tick(facts, now, false);
        if (allocation.Active() && button != nullptr && button->enabledKnown && button->enabled) {
            const int x = button->rect.x + button->rect.width / 2;
            const int y = button->rect.y + button->rect.height / 2;
            if (!Click(view, *window, x, y, mouse, true)) allocation.Cancel(Facts(state, view), now);
        }
        ProjectAllocation();
        active = allocation.Active();
        // Every next point gets a fresh bounded window/skill positioning budget.
        deadline = now + 6000;
    }

    void Cancel(const MapleControl::State& state, const CareView& view, std::uint64_t now,
                const std::string& why = "care_cancelled", bool mayConfirm = true) {
        if (!active) return;
        if (allocationStarted) {
            cancelReason = why;
            allocationFinishing = allocation.Pending() && !mayConfirm && ContextMatches(state, view);
            if (!allocationFinishing) allocation.Cancel(Facts(state, view), now, mayConfirm);
            ProjectAllocation();
            if (!allocation.Confirmed()) result.reason = why;
        } else
            result.reason = why;
        if (equipmentStarted) {
            ProjectEquipment(view);
            ObserveCleanup(state, view);
        }
        active = false;
    }

    bool Active() const { return active; }

    void ConvergeCancellation(const MapleControl::State& state, const CareView& view, std::uint64_t now,
                              bool inputReleased) {
        if (!allocationFinishing) return;
        const bool sameContext = ContextMatches(state, view);
        if (!inputReleased && sameContext) return;
        // Dispatch remains stopped. One fresh read at real release retains any
        // point whose target and pool have both been observed, without a retry.
        allocation.Cancel(Facts(state, view), now, sameContext);
        allocationFinishing = false;
        ProjectAllocation();
        if (!allocation.Confirmed()) result.reason = cancelReason;
    }

    static bool AllowsTarget(const CareView& view, const NativeMouseInput::Target& target) {
        if (!view.known || view.blocked || target.x < 0 || target.y < 0 || target.x >= view.width
            || target.y >= view.height)
            return false;
        if (target.window == 0) {
            if (!view.sceneKnown) return false;
            for (const auto& window : view.windows)
                if (!window.sceneLayer
                    && (!window.geometryKnown
                        || CareRect{window.rect.x - 8, window.rect.y - 8, window.rect.width + 16,
                                    window.rect.height + 16}
                               .Contains(target.x, target.y)))
                    return false;
            for (const auto& npc : view.npcs)
                if (target.x >= npc.first - 70 && target.x <= npc.first + 70 && target.y >= npc.second - 130
                    && target.y <= npc.second + 25)
                    return false;
            return true;
        }
        bool found = false;
        for (const auto& window : view.windows) {
            if (window.address == target.window) {
                if (!window.geometryKnown || !window.rect.Contains(target.x, target.y)) return false;
                found = true;
                continue;
            }
            if (found && !window.sceneLayer && (!window.geometryKnown || window.rect.Contains(target.x, target.y)))
                return false;
        }
        return found;
    }

    static bool CancelPoint(const CareView& view, std::uint32_t window, int& x, int& y) {
        if (view.width < 2 || view.height < 2) return false;
        for (const auto& item : view.windows)
            if (item.address == window && item.geometryKnown) {
                const CareRect outside{item.rect.x - 8, item.rect.y - 8, item.rect.width + 16, item.rect.height + 16};
                for (const auto& point : {std::pair<int, int>{1, 1},
                                          {view.width - 2, 1},
                                          {1, view.height - 2},
                                          {view.width - 2, view.height - 2}})
                    if (!outside.Contains(point.first, point.second)) {
                        x = point.first;
                        y = point.second;
                        return true;
                    }
            }
        return false;
    }

    bool StopMouse() const { return mouseStopRequested; }

    bool DispatchEquipment(const MapleControl::State& state, const CareView& view,
                           const NativeMouseInput::Target& target) {
        if (!active || !equipmentStarted || !equipmentQueued || !ContextMatches(state, view) || !view.known
            || view.blocked || !EquipmentFactsKnown(view) || !EquipmentUnchanged(view))
            return false;
        for (const auto& window : view.windows)
            if (window.address == windowAddress && window.identity == windowIdentity) {
                const int index = action.sourceSlot - window.firstSlot;
                if (!window.inventoryKnown || window.inventoryType != 1 || window.expanded || index < 0 || index >= 24
                    || target.x != window.rect.x + 24 + index % 4 * 36
                    || target.y != window.rect.y + 66 + index / 4 * 34
                    || !Visible(view, window, target.x - window.rect.x, target.y - window.rect.y))
                    return false;
                equipmentInputStarted = true;
                cleanupSettled = false;
                result.reason = "equipment_change_requested";
                return true;
            }
        return false;
    }

    void ObserveCleanup(const MapleControl::State& state, const CareView& view) {
        if (scopeFinished) return;
        if (!equipmentStarted || !equipmentInputStarted) {
            cleanupSettled = true;
            return;
        }
        if (!ContextMatches(state, view)) {
            cleanupSettled = true;
            return;
        }
        if (!view.known) {
            cleanupSettled = false;
            return;
        }
        if (view.dragObject == 0) {
            cleanupSettled = true;
            return;
        }
        if (view.dragInventoryType == 1 && view.dragSlot == action.sourceSlot) {
            if (ownedDrag == 0) ownedDrag = view.dragObject;
            cleanupSettled = ownedDrag != view.dragObject;
        } else
            cleanupSettled = true;
    }

    bool CleanupPending() const { return !active && (!cleanupSettled || allocationFinishing); }

    void FinishScope() {
        if (!active && !CleanupPending()) scopeFinished = true;
    }

    bool ReleasePending(bool keys, bool mouse) const { return !active && (keys || mouse || CleanupPending()); }

    bool CanEscape(const CareView& view) const {
        return CleanupPending() && !escapeSent && !view.blocked && view.dragObject == ownedDrag && ownedDrag != 0;
    }

    void EscapeSent() { escapeSent = true; }

    bool DispatchPoint(const MapleControl::State& state, const CareView& view, const NativeMouseInput::Target& target,
                       std::uint64_t now) {
        if (!active || !allocationStarted || allocation.Pending() || !state.ready || !view.known || view.blocked
            || state.character.id != character || state.sceneGeneration != generation || view.nativeUser != nativeUser)
            return false;
        for (const auto& window : view.windows)
            if (window.address == windowAddress && window.identity == windowIdentity) {
                unsigned id = 2002 + MapleControl::Allocation::AttributeIndex(action.allocation.stat);
                if (action.allocation.skill) {
                    const auto found = std::find(window.skills.begin(), window.skills.end(), action.allocation.skillId);
                    if (found == window.skills.end()) return false;
                    const int row = static_cast<int>(found - window.skills.begin()) - window.firstIndex;
                    if (row < 0 || row >= 4) return false;
                    id = 2010 + row;
                }
                const auto* button = Button(window, id);
                if (button == nullptr || !button->enabledKnown || !button->enabled
                    || target.x != window.rect.x + button->rect.x + button->rect.width / 2
                    || target.y != window.rect.y + button->rect.y + button->rect.height / 2
                    || !Visible(view, window, target.x - window.rect.x, target.y - window.rect.y))
                    return false;
                const bool dispatch = allocation.Tick(Facts(state, view), now);
                ProjectAllocation();
                active = allocation.Active();
                if (dispatch) pointDeadline = now + action.allocation.timeoutMs;
                return dispatch;
            }
        return false;
    }

    const MapleControl::Action& Request() const { return action; }

    MapleControl::ActionResult Result() const { return result; }

private:
    bool EquipmentFactsKnown(const CareView& view) const {
        if (!view.inventoryKnown) return false;
        for (int slot : {action.sourceSlot, action.destinationSlot}) {
            const auto entry = view.inventory.find(slot);
            if (entry != view.inventory.end() && (entry->second.reference.empty() || !entry->second.ordinaryKnown))
                return false;
        }
        return true;
    }

    bool ContextMatches(const MapleControl::State& state, const CareView& view) const {
        return state.ready && state.characterKnown && state.character.id == character
               && state.sceneGeneration == generation && view.nativeUser == nativeUser
               && (!(allocationStarted || equipmentStarted) || state.character.values[1] == job);
    }

    static std::string SlotReference(const CareView& view, int slot) {
        const auto found = view.inventory.find(slot);
        return found == view.inventory.end() ? "" : found->second.reference;
    }

    bool EquipmentUnchanged(const CareView& view) const {
        return SlotReference(view, action.sourceSlot) == sourceEquipment.reference
               && SlotReference(view, action.destinationSlot) == destinationEquipment.reference;
    }

    bool EquipmentConfirmed(const CareView& view) const {
        return !sourceEquipment.reference.empty()
               && SlotReference(view, action.sourceSlot) == destinationEquipment.reference
               && SlotReference(view, action.destinationSlot) == sourceEquipment.reference;
    }

    void ProjectEquipment(const CareView& view) {
        using Value = MapleControl::Value;
        result.equipment = Value::Object(
            {{"source_slot", action.sourceSlot},
             {"destination_slot", action.destinationSlot},
             {"character_id", character},
             {"scene_generation", generation},
             {"current_character_id", view.characterId != 0 ? Value(view.characterId) : Value()},
             {"current_scene_generation", view.sceneGeneration},
             {"source_item_id", sourceEquipment.itemId != 0 ? Value(sourceEquipment.itemId) : Value()},
             {"requested_ref", action.reference.empty() ? Value() : Value(action.reference)},
             {"source_ref_before", equipmentBaselineKnown ? Value(sourceEquipment.reference) : Value()},
             {"destination_ref_before", equipmentBaselineKnown ? Value(destinationEquipment.reference) : Value()},
             {"source_ref_after", EquipmentFactsKnown(view) ? Value(SlotReference(view, action.sourceSlot)) : Value()},
             {"destination_ref_after",
              EquipmentFactsKnown(view) ? Value(SlotReference(view, action.destinationSlot)) : Value()}});
    }

    template <class Mouse> void EquipmentInput(const CareView& view, const CareWindow& window, const Mouse& mouse) {
        if (!EquipmentFactsKnown(view) || !EquipmentUnchanged(view)) {
            Stop("equipment_objects_changed");
            return;
        }
        if (!window.inventoryKnown || window.expanded) {
            Stop("equipment_inventory_layout_unavailable");
            return;
        }
        if (expectedTab != -1) {
            if (window.inventoryType != 1) {
                Stop("equipment_tab_not_confirmed");
                return;
            }
            expectedTab = -1;
        }
        if (window.inventoryType != 1) {
            expectedTab = 1;
            Click(view, window, 19, 34, mouse);
            return;
        }
        if (oldFirst != -1) {
            const bool advanced = scrollDirection > 0 ? window.firstSlot > oldFirst : window.firstSlot < oldFirst;
            oldFirst = -1;
            if (!advanced) {
                Stop("equipment_scroll_not_confirmed");
                return;
            }
        }
        const int index = action.sourceSlot - window.firstSlot;
        if (index < 0 || index >= 24) {
            NativeMouseInput::Target target;
            target.x = window.rect.x + 80;
            target.y = window.rect.y + 90;
            target.clicks = 0;
            target.wheel = index < 0 ? 120 : -120;
            target.character = nativeUser;
            target.scene = generation;
            target.window = window.address;
            oldFirst = window.firstSlot;
            scrollDirection = index < 0 ? -1 : 1;
            if (!Visible(view, window, 80, 90) || !mouse(target)) Stop("equipment_scroll_unavailable");
            return;
        }
        const int x = 24 + index % 4 * 36, y = 66 + index / 4 * 34;
        if (!Visible(view, window, x, y)) {
            Stop("equipment_slot_occluded");
            return;
        }
        NativeMouseInput::Target target;
        target.x = window.rect.x + x;
        target.y = window.rect.y + y;
        target.clicks = 2;
        target.character = nativeUser;
        target.scene = generation;
        target.window = window.address;
        target.equipment = true;
        equipmentQueued = true;
        if (!mouse(target)) Stop("equipment_mouse_unavailable");
    }

    MapleControl::AllocationFacts Facts(const MapleControl::State& state, const CareView& view) const {
        MapleControl::AllocationFacts facts;
        facts.instanceId = state.instanceId;
        facts.characterId = state.character.id;
        facts.sceneGeneration = state.sceneGeneration;
        facts.job = state.character.values[1];
        facts.known = state.ready && state.characterKnown && state.character.values[6] != 0;
        for (unsigned index = 0; index < 4; ++index) facts.attributes[index] = state.character.values[index + 2];
        if (action.allocation.skill) {
            facts.known = facts.known && view.skillsKnown;
            facts.points = state.character.values[11];
            facts.value = view.skillLevel;
            facts.maximum = view.skillMaximum;
            if (facts.job < 100 || facts.job >= 600 || action.allocation.skillId / 10000 == 0)
                facts.refusal = "unsupported: allocation_sp_pool";
        } else {
            facts.points = state.character.values[10];
            facts.value = facts.attributes[MapleControl::Allocation::AttributeIndex(action.allocation.stat)];
        }
        return facts;
    }

    void ProjectAllocation() {
        result.allocation = allocation.Report();
        result.reason = allocation.Reason();
        result.effect = allocation.Confirmed() ? "confirmed" : "unknown";
    }

    void Stop(const std::string& why) {
        active = false;
        result.reason = why;
    }

    void Remember(const CareWindow& window) {
        windowAddress = window.address;
        windowIdentity = window.identity;
    }

    unsigned WindowKey() const { return windowName == "stats" ? 'S' : windowName == "skills" ? 'K' : 'I'; }

    void FinishWindow(const CareView& view, const std::string& why) {
        result.effect = "confirmed";
        result.reason = why;
        result.ui = MapleControl::Value::Object({{"window", windowName},
                                                 {"open", action.direction != "close"},
                                                 {"game_focused", view.gameFocused},
                                                 {"instance_ref", windowIdentity}});
        active = false;
    }

    static const CareButton* Button(const CareWindow& window, unsigned id) {
        const CareButton* found = nullptr;
        for (const auto& button : window.buttons)
            if (button.id == id) {
                if (found != nullptr) return nullptr;
                found = &button;
            }
        return found;
    }

    static bool Visible(const CareView& view, const CareWindow& window, int x, int y) {
        if (!window.geometryKnown || x < 0 || y < 0 || x >= window.rect.width || y >= window.rect.height) return false;
        NativeMouseInput::Target target;
        target.window = window.address;
        target.x = window.rect.x + x;
        target.y = window.rect.y + y;
        return AllowsTarget(view, target);
    }

    template <class Mouse>
    bool Click(const CareView& view, const CareWindow& window, int x, int y, const Mouse& mouse, bool point = false) {
        if (!Visible(view, window, x, y)) {
            Stop("care_target_occluded");
            return false;
        }
        NativeMouseInput::Target target;
        target.x = window.rect.x + x;
        target.y = window.rect.y + y;
        target.character = nativeUser;
        target.scene = generation;
        target.window = window.address;
        target.point = point;
        if (!mouse(target)) {
            Stop("care_mouse_unavailable");
            return false;
        }
        return true;
    }

    template <class Mouse> bool FocusGame(const CareView& view, const Mouse& mouse) {
        if (view.gameFocused) return true;
        if (focusSent) {
            Stop("care_game_focus_not_confirmed");
            return false;
        }
        if (!view.sceneKnown) {
            Stop("care_scene_unavailable");
            return false;
        }
        for (int y : {110, 190, 290, 390, 490})
            for (int x : {320, 480, 640, 800, 960, 1120}) {
                if (x >= view.width - 20 || y >= view.height - 120) continue;
                bool blocked = false;
                for (const auto& window : view.windows)
                    if (!window.sceneLayer
                        && (!window.geometryKnown
                            || CareRect{window.rect.x - 8, window.rect.y - 8, window.rect.width + 16,
                                        window.rect.height + 16}
                                   .Contains(x, y)))
                        blocked = true;
                for (const auto& npc : view.npcs)
                    if (x >= npc.first - 70 && x <= npc.first + 70 && y >= npc.second - 130 && y <= npc.second + 25)
                        blocked = true;
                if (blocked) continue;
                NativeMouseInput::Target target;
                target.x = x;
                target.y = y;
                target.character = nativeUser;
                target.scene = generation;
                focusSent = true;
                if (!mouse(target)) Stop("care_mouse_unavailable");
                return false;
            }
        Stop("care_game_focus_blocked");
        return false;
    }

    template <class Mouse>
    bool SkillButton(const CareView& view, const CareWindow& window, const Mouse& mouse, const CareButton*& button) {
        if (!window.skillsKnown || window.tabCount < 1 || window.tabCount > 5) {
            Stop("care_skills_unavailable");
            return false;
        }
        if (expectedTab != -1) {
            if (window.selectedTab != expectedTab) {
                Stop("care_skill_tab_not_confirmed");
                return false;
            }
            expectedTab = -1;
        }
        if (oldFirst != -1) {
            const bool advanced = scrollDirection > 0 ? window.firstIndex > oldFirst : window.firstIndex < oldFirst;
            oldFirst = -1;
            if (!advanced) {
                Stop("care_skill_scroll_not_confirmed");
                return false;
            }
        }
        const auto found = std::find(window.skills.begin(), window.skills.end(), action.allocation.skillId);
        if (found == window.skills.end()) {
            tabs.insert(window.selectedTab);
            for (int tab = 0; tab < window.tabCount; ++tab)
                if (tabs.count(tab) == 0) {
                    expectedTab = tab;
                    Click(view, window, 19 + tab * 35, 34, mouse);
                    return false;
                }
            Stop("skill_not_in_ui");
            return false;
        }
        const int index = static_cast<int>(found - window.skills.begin());
        const int row = index - window.firstIndex;
        if (row < 0 || row >= 4) {
            NativeMouseInput::Target target;
            target.x = window.rect.x + 100;
            target.y = window.rect.y + 130;
            target.clicks = 0;
            target.wheel = row < 0 ? 120 : -120;
            target.character = nativeUser;
            target.scene = generation;
            target.window = window.address;
            oldFirst = window.firstIndex;
            scrollDirection = row < 0 ? -1 : 1;
            if (!Visible(view, window, 100, 130) || !mouse(target)) Stop("care_skill_scroll_unavailable");
            return false;
        }
        button = Button(window, 2010 + row);
        return true;
    }

    MapleControl::Action action;
    MapleControl::ActionResult result;
    MapleControl::Allocation allocation;
    CareEquipment sourceEquipment, destinationEquipment;
    std::uint32_t character = 0, nativeUser = 0, windowAddress = 0, activation = 0, job = 0;
    std::uint64_t generation = 0, deadline = 0, pointDeadline = 0;
    std::string windowName, windowIdentity;
    std::set<int> tabs;
    int expectedTab = -1, oldFirst = -1, scrollDirection = 0;
    bool active = false, allocationStarted = false, toggleSent = false, focusSent = false;
    bool equipmentStarted = false, equipmentQueued = false, equipmentInputStarted = false;
    bool cleanupSettled = true, escapeSent = false, mouseStopRequested = false;
    bool equipmentBaselineKnown = false;
    bool scopeFinished = true;
    bool allocationFinishing = false;
    std::string cancelReason;
    std::uint32_t ownedDrag = 0;
};
}
