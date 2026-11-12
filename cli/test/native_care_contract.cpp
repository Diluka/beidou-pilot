// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeCare.h"
#include "NativeKeyBindings.h"

#include <cassert>
#include <string>
#include <vector>

using namespace BeiDouBridge;
using namespace MapleControl;

State StateFixture() {
    State state;
    state.instanceId = "gui-contract";
    state.character.id = 7;
    state.sceneGeneration = 2;
    state.ready = state.characterKnown = state.inGame = true;
    state.character.values[1] = 100;
    state.character.values[2] = 10;
    state.character.values[6] = 100;
    state.character.values[10] = state.character.values[11] = 5;
    state.character.known.fill(true);
    return state;
}

CareView ViewFixture(const std::string& name = "stats") {
    CareView view;
    view.known = true;
    view.nativeUser = 77;
    view.characterId = 7;
    view.sceneGeneration = 2;
    view.width = 1280;
    view.height = 720;
    view.focusedWindow = 100;
    view.skillsKnown = view.sceneKnown = true;
    view.inventoryInputKnown = view.inventoryInputReady = true;
    CareWindow window;
    window.address = 100;
    window.identity = "window-1";
    window.name = name;
    window.geometryKnown = true;
    window.rect = {0, 0, name == "stats" ? 210 : 175, name == "stats" ? 348 : 289};
    window.skillsKnown = true;
    window.tabCount = 2;
    window.skills = {1000000};
    window.buttons = {{name == "stats" ? 2002u : 2010u, {140, 120, 12, 12}, true, true}};
    view.windows.push_back(window);
    return view;
}

void CheckAllocationFacts(const NativeCare& care, unsigned allocated, bool pending) {
    const auto data = care.Result().allocation.Dump();
    assert(data.find("\"allocated\":" + std::to_string(allocated) + ",") != std::string::npos);
    assert(data.find(std::string("\"point_pending\":") + (pending ? "true" : "false")) != std::string::npos);
}

void BindingContract() {
    std::array<unsigned char, 89 * 5> table{};
    std::array<unsigned, 256> keys{};
    auto binding = [&](unsigned scan, unsigned char type, std::uint32_t id, unsigned key) {
        table[scan * 5] = type;
        std::memcpy(table.data() + scan * 5 + 1, &id, sizeof(id));
        keys[scan] = key;
    };
    auto read = [&](unsigned scan, unsigned& key) {
        key = keys[scan];
        return true;
    };
    // Read-only V17 keymap facts from the failed GUI window trial.
    binding(23, 4, 1, 'I');
    binding(31, 4, 2, 'S');
    binding(37, 4, 3, 'K');
    binding(29, 5, 52, 17);
    binding(44, 5, 50, 'Z');
    binding(56, 5, 53, 18);
    unsigned key = 0;
    for (const auto& expected : {std::pair<unsigned, unsigned>{1, 'I'}, {2, 'S'}, {3, 'K'}}) {
        assert(FindNativeBinding(table, NativeBindingType::Menu, expected.first, key, read));
        assert(key == expected.second);
    }
    assert(FindNativeBinding(table, NativeBindingType::Action, 53, key, read) && key == 18);
    assert(FindNativeBinding(table, NativeBindingType::Action, 52, key, read) && key == 17);
    assert(FindNativeBinding(table, NativeBindingType::Action, 50, key, read) && key == 'Z');
    // Same numeric ID in another type must never be used as a window shortcut.
    binding(59, 5, 1, 112);
    binding(23, 2, 2000000, 'I');
    assert(!FindNativeBinding(table, NativeBindingType::Menu, 1, key, read));
    assert(FindNativeBinding(table, NativeBindingType::Action, 1, key, read) && key == 112);
    // A rebound menu is resolved, and a queued key is invalidated after rebind.
    binding(19, 4, 1, 'R');
    assert(FindNativeBinding(table, NativeBindingType::Menu, 1, key, read) && key == 'R');
    const auto queued = key;
    binding(19, 2, 2000000, 'R');
    assert(!FindNativeBinding(table, NativeBindingType::Menu, 1, key, read));
    binding(20, 4, 1, 'T');
    assert(FindNativeBinding(table, NativeBindingType::Menu, 1, key, read) && key != queued);
}

