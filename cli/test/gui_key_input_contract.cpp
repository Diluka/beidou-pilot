// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeKeyInput.h"
#include "NativeSkillUse.h"
#include "Runtime.h"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

std::uint64_t Now() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

bool Any(const BeiDouBridge::NativeKeyInput::Mask& keys) {
    return std::any_of(keys.begin(), keys.end(), [](bool value) { return value; });
}

enum class NativeCall { Ordinary, Modal, Handoff, Cancel };

// Only the external application updates and SendKey boundary are simulated.
// Desired input, epoch invalidation and release ACKs use the production core.
class NativeBoundary final : public MapleControl::Adapter {
public:
    struct Event {
        unsigned int key;
        bool down;
    };

    explicit NativeBoundary(NativeCall call) : call(call) {
        state.instanceId = "gui-input-contract";
        state.inGame = state.ready = state.mapKnown = state.characterKnown = state.positionKnown = true;
        state.sceneGeneration = 1;
        state.mapId = 50000;
        state.character.id = 7;
        state.character.values[6] = 100;
        state.character.known.fill(true);
    }

    const char* Backend() const override { return "gui-input-contract"; }

    const MapleControl::State& Observe() const override { return state; }

    bool Supports(MapleControl::ActionKind kind) const override { return kind == MapleControl::ActionKind::Stop; }

    bool Begin(const MapleControl::Action&, std::string& error) override {
        error = "unsupported_contract_semantic_action";
        return false;
    }

    MapleControl::ActionResult Result() const override {
        MapleControl::ActionResult result;
        result.dispatched = input.Dispatched();
        result.controlReleased = input.Released();
        result.reason = "native_key_input";
        return result;
    }

    void Release() override { input.Release(); }

    bool Released() const override { return input.Released(); }

    bool ReleasePending() const override { return input.ReleasePending(); }

    bool Logs(const std::string&, const std::vector<std::string>&) override { return true; }

    bool SupportsRawKeys() const override { return true; }

    bool RawKeys(const std::vector<std::string>& names, std::uint32_t duration, std::string& error) override {
        BeiDouBridge::NativeKeyInput::Mask desired{};
        for (const auto& name : names) {
            unsigned int key = 0;
            if (name == "space")
                key = 32;
            else if (name == "Left")
                key = 37;
            else if (name == "Right")
                key = 39;
            else if (name == "Control_L")
                key = 17;
            else {
                error = "unsupported_contract_key";
                return false;
            }
            desired[key] = true;
        }
        input.Request(desired, duration, state.character.id, Now());
        return true;
    }

    void RunVm() {
        Check(!insideVm, "fixture_reentered_vm");
        insideVm = true;
        runtime->Tick();
        insideVm = false;
        Check(runtime->CurrentStatus()->error.empty(), runtime->CurrentStatus()->error);
    }

    void FlushNative() {
        const auto previousUpReturns = upReturns;
        const auto result =
            input.Flush([this](unsigned int key, bool down, std::uint64_t epoch) { return Send(key, down, epoch); },
                        [this]() { return characterUpdates; });
        Check(!result.failed, "native_dispatch_failed");
        if (upReturns != previousUpReturns && input.ReleasePending())
            Check(!input.ConfirmRelease(state.character.id, characterUpdates, false),
                  "release_acked_without_update_after_keyup_return");
    }

