// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Runtime.h"

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

// The fixture owns sampled state and input consumption, not Lua scheduling.
class NativeBoundary final : public MapleControl::Adapter {
public:
    struct Input {
        std::string direction;
        bool interrupted = false;
    };

    NativeBoundary() {
        state.instanceId = "contract-instance";
        state.inGame = state.ready = state.mapKnown = state.characterKnown = state.positionKnown = true;
        state.sceneGeneration = 1;
        state.mapId = 50000;
        state.character.id = 1;
        state.character.values[6] = 100;
        state.character.known.fill(true);
    }

    const char* Backend() const override { return "contract"; }
    const MapleControl::State& Observe() const override { return state; }
    bool Supports(MapleControl::ActionKind) const override { return true; }
    bool Begin(const MapleControl::Action& action, std::string& error) override {
        if (!Released()) { error = "native_input_still_owned"; return false; }
        inputs.push_back({action.direction});
        active = true;
        remaining = static_cast<int>(action.durationMs / 20);
        if (remaining == 0) remaining = 1;
        result = {};
        result.dispatched = true;
        result.reason = "native_input_" + std::to_string(inputs.size());
        return true;
    }
    MapleControl::ActionResult Result() const override {
        auto snapshot = result;
        snapshot.controlReleased = Released();
        return snapshot;
    }
    void Release() override {
        if (active) inputs.back().interrupted = true;
        active = false;
        releasing = 3;
    }
    bool Released() const override { return !active && releasing == 0; }
    bool ReleasePending() const override { return releasing != 0; }
    bool Logs(const std::string&, const std::vector<std::string>&) override { return true; }
    bool SupportsRawKeys() const override { return true; }
    bool RawKeys(const std::vector<std::string>& keys, std::uint32_t duration, std::string& error) override {
        Check(keys.size() == 1 && (keys.front() == "Left" || keys.front() == "Right"), "unexpected_native_key");
        MapleControl::Action action;
        action.kind = MapleControl::ActionKind::Move;
        action.direction = keys.front() == "Right" ? "right" : "left";
        action.durationMs = duration;
        return Begin(action, error);
    }

    void Advance() {
        ++state.sequence;
        if (releasing != 0) --releasing;
        if (active) {
            state.x += inputs.back().direction == "right" ? 1 : -1;
            if (--remaining == 0) {
                active = false;
                releasing = 3;
            }
        }
    }

    MapleControl::State state;
    std::vector<Input> inputs;
    bool active = false;
    int remaining = 0;
    int releasing = 0;
    MapleControl::ActionResult result;
};

const char* collaboration = R"lua(
local started, replanned, retreating = false, false, false
game.spawn("chase", 10, function()
    game.acquire()
    local before = game.state()
    started = true
    local interrupted = game.move("right", 0.5)
    assert(interrupted.dispatched and interrupted.control_released)
    assert(interrupted.reason == "control_preempted" and interrupted.effect == "unknown")
    game.acquire()
    local after = game.state()
    assert(after.seq > before.seq and after.position.x < before.position.x, "fresh_replan_missing")
    local resumed = game.move(after.position.x < before.position.x and "left" or "right", 0.06)
    assert(resumed.reason == "native_input_3", "action_result_from_other_task")
    replanned = true
    game.move("right", 0.5)
    while true do game.sleep(0) end
end)
game.spawn("retreat", 20, function()
    while not started do game.sleep(0) end
    local waiting = false
    for _, task in ipairs(game.tasks().tasks) do
        if task.name == "chase" then waiting = task.status == "waiting" and task.wait == "action" end
    end
    assert(waiting, "observer_did_not_advance_during_action")
    game.acquire()
    assert(game.tasks().control.owner == "retreat")
    local result = game.move("left", 0.1)
    assert(result.reason == "native_input_2" and result.effect == "unknown")
    game.stop()
    while not replanned do game.sleep(0) end
    game.acquire()
    retreating = true
    local final = game.move("left", 0.2)
    assert(final.reason == "native_input_5" and final.control_released)
    for _, task in ipairs(game.tasks().tasks) do
        if task.name == "chase" then assert(task.status == "cancelled") end
    end
    game.stop()
end)
while not retreating do game.sleep(0) end
assert(game.tasks().control.owner == "retreat")
assert(game.cancel("chase"))
assert(game.tasks().control.owner == "retreat", "cancel_released_successor")
)lua";

