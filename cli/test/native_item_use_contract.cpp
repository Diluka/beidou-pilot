// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeItemUse.h"
#include "NativeKeyInput.h"
#include "Runtime.h"

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

// Inventory and the void native entry are external game boundaries. The
// fixture never applies potion effects or claims to validate the Windows ABI.
class NativeBoundary final : public MapleControl::Adapter {
public:
    NativeBoundary() {
        state.instanceId = "native-item-contract";
        state.inGame = state.ready = state.characterKnown = state.mapKnown = state.positionKnown = true;
        state.sceneGeneration = 3;
        state.mapId = 50000;
        state.character.id = 7;
        state.character.values[6] = 80;
        state.character.values[7] = 100;
        state.character.values[8] = 12;
        state.character.values[9] = 20;
        state.character.known.fill(true);
        state.inventoryKnown = true;
        state.inventory = {{2, 7, 2000000, 3, true}, {2, 9, 2000001, 2, true}};
    }

    const char* Backend() const override { return "native-item-contract"; }

    const MapleControl::State& Observe() const override { return state; }

    bool Supports(MapleControl::ActionKind kind) const override {
        return kind == MapleControl::ActionKind::UseItem || kind == MapleControl::ActionKind::Stop;
    }

    bool Begin(const MapleControl::Action& action, std::string& error) override {
        const auto item =
            std::find_if(state.inventory.begin(), state.inventory.end(), [&](const MapleControl::Item& value) {
                return value.inventoryType == 2 && value.slot > 0 && value.itemId == action.itemId
                       && value.quantityKnown && value.quantity > 0;
            });
        if (action.kind != MapleControl::ActionKind::UseItem || action.itemId / 10000 != 200 || !Released()
            || item == state.inventory.end()) {
            error = "native_item_unavailable";
            return false;
        }
        use.Request({state.character.id, state.sceneGeneration, context, item->slot, item->itemId});
        return true;
    }

    MapleControl::ActionResult Result() const override {
        MapleControl::ActionResult result;
        result.dispatched = use.Dispatched();
        result.controlReleased = Released();
        result.reason = "native_item_request";
        return result;
    }

    void Release() override {
        use.Cancel();
        keys.Release();
    }

    bool Released() const override { return keys.Released() && !use.Pending(); }

    bool ReleasePending() const override { return keys.ReleasePending(); }

    bool Logs(const std::string&, const std::vector<std::string>&) override { return true; }

    void Resume() {
        insideVm = true;
        runtime->Tick();
        insideVm = false;
        Check(runtime->CurrentStatus()->error.empty(), runtime->CurrentStatus()->error);
    }

    void Update() {
        ++state.sequence;
        ++characterUpdates;
        keys.ConfirmRelease(state.character.id, characterUpdates, false);
        Resume();
        const auto result = keys.Flush(
            [&](unsigned int, bool, std::uint64_t epoch) {
                ++keyEvents;
                keys.MarkDispatched(epoch);
                return true;
            },
            [&]() { return characterUpdates; });
        Check(!result.failed, "unexpected_key_failure");
    }

    void Invoked(const BeiDouBridge::NativeItemUse::Item& item) {
        Check(!insideVm && !use.Pending() && use.Dispatched(), "native_entry_ran_inside_lua_or_before_dispatch");
        invoked.push_back(item);
        Check(item.character == state.character.id && item.scene == state.sceneGeneration && item.context == context,
              "native_entry_received_foreign_context");
    }

    MapleControl::Runtime* runtime = nullptr;
    MapleControl::State state;
    BeiDouBridge::NativeItemUse use;
    BeiDouBridge::NativeKeyInput keys;
    std::vector<BeiDouBridge::NativeItemUse::Item> invoked;
    std::uint32_t context = 0x1234;
    std::uint64_t characterUpdates = 0;
    int keyEvents = 0;
    bool insideVm = false;
};