    void Update() {
        ++state.sequence;
        state.observedAtMs =
            std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch())
                .count();
        ++characterUpdates; // A real fixture character-update event, including modal updates.
        if (input.ConfirmRelease(state.character.id, characterUpdates, false)) {
            Check(!Any(physicalKeys), "release_acked_while_native_keys_still_down");
            Check(characterUpdates > lastUpReturnedAt, "release_acked_before_final_keyup_return");
            ++releaseAcks;
        }
        if (input.Active() && Now() >= input.Deadline()) input.Release();
        RunVm();
        FlushNative();
    }

    bool Send(unsigned int key, bool down, std::uint64_t epoch) {
        Check(!insideVm, "native_send_entered_before_lua_resume_returned");
        input.MarkDispatched(epoch);
        events.push_back({key, down});
        physicalKeys[key] = down;
        if (!down) {
            if (call == NativeCall::Cancel && !repeatedStop) {
                repeatedStop = true;
                runtime->Cancel("native_stop_during_keyup");
                input.Release(); // The host stop entry may supersede an in-flight batch.
            }
            const auto previousAcks = releaseAcks;
            Update(); // Native key delivery may itself pump a character update.
            Check(releaseAcks == previousAcks && !input.Released(), "release_acked_inside_keyup_dispatch");
            ++upReturns;
            lastUpReturnedAt = characterUpdates;
        } else if (key == 32 && call != NativeCall::Ordinary && !modalOpen) {
            modalOpen = true;
            Check(runtime->CurrentStatus()->resumes > 0, "modal_entered_before_first_resume_returned");
            if (call == NativeCall::Cancel) runtime->Cancel("modal_cancel");
            const auto deadline = Now() + 1500;
            while (runtime->Running() && Now() < deadline) {
                Update();
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            Check(!runtime->Running(), "lua_stalled_until_native_modal_return");
            Check(input.Released() && !Any(physicalKeys), "modal_callback_finished_before_release_ack");
            // Progress is proved while this callback and the modal are still open.
            completedInsideModal = true;
        }
        return true;
    }

    int Count(unsigned int key, bool down) const {
        return static_cast<int>(std::count_if(events.begin(), events.end(), [key, down](const Event& event) {
            return event.key == key && event.down == down;
        }));
    }

    NativeCall call;
    MapleControl::Runtime* runtime = nullptr;
    MapleControl::State state;
    BeiDouBridge::NativeKeyInput input;
    BeiDouBridge::NativeKeyInput::Mask physicalKeys{};
    std::vector<Event> events;
    std::uint64_t characterUpdates = 0;
    std::uint64_t lastUpReturnedAt = 0;
    int releaseAcks = 0;
    int upReturns = 0;
    bool insideVm = false;
    bool modalOpen = false;
    bool completedInsideModal = false;
    bool repeatedStop = false;
};

void ModalProgress() {
    NativeBoundary native(NativeCall::Modal);
    MapleControl::Runtime runtime(native);
    native.runtime = &runtime;
    std::string error;
    Check(runtime.Start("modal-progress", "game.press('space',0.08);game.sleep(0.2)", 3000, error), error);
    native.RunVm();
    Check(native.events.empty() && !native.input.Dispatched() && !native.input.Released(),
          "accepted_press_was_already_dispatched_or_released");
    Check(runtime.CurrentStatus()->resumes == 1 && runtime.CurrentStatus()->tasks.front().wait == "raw_keys",
          "press_did_not_yield_before_native_phase");
    native.FlushNative();
    Check(native.modalOpen && native.completedInsideModal, "progress_required_closing_modal");
    Check(runtime.CurrentStatus()->status == "completed" && runtime.CurrentStatus()->resumes == 3,
          "press_sleep_did_not_complete_once");
    Check(native.Count(32, true) == 1 && native.Count(32, false) == 1 && native.releaseAcks == 1,
          "press_delivery_or_natural_release_missing");
}

