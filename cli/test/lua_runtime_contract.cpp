// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Runtime.h"

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

// The fixture owns sampled state and input consumption, not Lua scheduling.
class NativeBoundary : public MapleControl::Adapter {
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
        if (!Released()) {
            error = "native_input_still_owned";
            return false;
        }
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

// Native domain values are fixtures; the real Runtime owns Lua projection and lifecycle checks.
class ObservationBoundary final : public NativeBoundary {
public:
    MapleControl::Observation ObserveDomain(const std::string& domain) const override {
        queries.push_back(domain);
        using MapleControl::Value;
        if (domain == "stage") return {"ok", Value::Object({{"stage", state.ready ? "IN_GAME" : "STARTING"}}), {}};
        if (domain == "scene")
            return {"ok",
                    Value::Object({{"map_id", state.mapId},
                                   {"npcs", Value::Array({Value::Object(
                                                {{"object_id", 3}, {"name", npcName}, {"x", 12.5}, {"y", -4}})})}}),
                    {}};
        if (domain == "character")
            return {"ok",
                    Value::Object(
                        {{"mesos", 0},
                         {"skills", Value::Object({{"2000001", Value::Object({{"level", 1}, {"master_level", {}}})}})},
                         {"unavailable", Value::Array()}}),
                    {}};
        if (domain == "quests")
            return {
                "ok",
                Value::Object({{"source", "character_data_snapshot"},
                               {"live_updates", false},
                               {"quests", Value::Array({Value::Object({{"quest_id", 1037}, {"progress", "001"}})})}}),
                {}};
        if (domain == "shop") return {"unavailable", {}, "native_shop_read_unavailable"};
        return {"unsupported", {}, "unsupported_observation_domain"};
    }

    mutable std::vector<std::string> queries;
    std::string npcName = "向导";
};

// This boundary controls native completion; it does not simulate inventory packets or equipment rules.
class ConfirmationBoundary final : public NativeBoundary {
public:
    MapleControl::Observation ObserveDomain(const std::string& domain) const override {
        if (domain != "interaction") return NativeBoundary::ObserveDomain(domain);
        using MapleControl::Value;
        return {"ok",
                Value::Object(
                    {{"page", Value::Object(
                                  {{"source", "native_fixture"},
                                   {"title", "Panel"},
                                   {"text", "Current page"},
                                   {"controls", Value::Array({Value::Object({{"role", "button"},
                                                                             {"text", "Next"},
                                                                             {"enabled", true},
                                                                             {"ref", "opaque-native-control"}})})}})}}),
                {}};
    }

    bool Supports(MapleControl::ActionKind kind) const override {
        if (kind == MapleControl::ActionKind::Revive) return reviveSupported;
        if (kind == MapleControl::ActionKind::Activate) return activateSupported;
        return (kind != MapleControl::ActionKind::Equip && kind != MapleControl::ActionKind::Unequip)
               || equipmentSupported;
    }

    bool Begin(const MapleControl::Action& action, std::string&) override {
        Check(!pending, "equipment_request_was_replayed_before_confirmation");
        requests.push_back(action);
        pending = true;
        result = {};
        result.dispatched = true;
        return true;
    }

    MapleControl::ActionResult Result() const override { return result; }

    void Release() override {
        if (!pending) return;
        Complete("unknown", "equipment_request_cancelled");
    }

    bool Released() const override { return !pending; }

    bool ReleasePending() const override { return false; }

    void Complete(const std::string& effect, const std::string& reason) {
        pending = false;
        result.controlReleased = true;
        result.effect = effect;
        result.reason = reason;
    }

    std::vector<MapleControl::Action> requests;
    bool pending = false;
    bool equipmentSupported = true;
    bool reviveSupported = true;
    bool activateSupported = true;
};

// The native callback re-enters the real scheduler; it does not model NPCs.
class ReentrantBoundary final : public NativeBoundary {
public:
    bool RawKeys(const std::vector<std::string>& keys, std::uint32_t duration, std::string& error) override {
        Check(keys == std::vector<std::string>{"space"}, "unexpected_reentrant_key");
        MapleControl::Action action;
        action.kind = MapleControl::ActionKind::Jump;
        action.durationMs = duration;
        if (!Begin(action, error)) return false;
        ++rawCallbacks;
        Callback();
        return true;
    }