void MouseContract() {
    {
        NativeMouseInput clicks;
        NativeMouseInput::Target target;
        target.character = 77;
        target.clicks = 2;
        std::uint64_t updates = 0;
        std::vector<unsigned> messages;
        assert(clicks.Request(target, 0));
        for (unsigned now = 0; now <= 300 && !clicks.Released(); now += 25) {
            ++updates;
            clicks.Flush(
                now,
                [&](auto event, const auto&, auto epoch) {
                    messages.push_back(NativeMouseInput::Message(event));
                    if (event == NativeMouseInput::Event::Down || event == NativeMouseInput::Event::DoubleDown)
                        clicks.MarkDispatched(epoch);
                    return true;
                },
                [&] { return updates; });
            clicks.ConfirmRelease(77, updates, false);
        }
        assert(clicks.Released() && !clicks.Cancelled());
        assert(messages == std::vector<unsigned>({0x200, 0x201, 0x202, 0x203, 0x202}));
    }
    NativeMouseInput mouse;
    NativeMouseInput::Target target;
    target.character = 77;
    target.scene = 2;
    target.clicks = 2;
    target.point = true;
    std::uint64_t updates = 1;
    std::vector<NativeMouseInput::Event> events;
    auto send = [&](auto event, const auto&, std::uint64_t epoch) {
        events.push_back(event);
        if (event == NativeMouseInput::Event::Down) {
            mouse.MarkDispatched(epoch);
            mouse.Release();
            // Reentrant cancellation must deliver up but never the second click.
            mouse.Flush(
                5,
                [&](auto nested, const auto&, std::uint64_t) {
                    events.push_back(nested);
                    return true;
                },
                [&] { return updates; });
        }
        return true;
    };
    assert(mouse.Request(target, 0));
    assert(mouse.Flush(0, send, [&] { return updates; }));
    assert(mouse.Flush(1, send, [&] { return updates; }));
    assert(!mouse.Held() && mouse.Owned() && mouse.PointDispatched());
    assert(mouse.Cancelled());
    assert(!mouse.Released());
    assert(mouse.Flush(6, send, [&] { return updates; }));
    assert(!mouse.ConfirmRelease(77, updates, false));
    assert(!mouse.ConfirmRelease(88, ++updates, false));
    assert(mouse.ConfirmRelease(77, ++updates, false));
    assert(mouse.Released() && !mouse.Owned());
    assert(events
           == std::vector<NativeMouseInput::Event>(
               {NativeMouseInput::Event::Position, NativeMouseInput::Event::Down, NativeMouseInput::Event::Up}));
    mouse.ResetReport();
    assert(!mouse.PointDispatched());

    // A failed up remains required; new input cannot take over until it is delivered.
    target.clicks = 1;
    assert(mouse.Request(target, 10));
    auto ordinary = [&](auto event, const auto&, std::uint64_t epoch) {
        if (event == NativeMouseInput::Event::Down) mouse.MarkDispatched(epoch);
        return true;
    };
    mouse.Flush(10, ordinary, [&] { return updates; });
    mouse.Flush(11, ordinary, [&] { return updates; });
    mouse.Release();
    assert(!mouse.Flush(12, [](auto, const auto&, auto) { return false; }, [&] { return updates; }));
    assert(mouse.ReleasePending() && !mouse.Request(target, 13));
    mouse.Flush(13, ordinary, [&] { return updates; });
    assert(mouse.ConfirmRelease(77, ++updates, false));
}