const char* cancelled = R"lua(
game.spawn("chase", 10, function()
    game.acquire()
    game.move("right", 0.5)
    error("cancelled_chase_resumed")
end)
game.spawn("observer", 20, function()
    while true do game.state(); game.sleep(0) end
end)
)lua";

const char* single = R"lua(
local first = game.move("right", 0.04)
assert(first.dispatched and first.control_released)
game.stop()
local second = game.move("left", 0.04)
assert(second.dispatched and second.control_released)
game.stop()
)lua";

const char* rawKeys = R"lua(
local holding, stopping, stopped = false, false, false
game.spawn("old", 10, function()
    game.acquire()
    local completed = game.move("right", 0.04)
    assert(completed.dispatched and completed.control_released)
    game.keys("Right", 0.5)
    holding = true
    game.sleep(0)
    stopping = true
    local before = game.state().seq
    local released = game.stop()
    assert(released.control_released and game.state().seq >= before + 3, "stale_result_skipped_key_release")
    stopped = true
    assert(game.tasks().control.owner == "new")
    assert(game.stop().reason == "control_not_owned")
end)
game.spawn("new", 20, function()
    while not holding do game.sleep(0) end
    game.acquire()
    assert(stopping, "old_task_could_not_stop_during_release")
    game.keys("Left", 0.2)
    while not stopped do game.sleep(0) end
    for _ = 1, 15 do game.sleep(0) end
    assert(game.tasks().control.owner == "new")
    game.stop()
end)
)lua";

const char* lifecycle = R"lua(
local function exercise(mode)
    collectgarbage("collect")
    local before = collectgarbage("count")
    for index = 1, 20 do
        local name = mode .. "_" .. index
        game.spawn(name, 1, function()
            local payload = string.rep("x", 1024 * 1024)
            if mode == "cancel" then game.sleep(30)
            elseif mode == "self_cancel" then game.cancel(name) end
            return payload
        end)
        game.sleep(0)
        if mode == "cancel" then assert(game.cancel(name)) end
    end
    collectgarbage("collect")
    local growth = collectgarbage("count") - before
    local ended = 0
    for _, task in ipairs(game.tasks().tasks) do
        if string.sub(task.name, 1, #mode + 1) == mode .. "_" then
            assert(task.status == (mode == "return" and "completed" or "cancelled"))
            ended = ended + 1
        end
    end
    assert(ended == 20, "task_history_missing")
    return growth
end
local cancelled = exercise("cancel")
local returned = exercise("return")
local self_cancelled = exercise("self_cancel")
assert(cancelled < 512 and returned < 512 and self_cancelled < 512,
    string.format("retained_task_payload_kib: cancel=%.1f return=%.1f self_cancel=%.1f",
        cancelled, returned, self_cancelled))
)lua";
}


MapleControl::TaskStatus LatestTask(MapleControl::Runtime& runtime, const std::string& name) {
    const auto* status = runtime.CurrentStatus();
    for (auto task = status->tasks.rbegin(); task != status->tasks.rend(); ++task)
        if (task->name == name) return *task;
    Check(false, "task_missing: " + name);
    return {};
}

void Advance(MapleControl::Runtime& runtime, NativeBoundary& native, int count) {
    for (int tick = 0; tick < count; ++tick) {
        native.Advance();
        runtime.Tick();
    }
}