    void Release() override {
        NativeBoundary::Release();
        ++releaseCallbacks;
        if (acknowledgeRelease)
            while (ReleasePending()) NativeBoundary::Advance();
        Callback();
    }

    bool Logs(const std::string&, const std::vector<std::string>& lines) override {
        for (const auto& line : lines)
            if (line.find("observer_tick") != std::string::npos) ++observerLogs;
        return true;
    }

    void Callback() {
        const auto resumes = runtime->CurrentStatus()->resumes;
        const auto taskCount = runtime->CurrentStatus()->tasks.size();
        runtime->Tick();
        const auto* status = runtime->CurrentStatus();
        Check(status->error.empty(), "native_callback_resumed_active_thread: " + status->error);
        Check(status->resumes == resumes, "native_callback_advanced_coroutine_twice");
        MapleControl::TaskChange change;
        change.requestId = "native-callback-management";
        change.scriptId = status->id;
        change.name = "nested";
        change.source = "error('unexpected_nested_task')";
        const auto result = runtime->ManageTask(change);
        Check(result.status == "rejected" && result.reason == "task_management_busy",
              "native_callback_mutated_running_tasks: " + result.reason);
        Check(runtime->CurrentStatus()->tasks.size() == taskCount, "native_callback_added_task");
    }

    MapleControl::Runtime* runtime = nullptr;
    bool acknowledgeRelease = false;
    int rawCallbacks = 0;
    int releaseCallbacks = 0;
    int observerLogs = 0;
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
)lua",
                        5000, error),
          error);
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
    Check(native.active && !native.ReleasePending() && native.inputs.size() == 1
              && runtime.CurrentStatus()->control.owner == "chase"
              && LatestTask(runtime, "chase").revision == original.revision,
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
    Check(replacement.revision > original.revision && native.inputs.size() == 2 && native.active
              && native.inputs.back().direction == "left",
          "replacement_not_started");
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
    Check(!runtime.Running() && runtime.CurrentStatus()->reason == "script_error"
              && runtime.CurrentStatus()->error.find("injected-runtime-error") != std::string::npos,
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
)lua",
                        5000, error),
          error);
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

void ReentrantCallbacks() {
    for (const bool press : {true, false}) {
        ReentrantBoundary native;
        MapleControl::Runtime runtime(native);
        native.runtime = &runtime;
        std::string error;
        Check(runtime.Start(press ? "reentrant-press" : "reentrant-release",
                            press ? "game.press('space',0.08);game.sleep(0.2)" : "game.keys('space',0.08)", 3000,
                            error),
              error);
        for (int tick = 0; tick < 60 && runtime.Running(); ++tick) {
            native.Advance();
            runtime.Tick();
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        const auto* status = runtime.CurrentStatus();
        Check(!runtime.Running() && status->status == "completed" && status->error.empty(),
              "reentrant_script_did_not_complete: " + status->error);
        Check(native.inputs.size() == 1 && native.rawCallbacks == 1, "native_callback_replayed_key");
        Check(native.Released() && native.releaseCallbacks == (press ? 0 : 1), "native_release_not_confirmed");
        Check(status->resumes == (press ? 3 : 1), "original_coroutine_advanced_twice");
        Check(native.inputs.front().interrupted == !press, "press_did_not_release_naturally");
    }
}

void ManagementCallbacks() {
    for (const auto operation : {MapleControl::TaskOperation::Replace, MapleControl::TaskOperation::Stop}) {
        ReentrantBoundary native;
        MapleControl::Runtime runtime(native);
        native.runtime = &runtime;
        native.acknowledgeRelease = true;
        std::string error;
        Check(runtime.Start("management-callback", R"lua(
game.spawn("observer", 0, function()
    while true do game.log("observer_tick"); game.sleep(0) end
end)
game.spawn("target", 10, function()
    game.acquire()
    game.move("right", 10)
    game.move("right", 0.02)
end)
)lua",
                            3000, error),
              error);
        Advance(runtime, native, 3);
        Check(native.active && native.inputs.size() == 1, "management_target_not_waiting_on_input");
        const auto observedBefore = native.observerLogs;
        const auto oldRevision = LatestTask(runtime, "target").revision;
        MapleControl::TaskChange change;
        change.requestId = "external-management";
        change.scriptId = "management-callback";
        change.name = "target";
        change.operation = operation;
        change.expectedRevision = oldRevision;
        if (operation == MapleControl::TaskOperation::Replace) {
            change.priority = 10;
            change.source = "game.acquire(); game.move('left',0.04); game.stop()";
        }
        const auto result = runtime.ManageTask(change);
        Check(result.status == "completed" && result.changed && result.controlReleased,
              "external_management_did_not_complete: " + result.reason);
        Advance(runtime, native, 12);
        Check(runtime.Running() && runtime.CurrentStatus()->error.empty(), "management_callback_cancelled_session");
        Check(native.observerLogs > observedBefore, "management_callback_stopped_observer");
        Check(native.inputs.front().interrupted && native.releaseCallbacks == 1 && native.Released(),
              "management_release_not_confirmed");
        if (operation == MapleControl::TaskOperation::Replace) {
            Check(native.inputs.size() == 2 && native.inputs.back().direction == "left"
                      && !native.inputs.back().interrupted,
                  "replacement_did_not_acquire_and_finish");
            Check(result.revision != oldRevision && LatestTask(runtime, "target").status == "completed",
                  "replacement_version_not_completed");
        } else
            Check(native.inputs.size() == 1 && LatestTask(runtime, "target").status == "cancelled",
                  "stopped_task_resumed");
        runtime.Cancel("contract_cancel");
        Advance(runtime, native, 3);
        Check(!runtime.Running() && native.Released(), "management_callback_cleanup_not_confirmed");
    }
}