void ModalSlotChanges() {
    for (const auto mode : {NativeCall::Handoff, NativeCall::Cancel}) {
        NativeBoundary native(mode);
        MapleControl::Runtime runtime(native);
        native.runtime = &runtime;
        std::string error;
        const auto* source = mode == NativeCall::Handoff ? R"lua(
local started = false
game.spawn("new", 20, function()
    while not started do game.sleep(0) end
    game.acquire()
    local result = game.press("Left",0.04)
    assert(result.dispatched and result.control_released)
end)
game.spawn("old", 10, function()
    game.acquire()
    started = true
    local result = game.press({"Control_L","space","Right"},0.5)
    assert(result.dispatched and result.control_released and result.reason == "control_preempted")
end)
)lua"
                                                         : "game.press({'Control_L','space','Right'},0.5)";
        Check(runtime.Start("modal-slot", source, 3000, error), error);
        const auto deadline = Now() + 1500;
        while (runtime.Running() && Now() < deadline) {
            native.Update();
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        Check(native.completedInsideModal && native.modalOpen && native.input.Released(), "modal_slot_did_not_release");
        Check(native.Count(17, true) == 1 && native.Count(32, true) == 1 && native.Count(39, true) == 0,
              "old_target_remaining_key_was_replayed");
        Check(native.Count(17, false) == 1 && native.Count(32, false) == 1 && native.input.Dispatched(),
              "old_held_batch_lost_keyup_or_dispatch_fact");
        if (mode == NativeCall::Handoff) {
            Check(runtime.CurrentStatus()->status == "completed" && native.Count(37, true) == 1
                      && native.Count(37, false) == 1,
                  "successor_input_was_lost_or_released_by_old_batch");
            Check(native.releaseAcks == 2, "handoff_missing_release_ack");
        } else
            Check(runtime.CurrentStatus()->status == "cancelled" && native.repeatedStop && native.releaseAcks == 1,
                  "modal_cancel_or_full_keyup_batch_did_not_finish");
    }

    NativeBoundary native(NativeCall::Ordinary);
    MapleControl::Runtime runtime(native);
    native.runtime = &runtime;
    std::string error;
    Check(runtime.Start("latest-target", R"lua(
game.keys("Right",1)
game.sleep(0)
game.keys("Left",1)
game.keys("Right",1)
game.sleep(1)
)lua",
                        3000, error),
          error);
    native.RunVm();
    native.FlushNative();
    Check(native.Count(39, true) == 1 && native.input.Held()[39], "initial_right_not_held");
    const auto delivered = native.events.size();
    native.Update();
    Check(native.events.size() == delivered && native.input.Held()[39] && native.physicalKeys[39],
          "overwritten_target_flickered_held_key");
    runtime.Cancel("latest_target_cleanup");
    for (int tick = 0; tick < 10 && runtime.Running(); ++tick) native.Update();
    Check(!runtime.Running() && native.input.Released() && native.Count(39, false) == 1 && native.Count(37, true) == 0,
          "latest_target_cleanup_lost_release");
}