void CareContract() {
    auto state = StateFixture();
    auto view = ViewFixture();
    Action ap;
    ap.kind = ActionKind::AllocateAp;
    ap.allocation.stat = "strength";
    ap.allocation.count = 2;
    ap.allocation.timeoutMs = 100;
    NativeCare care;
    std::vector<NativeMouseInput::Target> requests;
    std::vector<unsigned> keys;
    auto mouse = [&](const auto& request) {
        requests.push_back(request);
        return true;
    };
    auto key = [&](unsigned value) {
        keys.push_back(value);
        return true;
    };
    assert(care.Begin(ap, state, view, 0));
    care.Tick(state, view, 1, true, mouse, key);
    assert(requests.size() == 1 && requests.back().point);
    CheckAllocationFacts(care, 0, false);
    // Queuing a click is not a point request or a confirmation.
    --state.character.values[10];
    ++state.character.values[2];
    assert(!care.DispatchPoint(state, view, requests.back(), 2));
    assert(!care.Active() && care.Result().reason == "allocation_baseline_changed");
    CheckAllocationFacts(care, 0, false);

    state = StateFixture();
    requests.clear();
    assert(care.Begin(ap, state, view, 0));
    care.Tick(state, view, 1, true, mouse, key);
    assert(care.DispatchPoint(state, view, requests.back(), 2));
    --state.character.values[10];
    ++state.character.values[2];
    care.Tick(state, view, 3, false, mouse, key);
    CheckAllocationFacts(care, 0, true);
    care.Tick(state, view, 4, true, mouse, key);
    CheckAllocationFacts(care, 1, false);
    care.Tick(state, view, 5, true, mouse, key);
    assert(requests.size() == 2);
    assert(care.DispatchPoint(state, view, requests.back(), 6));
    care.Cancel(state, view, 7, "explicit_cancel", false);
    care.Tick(state, view, 8, true, mouse, key);
    assert(!care.Active() && requests.size() == 2);
    CheckAllocationFacts(care, 1, true);
    assert(care.CleanupPending());
    care.ConvergeCancellation(state, view, 9, true);
    assert(!care.CleanupPending());

    // A native disabled skill is refused without any point request.
    view = ViewFixture("skills");
    view.windows[0].buttons[0].enabled = false;
    Action sp;
    sp.kind = ActionKind::AllocateSp;
    sp.allocation.skill = true;
    sp.allocation.skillId = 1000000;
    requests.clear();
    assert(care.Begin(sp, state, view, 0));
    care.Tick(state, view, 1, true, mouse, key);
    assert(!care.Active() && requests.empty() && care.Result().reason == "allocation_not_enabled");
    CheckAllocationFacts(care, 0, false);

    // Changing/reusing the window address with a new native identity invalidates the operation.
    view = ViewFixture();
    requests.clear();
    assert(care.Begin(ap, state, view, 0));
    care.Tick(state, view, 1, true, mouse, key);
    view.windows[0].identity = "window-2";
    assert(!care.DispatchPoint(state, view, requests.back(), 2));
    care.Tick(state, view, 3, true, mouse, key);
    assert(!care.Active() && requests.size() == 1);

    // A job change while the UI press is in flight cancels before another edge.
    state = StateFixture();
    view = ViewFixture();
    requests.clear();
    assert(care.Begin(ap, state, view, 0));
    care.Tick(state, view, 1, true, mouse, key);
    assert(care.DispatchPoint(state, view, requests.back(), 2));
    state.character.values[1] = 200;
    care.Tick(state, view, 3, false, mouse, key);
    assert(!care.Active());
    CheckAllocationFacts(care, 0, true);
}

void CancelObservedPoint() {
    auto state = StateFixture();
    auto view = ViewFixture();
    Action action;
    action.kind = ActionKind::AllocateAp;
    action.allocation.stat = "strength";
    action.allocation.count = 2;
    action.allocation.timeoutMs = 100;
    NativeCare care;
    std::vector<NativeMouseInput::Target> requests;
    assert(care.Begin(action, state, view, 0));
    care.Tick(
        state, view, 1, true,
        [&](const auto& request) {
            requests.push_back(request);
            return true;
        },
        [](unsigned) { return true; });
    assert(care.DispatchPoint(state, view, requests[0], 2));
    // Native Up has returned, but its character-update release proof is pending.
    --state.character.values[10];
    ++state.character.values[2];
    care.Cancel(state, view, 3, "explicit_cancel", false);
    assert(!care.Active() && care.CleanupPending());
    care.ConvergeCancellation(state, view, 4, false);
    CheckAllocationFacts(care, 0, true);
    care.ConvergeCancellation(state, view, 5, true);
    CheckAllocationFacts(care, 1, false);
    assert(!care.CleanupPending() && requests.size() == 1);
    care.Tick(
        state, view, 6, true,
        [&](const auto&) {
            assert(false);
            return true;
        },
        [](unsigned) {
            assert(false);
            return true;
        });
}