void DomainObservations() {
    ObservationBoundary native;
    native.state.observedAtMs = 1000;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("domain-observations", R"lua(
assert(game.state().in_game)
game.sleep(0)
local character = game.observe("character")
assert(character.status == "ok" and character.source == "client-native-api" and character.readonly)
assert(character.backend == "contract" and character.instance_id == "contract-instance")
assert(character.character_id == 1 and character.map_id == 50000 and character.scene_generation == 1)
assert(character.ready and character.in_game and character.observed_at_ms == 1000)
assert(character.data.mesos == 0 and character.data.skills["2000001"].level == 1)
assert(character.data.skills["2000001"].master_level == nil and #character.data.unavailable == 0)
local quests = game.observe("quests")
assert(quests.data.source == "character_data_snapshot" and quests.data.live_updates == false)
assert(quests.data.quests[1].quest_id == 1037 and quests.data.quests[1].progress == "001")
assert(quests.data.source_updated_at_ms == nil)
local old = game.observe("scene")
assert(old.data.npcs[1].name == "向导" and old.data.npcs[1].x == 12.5 and old.data.npcs[1].y == -4)
assert(tostring(old.data.npcs[1].object_id) == "3" and math.type(old.data.npcs[1].x) == "float")
old.data.npcs[1].name = "仅修改脚本副本"
assert(game.observe("scene").data.npcs[1].name == "向导")
game.sleep(0)
local current = game.observe("scene")
assert(current.seq > old.seq and current.observed_at_ms == 2000)
assert(current.scene_generation == 2 and current.map_id == 50001 and current.data.map_id == 50001)
assert(current.data.npcs[1].name == "新场景向导")
assert(old.scene_generation == 1 and old.map_id == 50000 and old.observed_at_ms == 1000)
assert(old.data.npcs[1].name == "仅修改脚本副本")
)lua",
                        5000, error),
          error);
    Advance(runtime, native, 1);
    Check(native.queries.empty(), "domain_sampling_was_not_on_demand");
    Advance(runtime, native, 1);
    Check(native.queries.size() == 4, "unexpected_domain_reads_before_next_scene");
    native.state.mapId = 50001;
    native.state.sceneGeneration = 2;
    native.state.observedAtMs = 2000;
    native.npcName = "新场景向导";
    Advance(runtime, native, 5);
    const auto* status = runtime.CurrentStatus();
    Check(!runtime.Running() && status->status == "completed" && status->error.empty(), status->error);
    Check(native.queries.size() == 5 && native.inputs.empty(), "domain_reads_dispatched_or_repeated_actions");
}