void UndispatchedRequests() {
    for (int scenario = 0; scenario < 4; ++scenario) {
        NativeBoundary native(NativeCall::Ordinary);
        MapleControl::Runtime runtime(native);
        native.runtime = &runtime;
        std::string error;
        const auto* source =
            scenario == 0   ? "game.press('space',0.08)"
            : scenario == 1 ? "game.keys('space',0.08)"
            : scenario == 2 ? "game.keys('space',0.08);local r=game.stop();assert(r.dispatched and r.control_released)"
                            : "assert(game.press('space',0.01).dispatched);game.keys({},0.08);"
                              "local r=game.stop();assert(r.dispatched and r.control_released)";
        Check(runtime.Start("undispatched", source, 3000, error), error);
        native.RunVm();
        if (scenario == 0) runtime.Cancel("before_native_phase");
        for (int tick = 0; tick < 100 && runtime.Running(); ++tick) {
            native.Update();
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        Check(!runtime.Running() && native.input.Released() && !native.Result().dispatched
                  && native.events.size() == (scenario == 3 ? 2u : 0u),
              "ended_request_was_dispatched_afterwards");
        Check(runtime.CurrentStatus()->status == (scenario == 0 ? "cancelled" : "completed"),
              "undispatched_request_result_changed");
    }
}

void SkillConsumption() {
    BeiDouBridge::NativeKeyInput input;
    BeiDouBridge::NativeSkillUse skills;
    BeiDouBridge::NativeKeyInput::Mask desired{};
    desired[39] = true;
    input.Request(desired, 100, 200, 1000);
    BeiDouBridge::NativeSkillUse::Skill skill{1001004, 7, 200, 3, input.Epoch(), 1100, 1};
    BeiDouBridge::NativeSkillUse::Context context{7, 200, 3, input.Epoch(), 1000, 200, 4, true, true};
    int calls = 0;
    const auto invoke = [&](std::uint32_t id, int& nativeResult, std::string&) {
        Check(id == 1001004 && !skills.Pending(), "skill_reentered_with_pending_old_request");
        ++calls;
        Check(skills.Consume(context,
                             [](std::uint32_t, int&, std::string&) {
                                 Check(false, "nested_update_replayed_skill");
                                 return true;
                             }),
              "nested_update_failed");
        nativeResult = 7;
        return true;
    };
    skills.Request(skill);
    Check(!skills.Result().nativeResultKnown && skills.Consume(context, invoke) && calls == 0,
          "skill_invoked_before_direction_delivery");
    const auto flushed = input.Flush(
        [&](unsigned int key, bool down, std::uint64_t epoch) {
            Check(key == 39 && down, "unexpected_skill_direction");
            input.MarkDispatched(epoch);
            return true;
        },
        [&]() { return context.characterUpdates; });
    Check(!flushed.failed && input.Held()[39] && input.Dispatched(), "direction_not_delivered");
    skills.DirectionDelivered(input.Epoch(), context.characterUpdates);
    Check(skills.Consume(context, invoke) && calls == 0, "delivery_was_mistaken_for_character_consumption");
    ++context.characterUpdates;
    Check(skills.Consume(context, invoke) && calls == 0, "skill_invoked_before_direction_matched");
    context.facingLeft = false;
    Check(skills.Consume(context, invoke) && calls == 1 && !skills.Pending() && skills.Result().dispatched
              && skills.Result().nativeResultKnown && skills.Result().nativeResult == 7
              && skills.Result().reason == "native_skill_admitted",
          "consumed_direction_did_not_admit_skill");
    skills.Consume(context, invoke);
    Check(calls == 1, "completed_skill_replayed");

    skills.Request(skill);
    skills.Cancel("cancel_requested");
    ++context.characterUpdates;
    skills.Consume(context, invoke);
    Check(calls == 1 && !skills.Pending() && !skills.Result().nativeResultKnown, "cancelled_skill_was_late_dispatched");
    skills.Request(skill);
    context.now = skill.deadline;
    skills.Consume(context, invoke);
    context.now = 1000;
    skills.Consume(context, invoke);
    Check(calls == 1 && !skills.Pending() && !skills.Result().nativeResultKnown
              && skills.Result().reason == "native_skill_expired",
          "expired_skill_was_late_dispatched");
    skills.Request(skill);
    ++context.inputEpoch;
    skills.Consume(context, invoke);
    Check(calls == 1 && !skills.Pending() && skills.Result().reason == "native_skill_context_changed",
          "replaced_input_dispatched_old_skill");

    skill.direction = 0;
    skill.inputEpoch = context.inputEpoch;
    skills.Request(skill);
    Check(skills.Consume(context,
                         [&](std::uint32_t, int& nativeResult, std::string&) {
                             ++calls;
                             nativeResult = 0;
                             return true;
                         })
              && calls == 2 && !skills.Result().dispatched && skills.Result().nativeResultKnown
              && skills.Result().nativeResult == 0 && skills.Result().reason == "native_skill_rejected",
          "native_zero_was_reported_as_skill_admission");
    skills.Request(skill);
    Check(!skills.Consume(context,
                          [](std::uint32_t, int&, std::string& error) {
                              error = "character_changed";
                              return false;
                          })
              && !skills.Result().nativeResultKnown && skills.Result().reason == "character_changed",
          "failed_entry_was_reported_as_native_result");
    skills.Request(skill);
    Check(skills.Consume(context,
                         [&](std::uint32_t, int&, std::string& error) {
                             skills.Request(skill);
                             error = "old_entry_failed";
                             return false;
                         })
              && skills.Pending() && !skills.Result().nativeResultKnown
              && skills.Result().reason == "native_skill_pending",
          "old_callback_overwrote_or_failed_successor_request");
}
}

int main(int argc, char** argv) {
    Check(argc == 2, "expected GUI input scenario");
    const std::string scenario = argv[1];
    if (scenario == "modal")
        ModalProgress();
    else if (scenario == "slot-changes")
        ModalSlotChanges();
    else if (scenario == "undispatched")
        UndispatchedRequests();
    else if (scenario == "skill-consumption")
        SkillConsumption();
    else
        Check(false, "unknown GUI input scenario");
}