void EquipmentContract() {
    auto state = StateFixture();
    auto view = ViewFixture("inventory");
    auto& window = view.windows[0];
    window.inventoryKnown = true;
    window.firstSlot = 1;
    window.inventoryType = 1;
    view.inventoryKnown = true;
    view.inventory[1] = {1302000, "source-object", true, true, {-11}};
    view.inventory[-11] = {1332066, "wearing-object", true, true, {-11}};
    Action equip;
    equip.kind = ActionKind::Equip;
    equip.sourceSlot = 1;
    equip.destinationSlot = -11;
    equip.durationMs = 1000;
    equip.reference = "source-object";
    NativeCare care;
    std::vector<NativeMouseInput::Target> inputs;
    auto mouse = [&](const auto& target) {
        inputs.push_back(target);
        return true;
    };
    auto key = [](unsigned) { return true; };
    assert(care.Begin(equip, state, view, 0));
    assert(!care.ReleasePending(false, true)); // Pulse release cannot suppress whole-workflow cancellation.
    care.Tick(state, view, 1, true, mouse, key);
    assert(inputs.size() == 1 && inputs[0].equipment && inputs[0].clicks == 2);
    assert(care.DispatchEquipment(state, view, inputs[0]));
    view.dragObject = 900;
    view.dragInventoryType = 1;
    view.dragSlot = 1;
    care.ObserveCleanup(state, view);
    std::swap(view.inventory[1], view.inventory[-11]);
    care.Tick(state, view, 2, false, mouse, key);
    assert(!care.Active() && care.Result().effect == "confirmed" && care.CleanupPending());
    assert(care.ReleasePending(false, false) && care.CanEscape(view));
    care.EscapeSent();
    assert(!care.CanEscape(view));
    view.dragObject = 0;
    care.ObserveCleanup(state, view);
    assert(!care.CleanupPending());
    care.FinishScope();
    view.dragObject = 999;
    view.dragSlot = 1;
    care.ObserveCleanup(state, view);
    assert(!care.CleanupPending() && !care.CanEscape(view));
    view.dragObject = 0;
    care.Tick(state, view, 3, true, mouse, key);
    assert(inputs.size() == 1);

    // Same item ID with a new native reference invalidates the old request.
    std::swap(view.inventory[1], view.inventory[-11]);
    view.inventory[1].reference = "replacement-object";
    assert(care.Begin(equip, state, view, 4));
    assert(!care.Active() && care.Result().reason == "equipment_reference_expired");
    assert(inputs.size() == 1);

    // Cash and ambiguous automatic destinations are refused before a click.
    equip.reference = "replacement-object";
    view.inventory[1].ordinary = false;
    assert(care.Begin(equip, state, view, 5));
    assert(!care.Active());
    view.inventory[1].ordinary = true;
    view.inventory[1].bodySlots = {-12, -13};
    assert(care.Begin(equip, state, view, 6));
    assert(!care.Active());
    view.inventory[1].bodySlots = {-11};
    assert(care.Begin(equip, state, view, 7));
    care.Tick(state, view, 8, true, mouse, key);
    assert(care.DispatchEquipment(state, view, inputs.back()));
    // Cancellation observes a late native drag, but never clears another drag.
    care.Cancel(state, view, 9);
    view.dragObject = 901;
    care.ObserveCleanup(state, view);
    assert(care.CleanupPending() && care.CanEscape(view));
    view.dragObject = 902;
    view.dragSlot = 2;
    care.ObserveCleanup(state, view);
    assert(!care.CleanupPending() && !care.CanEscape(view));
}