void DomainAvailability() {
    ObservationBoundary native;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("domain-availability", R"lua(
local ui = game.observe("ui")
assert(ui.status == "unsupported" and ui.data == nil and ui.error == "unsupported_observation_domain")
local shop = game.observe("shop")
assert(shop.status == "unavailable" and shop.data == nil and shop.error == "native_shop_read_unavailable")
game.sleep(0)
local scene = game.observe("scene")
assert(scene.status == "unavailable" and scene.error == "native_client_not_in_game" and scene.data == nil)
assert(not scene.ready and scene.in_game and scene.map_id == nil and scene.character_id == nil)
assert(game.observe("stage").data.stage == "STARTING")
game.sleep(0)
game.observe("scene")
error("query_resumed_for_another_character")
)lua",
                        5000, error),
          error);
    Advance(runtime, native, 1);
    Check(native.queries.size() == 2, "supported_and_unavailable_queries_not_dispatched");
    native.state.ready = native.state.mapKnown = native.state.characterKnown = false;
    Advance(runtime, native, 1);
    Check(native.queries == std::vector<std::string>({"ui", "shop", "stage"}),
          "unready_scene_reused_native_domain_data");
    native.state.ready = native.state.characterKnown = true;
    native.state.character.id = 2;
    Advance(runtime, native, 5);
    const auto* status = runtime.CurrentStatus();
    Check(!runtime.Running() && status->status == "cancelled" && status->reason == "character_changed"
              && status->error.empty(),
          "old_character_observation_task_not_cancelled");
    Check(native.queries.size() == 3, "queried_domains_after_character_changed");
    Check(runtime.Start("invalid-domain", "game.observe('missing')", 5000, error), error);
    Advance(runtime, native, 5);
    status = runtime.CurrentStatus();
    Check(!runtime.Running() && status->reason == "script_error"
              && status->error.find("invalid option") != std::string::npos,
          "unknown_domain_was_not_rejected");
    Check(native.queries.size() == 3 && native.inputs.empty(), "invalid_domain_reached_native_collector");
}

void EquipmentRequests() {
    ConfirmationBoundary native;
    native.state.inventoryKnown = true;
    native.state.inventory = {{1, 1, 1002001, 1, true}, {1, 2, 1002001, 1, true}};
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("equipment-requests", R"lua(
assert(game.capabilities().equip and game.capabilities().unequip)
local items = game.state().inventory
assert(items[1].item_id == items[2].item_id)
local equipped = game.equip(items[2].slot, -5)
assert(equipped.dispatched and equipped.control_released and equipped.effect == "confirmed")
local removed = game.unequip(-5, 7, 1.25)
assert(removed.dispatched and removed.control_released and removed.effect == "unknown")
assert(removed.reason == "equipment_confirmation_timeout")
)lua",
                        5000, error),
          error);
    Advance(runtime, native, 3);
    Check(runtime.Running() && native.pending && native.requests.size() == 1,
          "equipment_returned_before_native_confirmation");
    const auto& equip = native.requests.front();
    Check(equip.kind == MapleControl::ActionKind::Equip && equip.sourceSlot == 2 && equip.destinationSlot == -5
              && equip.durationMs == 3000,
          "equipment_source_slot_or_default_deadline_was_not_preserved");
    native.Complete("confirmed", "equipment_changed");
    Advance(runtime, native, 1);
    Check(runtime.Running() && native.pending && native.requests.size() == 2,
          "confirmed_equipment_did_not_advance_to_unequip");
    const auto& unequip = native.requests.back();
    Check(unequip.kind == MapleControl::ActionKind::Unequip && unequip.sourceSlot == -5 && unequip.destinationSlot == 7
              && unequip.durationMs == 1250,
          "unequip_slots_or_explicit_deadline_were_not_preserved");
    native.Complete("unknown", "equipment_confirmation_timeout");
    Advance(runtime, native, 3);
    const auto* status = runtime.CurrentStatus();
    Check(!runtime.Running() && status->status == "completed" && status->error.empty(), status->error);
    Check(native.requests.size() == 2 && native.Released(), "equipment_request_was_resent");
}