void LiveTaskChanges() {
    NativeBoundary native;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("live-session", R"lua(
local hidden = "local_only"
observations = 0
game.spawn("watch", 1, function()
    while true do observations = observations + 1; game.sleep(0) end
end)
game.spawn("chase", 10, function()
    game.acquire()
    game.move("right", 10)
    while true do game.sleep(0) end
end)
)lua", 5000, error), error);
    Advance(runtime, native, 3);
    Check(native.active && runtime.CurrentStatus()->control.owner == "chase", "initial_owner_missing");
    const auto original = LatestTask(runtime, "chase");
    MapleControl::TaskChange change;
    change.requestId = "append";
    change.scriptId = "live-session";
    change.name = "added";
    change.priority = 1;
    change.source = R"lua(
assert(hidden == nil and observations > 0, "injected_source_scope_wrong")
local before = observations
game.sleep(0)
assert(observations > before, "original_observer_stopped")
for _, task in ipairs(game.tasks().tasks) do assert(task.revision > 0) end
)lua";
    auto result = runtime.ManageTask(change);
    Check(result.status == "completed" && result.changed && result.revision > original.revision,
          "task_append_not_installed");
    Advance(runtime, native, 3);
    Check(LatestTask(runtime, "added").status == "completed" && native.active,
          "new_task_or_original_action_did_not_continue");
    change.operation = MapleControl::TaskOperation::Replace;
    change.name = "chase";
    change.expectedRevision = original.revision;
    change.requestId = "invalid-replacement";
    change.source = "local = invalid";
    result = runtime.ManageTask(change);
    Check(result.status == "rejected" && result.reason == "task_load_error" && !result.error.empty(),
          "invalid_replacement_not_rejected");
    Check(native.active && !native.ReleasePending() && native.inputs.size() == 1 &&
          runtime.CurrentStatus()->control.owner == "chase" && LatestTask(runtime, "chase").revision == original.revision,
          "compile_error_changed_original_owner");
    change.requestId = "replace";
    change.priority = 10;
    change.source = "game.acquire(); game.move('left', 10); while true do game.sleep(0) end";
    result = runtime.ManageTask(change);
    Check(result.status == "pending" && native.ReleasePending(), "replacement_skipped_release_ack");
    const auto rejected = runtime.ManageTask(change);
    Check(rejected.reason == "task_management_busy" && runtime.CurrentTaskChange()->requestId == "replace",
          "rejected_request_overwrote_pending_replacement");
    Advance(runtime, native, 2);
    Check(native.inputs.size() == 1 && runtime.Running(), "replacement_started_before_release_ack");
    Advance(runtime, native, 2);
    const auto replacement = LatestTask(runtime, "chase");
    Check(replacement.revision > original.revision && native.inputs.size() == 2 && native.active &&
          native.inputs.back().direction == "left", "replacement_not_started");
    result = *runtime.CurrentTaskChange();
    Check(result.status == "completed" && result.controlReleased && result.revision == replacement.revision,
          "replacement_result_missing");
    change.operation = MapleControl::TaskOperation::Stop;
    change.requestId = "late-stop";
    result = runtime.ManageTask(change);
    Check(result.reason == "task_revision_mismatch" && native.active && !native.ReleasePending(),
          "old_revision_stopped_replacement");
    change.scriptId = "old-session";
    change.expectedRevision = replacement.revision;
    result = runtime.ManageTask(change);
    Check(result.reason == "script_session_mismatch" && native.active, "old_session_changed_task");
    change.scriptId = "live-session";
    change.requestId = "stop";
    result = runtime.ManageTask(change);
    Check(result.status == "pending" && native.ReleasePending(), "stop_skipped_own_release_ack");
    Advance(runtime, native, 3);
    result = *runtime.CurrentTaskChange();
    Check(result.status == "completed" && result.changed && result.controlReleased && runtime.Running(),
          "target_stop_cancelled_other_tasks");
    Check(LatestTask(runtime, "watch").status == "waiting", "observer_stopped_with_target");
    result = runtime.ManageTask(change);
    Check(result.status == "completed" && !result.changed, "terminal_stop_not_idempotent");
    change.operation = MapleControl::TaskOperation::Add;
    change.name = "failing";
    change.requestId = "runtime-error";
    change.source = "error('injected-runtime-error')";
    Check(runtime.ManageTask(change).status == "completed", "valid_error_source_not_compiled");
    Advance(runtime, native, 3);
    Check(!runtime.Running() && runtime.CurrentStatus()->reason == "script_error" &&
          runtime.CurrentStatus()->error.find("injected-runtime-error") != std::string::npos,
          "injected_runtime_error_did_not_preserve_session_error_semantics");
}

void LastTaskReplacement() {
    NativeBoundary native;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("last-session", R"lua(
game.spawn("only", 10, function()
    game.acquire(); game.move("right", 10)
end)
)lua", 5000, error), error);
    Advance(runtime, native, 3);
    MapleControl::TaskChange change;
    change.requestId = "last-replacement";
    change.scriptId = "last-session";
    change.name = "only";
    change.operation = MapleControl::TaskOperation::Replace;
    change.expectedRevision = LatestTask(runtime, "only").revision;
    change.priority = 10;
    change.source = "game.acquire(); game.move('left', 10)";
    Check(runtime.ManageTask(change).status == "pending", "last_task_replacement_not_pending");
    Advance(runtime, native, 2);
    Check(runtime.Running(), "last_task_replacement_ended_session_early");
    Advance(runtime, native, 2);
    Check(native.inputs.size() == 2 && native.active && runtime.Running(), "last_replacement_not_installed");
    change.requestId = "cancelled-replacement";
    change.expectedRevision = LatestTask(runtime, "only").revision;
    change.source = "game.acquire(); game.move('right', 10)";
    Check(runtime.ManageTask(change).status == "pending", "second_replacement_not_pending");
    runtime.Cancel("contract_cancel");
    Check(runtime.CurrentTaskChange()->status == "cancelled", "session_cancel_left_pending_replacement");
    Advance(runtime, native, 3);
    Check(!runtime.Running() && native.Released() && native.inputs.size() == 2,
          "replacement_installed_after_session_cancel");
}