void EquipmentReadinessContract() {
    auto state = StateFixture();
    auto view = ViewFixture("inventory");
    view.windows[0].inventoryKnown = true;
    view.windows[0].firstSlot = view.windows[0].inventoryType = 1;
    view.inventoryKnown = true;
    view.inventory[2] = {1040002, "shirt-bag", true, true, {-5}};
    view.inventory[-5] = {1040002, "shirt-worn", true, true, {-5}};
    Action equip;
    equip.kind = ActionKind::Equip;
    equip.sourceSlot = 2;
    equip.destinationSlot = -5;
    equip.durationMs = 1000;
    equip.reference = "shirt-bag";
    NativeCare care;
    std::vector<NativeMouseInput::Target> inputs;
    auto mouse = [&](const auto& target) {
        inputs.push_back(target);
        return true;
    };
    auto key = [](unsigned) {
        assert(false);
        return true;
    };
    assert(care.Begin(equip, state, view, 0));
    care.Tick(state, view, 1, true, mouse, key);
    assert(inputs.size() == 1 && care.DispatchEquipment(state, view, inputs.back()));
    std::swap(view.inventory[2], view.inventory[-5]);
    view.inventoryInputReady = false;
    // The native request may still be locked when the exchange is observed.
    care.Tick(state, view, 2, true, mouse, key);
    assert(!care.Active() && care.Result().effect == "confirmed");

    // A fresh, immediate inverse request waits before its first click. Mouse
    // release from the previous action does not bypass native readiness.
    equip.reference = "shirt-worn";
    assert(care.Begin(equip, state, view, 2));
    care.Tick(state, view, 3, true, mouse, key);
    care.Tick(state, view, 499, true, mouse, key);
    assert(care.Active() && inputs.size() == 1);
    assert(care.Result().reason == "equipment_waiting_native_ready");
    view.inventoryInputReady = true;
    care.Tick(state, view, 500, true, mouse, key);
    assert(inputs.size() == 2 && care.DispatchEquipment(state, view, inputs.back()));
    std::swap(view.inventory[2], view.inventory[-5]);
    care.Tick(state, view, 501, true, mouse, key);
    assert(!care.Active() && care.Result().effect == "confirmed");
    assert(view.inventory[2].reference == "shirt-bag");

    equip.reference = "shirt-bag";
    view.inventoryInputReady = false;
    assert(care.Begin(equip, state, view, 600));
    care.Tick(state, view, 601, true, mouse, key);
    care.Cancel(state, view, 602);
    view.inventoryInputReady = true;
    care.Tick(state, view, 603, true, mouse, key);
    assert(!care.Active() && care.Result().effect == "unknown" && inputs.size() == 2);

    view.inventoryInputReady = false;
    assert(care.Begin(equip, state, view, 700));
    care.Tick(state, view, 701, true, mouse, key);
    care.Tick(state, view, 1700, true, mouse, key);
    assert(!care.Active() && care.Result().reason == "equipment_native_not_ready" && inputs.size() == 2);

    view.inventoryInputKnown = false;
    assert(care.Begin(equip, state, view, 1800));
    care.Tick(state, view, 1801, true, mouse, key);
    assert(!care.Active() && care.Result().reason == "equipment_native_readiness_unavailable" && inputs.size() == 2);

    view.inventoryInputKnown = view.inventoryInputReady = true;
    assert(care.Begin(equip, state, view, 1900));
    care.Tick(state, view, 1901, true, mouse, key);
    assert(inputs.size() == 3);
    view.inventoryInputReady = false;
    assert(!care.DispatchEquipment(state, view, inputs.back()));
    view.inventoryInputReady = true;
    care.Tick(state, view, 1902, true, mouse, key);
    assert(!care.Active() && care.StopMouse() && care.Result().effect == "unknown" && inputs.size() == 3);

    // Waiting cannot relax the object or scene binding.
    view.inventoryInputReady = false;
    assert(care.Begin(equip, state, view, 2000));
    care.Tick(state, view, 2001, true, mouse, key);
    view.inventory[2].reference = "replaced-shirt";
    view.inventoryInputReady = true;
    care.Tick(state, view, 2002, true, mouse, key);
    assert(!care.Active() && care.Result().reason == "equipment_objects_changed" && inputs.size() == 3);
    view.inventory[2].reference = "shirt-bag";
    view.inventoryInputReady = false;
    assert(care.Begin(equip, state, view, 2100));
    care.Tick(state, view, 2101, true, mouse, key);
    ++state.sceneGeneration;
    care.Tick(state, view, 2102, true, mouse, key);
    assert(!care.Active() && care.Result().reason == "care_context_changed" && inputs.size() == 3);

    // Readiness can disappear after the first down. The second down is then
    // suppressed, while the actual mouse-up obligation still reaches release.
    state = StateFixture();
    view.inventoryInputReady = true;
    NativeMouseInput pulse;
    std::vector<unsigned> messages;
    std::uint64_t updates = 0;
    assert(care.Begin(equip, state, view, 2200));
    care.Tick(state, view, 2201, true, [&](const auto& target) { return pulse.Request(target, 2201); }, key);
    for (unsigned now = 2201; now < 2600 && !pulse.Released(); now += 25) {
        ++updates;
        pulse.Flush(
            now,
            [&](NativeMouseInput::Event event, const auto& target, auto) {
                if ((event == NativeMouseInput::Event::Down || event == NativeMouseInput::Event::DoubleDown)
                    && !care.DispatchEquipment(state, view, target))
                    return false;
                messages.push_back(NativeMouseInput::Message(event));
                if (event == NativeMouseInput::Event::Down) view.inventoryInputReady = false;
                return true;
            },
            [&]() { return updates; });
        pulse.ConfirmRelease(77, updates, false);
    }
    assert((messages == std::vector<unsigned>{0x200, 0x201, 0x202, 0x202}));
    assert(!care.Active() && pulse.Released() && !pulse.Held());
}