void EquipmentCancellationAndRejection() {
    ConfirmationBoundary native;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("cancel-equipment", "game.equip(4,-6,0.5); error('resumed_after_cancel')", 5000, error), error);
    Advance(runtime, native, 1);
    runtime.Cancel("contract_cancel");
    Advance(runtime, native, 3);
    const auto* status = runtime.CurrentStatus();
    Check(!runtime.Running() && status->status == "cancelled" && status->reason == "contract_cancel"
              && status->error.empty(),
          "equipment_cancel_resumed_old_task");
    Check(native.requests.size() == 1 && native.Released() && native.Result().effect == "unknown",
          "cancelled_equipment_was_replayed_or_reported_confirmed");
    native.equipmentSupported = false;
    Check(runtime.Start("unsupported-equipment", R"lua(
assert(not game.capabilities().equip and not game.capabilities().unequip)
game.equip(1,-5)
)lua",
                        5000, error),
          error);
    Advance(runtime, native, 3);
    Check(runtime.CurrentStatus()->reason == "script_error"
              && runtime.CurrentStatus()->error.find("unsupported: equip") != std::string::npos,
          "unsupported_equipment_was_not_rejected");
    native.equipmentSupported = true;
    for (const auto* source : {"game.equip(0,-5)", "game.unequip(-5,0)"}) {
        Check(runtime.Start("invalid-equipment-slot", source, 5000, error), error);
        Advance(runtime, native, 3);
        Check(runtime.CurrentStatus()->reason == "script_error", "invalid_equipment_slot_was_not_rejected");
    }
    Check(native.requests.size() == 1, "rejected_equipment_reached_native_dispatch");
}

void ReviveRequests() {
    ConfirmationBoundary native;
    native.state.character.values[6] = 0;
    native.state.dead = native.state.reviveRequestable = MapleControl::Fact::True;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("revive-request", R"lua(
assert(game.capabilities().revive)
assert(game.state().dead and game.state().revive_requestable)
local result = game.revive(1.25)
assert(result.dispatched and result.control_released and result.effect == "confirmed")
assert(result.reason == "revive_confirmed" and not game.state().dead)
)lua",
                        5000, error),
          error);
    Advance(runtime, native, 2);
    Check(native.pending && native.requests.size() == 1, "revive_did_not_wait_for_native_confirmation");
    Check(native.requests[0].kind == MapleControl::ActionKind::Revive && native.requests[0].durationMs == 1250,
          "revive_deadline_or_action_kind_lost");
    ++native.state.sceneGeneration;
    native.state.mapId = 10000;
    runtime.Tick(true);
    Advance(runtime, native, 2);
    Check(runtime.Running() && native.pending && native.requests.size() == 1,
          "revive_map_arrival_completed_or_resent_the_request");
    native.state.character.values[6] = 50;
    native.state.dead = native.state.reviveRequestable = MapleControl::Fact::False;
    native.Complete("confirmed", "revive_confirmed");
    Advance(runtime, native, 3);
    Check(!runtime.Running() && runtime.CurrentStatus()->status == "completed" && runtime.CurrentStatus()->error.empty()
              && native.requests.size() == 1,
          runtime.CurrentStatus()->error);

    Check(runtime.Start("revive-unconfirmed", R"lua(
local result = game.revive()
assert(result.dispatched and result.effect == "unknown" and result.reason == "revive_not_confirmed")
)lua",
                        8000, error),
          error);
    Advance(runtime, native, 1);
    Check(native.requests.size() == 2 && native.requests.back().durationMs == 6000, "revive_default_deadline_lost");
    native.Complete("unknown", "revive_not_confirmed");
    Advance(runtime, native, 3);
    Check(!runtime.Running() && runtime.CurrentStatus()->error.empty() && native.requests.size() == 2,
          "unconfirmed_revive_was_replayed_or_reported_successful");
    native.reviveSupported = false;
    native.state.dead = native.state.reviveRequestable = MapleControl::Fact::Unknown;
    Check(runtime.Start("unsupported-revive", R"lua(
assert(not game.capabilities().revive)
assert(game.state().dead == nil and game.state().revive_requestable == nil)
game.revive()
)lua",
                        5000, error),
          error);
    Advance(runtime, native, 3);
    Check(runtime.CurrentStatus()->reason == "script_error"
              && runtime.CurrentStatus()->error.find("unsupported: revive") != std::string::npos
              && native.requests.size() == 2,
          "unsupported_revive_reached_native_dispatch");
}