int main(int argc, char** argv) {
    Check(argc == 2, "expected contract scenario");
    if (std::string(argv[1]) == "live-changes") { LiveTaskChanges(); return 0; }
    if (std::string(argv[1]) == "last-replacement") { LastTaskReplacement(); return 0; }
    const bool cancel = std::string(argv[1]) == "cancel";
    const bool ordinary = std::string(argv[1]) == "single";
    const bool keys = std::string(argv[1]) == "raw-keys";
    const bool lifetime = std::string(argv[1]) == "lifecycle";
    NativeBoundary native;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("runtime-contract", lifetime ? lifecycle : keys ? rawKeys : ordinary ? single
                        : cancel ? cancelled : collaboration, 5000, error), error);
    bool cancellationSent = false;
    for (int tick = 0; tick < 200 && runtime.Running(); ++tick) {
        native.Advance();
        runtime.Tick();
        if (cancel && native.active && !cancellationSent) {
            runtime.Cancel("contract_cancel");
            cancellationSent = true;
            Check(runtime.Running() && native.ReleasePending(), "cancel_did_not_wait_for_native_release");
        }
    }
    const auto* status = runtime.CurrentStatus();
    Check(!runtime.Running(), "runtime_did_not_finish");
    Check(status->error.empty(), status->error);
    Check(native.Released(), "terminal_state_before_native_release");
    if (cancel) {
        Check(cancellationSent && status->status == "cancelled" && status->reason == "contract_cancel",
              "session_cancellation_result_missing");
        Check(native.inputs.size() == 1, "task_dispatched_after_session_cancel");
        Check(status->control.owner.empty(), "session_cancel_retained_control_owner");
        for (const auto& task : status->tasks)
            Check(task.status == "cancelled" || task.status == "completed", "session_cancel_left_task_running");
    } else if (lifetime) {
        Check(status->status == "completed" && native.inputs.empty(), "task_lifecycle_contract_did_not_complete");
    } else if (keys) {
        Check(status->status == "completed", "raw_keys_handoff_did_not_complete");
        Check(native.inputs.size() == 3 && !native.inputs[0].interrupted && native.inputs[1].interrupted
              && !native.inputs[2].interrupted, "old_task_released_successor_keys");
    } else if (ordinary) {
        Check(status->status == "completed", "single_script_did_not_complete");
        Check(native.inputs.size() == 2 && native.inputs[0].direction == "right"
              && native.inputs[1].direction == "left", "move_after_stop_missing");
        Check(runtime.Start("next-script", "game.move('right', 0.02); game.stop()", 5000, error), error);
        for (int tick = 0; tick < 30 && runtime.Running(); ++tick) {
            native.Advance();
            runtime.Tick();
        }
        const auto* next = runtime.CurrentStatus();
        Check(!runtime.Running() && next->status == "completed" && next->error.empty(),
              "runtime_cannot_start_next_script: " + next->error);
        Check(native.inputs.size() == 3 && native.Released(), "next_script_did_not_release");
    } else {
        Check(status->status == "completed", "collaboration_did_not_complete");
        Check(native.inputs.size() == 5, "stale_action_replayed_or_expected_action_missing");
        Check(native.inputs[0].direction == "right" && native.inputs[0].interrupted,
              "chase_was_not_preempted");
        Check(native.inputs[1].direction == "left" && !native.inputs[1].interrupted,
              "first_retreat_was_interrupted");
        Check(native.inputs[2].direction == "left" && !native.inputs[2].interrupted,
              "chase_did_not_replan_from_current_state");
        Check(native.inputs[3].direction == "right" && native.inputs[3].interrupted,
              "second_chase_was_not_preempted");
        Check(native.inputs[4].direction == "left" && !native.inputs[4].interrupted,
              "cancelling_old_task_released_successor_input");
    }
}