void RuntimeDispatch() {
    // Complete normally, cancel before entry, and cancel after the void entry.
    for (int mode = 0; mode < 3; ++mode) {
        NativeBoundary native;
        MapleControl::Runtime runtime(native);
        native.runtime = &runtime;
        std::string error;
        Check(runtime.Start("native-item", R"lua(
local result = game.use_item(2000000)
assert(result.dispatched and result.control_released and result.effect == "unknown")
)lua",
                            3000, error),
              error);
        native.Resume();
        Check(runtime.CurrentStatus()->resumes == 1 && runtime.CurrentStatus()->tasks.front().wait == "action"
                  && native.use.Pending() && !native.use.Dispatched() && native.invoked.empty(),
              "accepted_item_was_dispatched_before_yield");
        if (mode == 1) runtime.Cancel("cancel_before_entry");
        const auto result =
            native.use.Consume(native.state.character.id, native.state.sceneGeneration, native.context,
                               [&](const BeiDouBridge::NativeItemUse::Item& item) {
                                   native.Invoked(item);
                                   if (mode == 2) runtime.Cancel("cancel_after_entry");
                                   native.Resume();
                                   native.Resume();
                                   Check(!runtime.Running(), "native_callback_could_not_finish_session");
                               });
        for (int tick = 0; tick < 4 && runtime.Running(); ++tick) native.Update();
        Check(!runtime.Running() && native.Released() && native.keyEvents == 0,
              "native_item_kept_session_or_used_keys");
        if (mode == 1) {
            Check(result == BeiDouBridge::NativeItemUse::Consumption::None && native.invoked.empty()
                      && !native.use.Dispatched(),
                  "cancelled_pending_item_reached_native_entry");
        } else {
            Check(result == BeiDouBridge::NativeItemUse::Consumption::Dispatched && native.invoked.size() == 1
                      && native.invoked.front().slot == 7 && native.invoked.front().itemId == 2000000
                      && native.use.Dispatched(),
                  "void_native_entry_arguments_or_dispatch_fact_lost");
        }
        Check(runtime.CurrentStatus()->status == (mode == 0 ? "completed" : "cancelled"),
              "item_session_terminal_result_changed");
    }
}

void CallbackAndIdentity() {
    for (const bool cancelNext : {false, true}) {
        NativeBoundary native;
        MapleControl::Runtime runtime(native);
        native.runtime = &runtime;
        std::string error;
        Check(runtime.Start("item-callback", R"lua(
assert(game.use_item(2000000).dispatched)
local result = game.use_item(2000001)
assert(result.dispatched and result.control_released and result.effect == "unknown")
)lua",
                            3000, error),
              error);
        native.Resume();
        const auto first = native.use.Consume(
            native.state.character.id, native.state.sceneGeneration, native.context,
            [&](const BeiDouBridge::NativeItemUse::Item& item) {
                native.Invoked(item);
                native.Resume(); // The suspended Lua task submits its next item in this callback.
                Check(native.use.Pending() && !native.use.Dispatched(), "new_item_request_missing_inside_callback");
                if (cancelNext) runtime.Cancel("cancel_new_item_inside_old_entry");
            });
        Check(first == BeiDouBridge::NativeItemUse::Consumption::Dispatched && native.use.Pending() == !cancelNext
                  && !native.use.Dispatched(),
              "old_entry_return_overwrote_new_request_or_cancel");
        const auto second = native.use.Consume(native.state.character.id, native.state.sceneGeneration, native.context,
                                               [&](const BeiDouBridge::NativeItemUse::Item& item) {
                                                   native.Invoked(item);
                                                   native.Resume();
                                                   native.Resume();
                                               });
        for (int tick = 0; tick < 4 && runtime.Running(); ++tick) native.Update();
        Check(!runtime.Running() && native.Released() && native.keyEvents == 0, "callback_item_did_not_settle");
        if (cancelNext) {
            Check(second == BeiDouBridge::NativeItemUse::Consumption::None && native.invoked.size() == 1
                      && runtime.CurrentStatus()->status == "cancelled",
                  "cancelled_new_item_was_invoked");
        } else
            Check(second == BeiDouBridge::NativeItemUse::Consumption::Dispatched && native.invoked.size() == 2
                      && native.invoked[1].slot == 9 && native.invoked[1].itemId == 2000001
                      && runtime.CurrentStatus()->status == "completed",
                  "new_item_identity_or_completion_lost");
    }

    BeiDouBridge::NativeItemUse use;
    const BeiDouBridge::NativeItemUse::Item item{7, 3, 0x1234, 7, 2000000};
    for (int mismatch = 0; mismatch < 3; ++mismatch) {
        auto current = item;
        if (mismatch == 0)
            ++current.character;
        else if (mismatch == 1)
            ++current.scene;
        else
            ++current.context;
        use.Request(item);
        const auto result = use.Consume(
            current.character, current.scene, current.context,
            [](const BeiDouBridge::NativeItemUse::Item&) { Check(false, "foreign_item_context_was_invoked"); });
        Check(result == BeiDouBridge::NativeItemUse::Consumption::ContextChanged && !use.Pending() && !use.Dispatched(),
              "foreign_context_not_rejected");
    }
}
}

int main(int argc, char** argv) {
    Check(argc == 2, "expected native item scenario");
    const std::string scenario = argv[1];
    if (scenario == "runtime")
        RuntimeDispatch();
    else if (scenario == "callback-identity")
        CallbackAndIdentity();
    else
        Check(false, "unknown native item scenario");
}