void ActivationRequests() {
    ConfirmationBoundary native;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("activation", R"lua(
assert(game.capabilities().activate)
assert(game.talk == nil and game.respond == nil and game.quest_start == nil and game.quest_complete == nil)
local observed = game.observe("interaction")
assert(observed.status == "ok")
local control = observed.data.page.controls[1]
assert(control.role == "button" and control.text == "Next" and control.enabled)
local result = game.activate(control.ref)
assert(result.dispatched and result.control_released and result.effect == "unknown")
assert(result.reason == "control_activated")
)lua",
                        3000, error),
          error);
    Advance(runtime, native, 2);
    Check(native.pending && native.requests.size() == 1
              && native.requests.back().kind == MapleControl::ActionKind::Activate
              && native.requests.back().reference == "opaque-native-control",
          "activation_reference_or_wait_lost");
    native.Complete("unknown", "control_activated");
    Advance(runtime, native, 3);
    Check(!runtime.Running() && runtime.CurrentStatus()->error.empty() && native.requests.size() == 1,
          "activation_was_replayed_or_claimed_a_business_result");
    Check(runtime.Start("activation-arguments", "game.activate('opaque-native-control', 3)", 3000, error), error);
    Advance(runtime, native, 2);
    Check(runtime.CurrentStatus()->error.find("activate accepts only a control reference") != std::string::npos
              && native.requests.size() == 1,
          "activation_accepted_protocol_or_budget_arguments");
    native.activateSupported = false;
    Check(runtime.Start("unsupported-activation", R"lua(
assert(not game.capabilities().activate)
game.activate("opaque-native-control")
)lua",
                        3000, error),
          error);
    Advance(runtime, native, 3);
    Check(runtime.CurrentStatus()->reason == "script_error"
              && runtime.CurrentStatus()->error.find("unsupported: activate") != std::string::npos
              && native.requests.size() == 1,
          "unsupported_activation_reached_native_dispatch");
}

int main(int argc, char** argv) {
    Check(argc == 2, "expected contract scenario");
    if (std::string(argv[1]) == "activation-requests") {
        ActivationRequests();
        return 0;
    }
    if (std::string(argv[1]) == "revive-requests") {
        ReviveRequests();
        return 0;
    }
    if (std::string(argv[1]) == "equipment-requests") {
        EquipmentRequests();
        return 0;
    }
    if (std::string(argv[1]) == "equipment-cancellation") {
        EquipmentCancellationAndRejection();
        return 0;
    }
    if (std::string(argv[1]) == "domain-observations") {
        DomainObservations();
        return 0;
    }
    if (std::string(argv[1]) == "domain-availability") {
        DomainAvailability();
        return 0;
    }
    if (std::string(argv[1]) == "live-changes") {
        LiveTaskChanges();
        return 0;
    }
    if (std::string(argv[1]) == "last-replacement") {
        LastTaskReplacement();
        return 0;
    }
    if (std::string(argv[1]) == "reentrant-callbacks") {
        ReentrantCallbacks();
        return 0;
    }
    if (std::string(argv[1]) == "management-callbacks") {
        ManagementCallbacks();
        return 0;
    }
    const bool cancel = std::string(argv[1]) == "cancel";
    const bool ordinary = std::string(argv[1]) == "single";
    const bool keys = std::string(argv[1]) == "raw-keys";
    const bool lifetime = std::string(argv[1]) == "lifecycle";
    NativeBoundary native;
    MapleControl::Runtime runtime(native);
    std::string error;
    Check(runtime.Start("runtime-contract",
                        lifetime   ? lifecycle
                        : keys     ? rawKeys
                        : ordinary ? single
                        : cancel   ? cancelled
                                   : collaboration,
                        5000, error),
          error);
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
                  && !native.inputs[2].interrupted,
              "old_task_released_successor_keys");
    } else if (ordinary) {
        Check(status->status == "completed", "single_script_did_not_complete");
        Check(native.inputs.size() == 2 && native.inputs[0].direction == "right"
                  && native.inputs[1].direction == "left",
              "move_after_stop_missing");
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
        Check(native.inputs[0].direction == "right" && native.inputs[0].interrupted, "chase_was_not_preempted");
        Check(native.inputs[1].direction == "left" && !native.inputs[1].interrupted, "first_retreat_was_interrupted");
        Check(native.inputs[2].direction == "left" && !native.inputs[2].interrupted,
              "chase_did_not_replan_from_current_state");
        Check(native.inputs[3].direction == "right" && native.inputs[3].interrupted, "second_chase_was_not_preempted");
        Check(native.inputs[4].direction == "left" && !native.inputs[4].interrupted,
              "cancelling_old_task_released_successor_input");
    }
}