void WindowContract() {
    auto state = StateFixture();
    auto view = ViewFixture();
    Action action;
    action.kind = ActionKind::Window;
    action.reference = "stats";
    action.direction = "open";
    action.durationMs = 1000;
    NativeCare care;
    std::vector<unsigned> keys;
    std::vector<NativeMouseInput::Target> clicks;
    auto mouse = [&](const auto& target) {
        clicks.push_back(target);
        return true;
    };
    auto key = [&](unsigned value) {
        keys.push_back(value);
        return true;
    };
    NativeMouseInput::Target root;
    root.x = 320;
    root.y = 110;
    assert(NativeCare::AllowsTarget(view, root));
    auto popup = view.windows[0];
    popup.address = 200;
    popup.rect = {300, 100, 100, 100};
    view.windows.push_back(popup);
    assert(!NativeCare::AllowsTarget(view, root));
    view.windows.pop_back();
    view.npcs.emplace_back(320, 150);
    assert(!NativeCare::AllowsTarget(view, root));
    view.npcs.clear();
    int releaseX = 0, releaseY = 0;
    assert(NativeCare::CancelPoint(view, 100, releaseX, releaseY));
    assert(!view.windows[0].rect.Contains(releaseX, releaseY));
    view.windows.clear();
    view.gameFocused = true;
    assert(care.Begin(action, state, view, 0));
    care.Tick(state, view, 1, true, mouse, key);
    care.Tick(state, view, 2, true, mouse, key);
    assert(keys == std::vector<unsigned>{'S'} && care.Active());
    view = ViewFixture();
    care.Tick(state, view, 3, false, mouse, key);
    assert(care.Active());
    care.Tick(state, view, 4, true, mouse, key);
    assert(!care.Active() && care.Result().effect == "confirmed");

    action.direction = "close";
    assert(care.Begin(action, state, view, 10));
    care.Tick(state, view, 11, true, mouse, key);
    assert(clicks.size() == 1 && clicks.back().window == 0);
    view.gameFocused = true;
    care.Tick(state, view, 12, true, mouse, key);
    assert(keys.size() == 2);
    view.windows.clear();
    care.Tick(state, view, 13, true, mouse, key);
    assert(!care.Active() && care.Result().effect == "confirmed");
}

int main() {
    BindingContract();
    MouseContract();
    CareContract();
    CancelObservedPoint();
    EquipmentContract();
    EquipmentReadinessContract();
    WindowContract();
}
