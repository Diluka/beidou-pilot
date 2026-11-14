// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TickRuntime.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <map>
#include <string>
#include <thread>
#include <vector>

namespace {
using namespace MapleControl;

void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

Value Field(const Value& object, const std::string& name) {
    for (const auto& member : object.Members())
        if (member.first == name) return member.second;
    return {};
}

Observation Terrain(std::uint32_t mapId, int x) {
    return {"ok",
            Value::Object(
                {{"map_id", mapId},
                 {"source", "local-IMG-contract"},
                 {"footholds",
                  Value::Array({Value::Object(
                      {{"id", 7}, {"x1", x}, {"y1", 0}, {"x2", x + 100}, {"y2", 0}, {"prev", 0}, {"next", 0}})})},
                 {"ropes", Value::Array({Value::Object({{"index", 1}, {"x", x + 50}, {"y1", -50}, {"y2", 0}})})}}),
            {}};
}

class NativeBoundary final : public TickAdapter {
public:
    NativeBoundary() {
        state.instanceId = "tick-contract";
        state.inGame = state.ready = state.mapKnown = state.characterKnown = state.positionKnown = true;
        state.sceneGeneration = 1;
        state.characterUpdatesKnown = true;
        state.mapId = 50000;
        state.character.id = 1;
        state.character.name = "contract";
        state.character.known.fill(true);
        state.character.values[6] = 100;
        state.actionIdle = Fact::True;
        state.monstersKnown = true;
        Monster monster;
        monster.objectId = 7;
        monster.templateId = 100100;
        monster.templateKnown = true;
        monster.name = "snail";
        monster.SetPosition(12, 3);
        monster.active = true;
        monster.hpPercent = 100;
        monster.hpSequence = 1;
        state.monsters.push_back(monster);
    }

    const char* Backend() const override { return "contract"; }

    const State& Observe() const override { return state; }

    Observation ObserveDomain(const std::string& domain) const override {
        ++queries[domain];
        if (onDomain) onDomain(domain);
        if (domain == "terrain") {
            const auto found = terrains.find(state.mapId);
            return found == terrains.end() ? Observation{"unavailable", {}, "local_terrain_missing"} : found->second;
        }
        if (domain == "character")
            return {"ok",
                    Value::Object({{"buffs", {}},
                                   {"buffs_available", false},
                                   {"unavailable", Value::Array({"native_buff_details_unavailable"})}}),
                    {}};
        if (domain == "scene") {
            if (!nativeNpcDomain) return {"ok", {}, {}};
            if (state.npcsKnown) {
                auto npcs = Value::Array();
                for (const auto& npc : state.npcs) {
                    auto row = npc.MotionDocument();
                    row["object_id"] = npc.objectId;
                    row["template_id"] = npc.templateId;
                    row["name"] = npc.name;
                    row["ref"] = "native-npc-reference";
                    npcs.Add(row);
                }
                return {"ok", Value::Object({{"npcs", npcs}}), {}};
            }
            return {
                "ok", Value::Object({{"npcs", Value::Array({Value::Object({{"id", 99}, {"name", "guide"}})})}}), {}};
        }
        if (domain == "inventory")
            return {"ok",
                    Value::Object({{"items", Value::Array({Value::Object({{"item_id", 2000000}, {"quantity", 2}})})}}),
                    {}};
        if (domain == "quests") return {"unavailable", {}, "quest_sample_missing"};
        return {"unsupported", {}, "unsupported_observation_domain"};
    }

    bool Supports(ActionKind kind) const override { return kind != ActionKind::UseItem || supportsItems; }

    bool SupportsSkill() const override { return supportsSkills; }

    // The coroutine adapter still owns Begin/Release. Tick must only change the
    // desired input, leaving native admission and animation completion independent.
    bool Begin(const Action& requested, std::string& error) override {
        ++beginCalls;
        if (!Released()) {
            error = "native_action_busy";
            return false;
        }
        requests.push_back(requested);
        events.push_back("begin");
        active = requested;
        actionActive = legacyDelivery = true;
        state.actionIdle = Fact::False;
        result = {};
        result.sessionId = requested.sessionId;
        result.reason = "native_dispatched";
        return true;
    }

    bool SetActionIntent(const Action& requested, std::string&) override {
        ++intentCalls;
        const bool changed = desired.kind != requested.kind || desired.skillId != requested.skillId
                             || desired.itemId != requested.itemId;
        desired = requested;
        if (!changed) return true;
        armed = desired.kind != ActionKind::Stop;
        actionReleaseTicks = 2; // Native acknowledgement, not the animation timer.
        result.controlReleased = false;
        if (armed) {
            requests.push_back(requested);
            events.push_back("intent");
            if (onIntent) onIntent();
        } else {
            ++releases;
            events.push_back("release_action");
            if (onRelease) onRelease();
        }
        return true;
    }

    bool ActionIntentSettled() const override { return actionReleaseTicks == 0; }

    const Action* ActiveAction() const override { return actionActive ? &active : nullptr; }

    ActionResult Result() const override { return result; }

    void Release() override {
        ReleaseAction();
        actionActive = legacyDelivery = false;
        state.actionIdle = Fact::True;
        if (!directions.empty()) {
            directions.clear();
            directionTicks = 1;
        }
    }

    void ReleaseAction() override {
        ++releases;
        events.push_back("release_action");
        desired = {};
        armed = false;
        actionReleaseTicks = 2;
        result.controlReleased = false;
        if (onRelease) onRelease();
    }

    bool Released() const override {
        return !actionActive && desired.kind == ActionKind::Stop && ActionIntentSettled();
    }

    bool ReleasePending() const override { return !ActionIntentSettled(); }

    bool SetHeldKeys(const std::vector<std::string>& keys, std::string& error) override {
        if (rejectClear && keys.empty()) {
            error = "keyup_not_accepted";
            return false;
        }
        if (keys == directions) return true;
        directions = keys;
        directionTicks = 1;
        changes.push_back(keys);
        events.push_back(keys.empty() ? "held:none" : "held:" + keys.front());
        return true;
    }

    bool HeldKeysSettled() const override { return directionTicks == 0; }

    bool Logs(const std::string& id, const std::vector<std::string>& lines) override {
        events.push_back("logs");
        for (const auto& line : lines) logs.push_back(id + ":" + line);
        if (onLogs) onLogs();
        return true;
    }

    void Advance() {
        state.character.positionKnown = state.positionKnown;
        if (state.positionKnown) state.character.SetPosition(state.x, state.y);
        ++state.sequence;
        if (advanceCharacter) ++state.characterUpdates;
        if (legacyDelivery) {
            delivered.push_back(active);
            legacyDelivery = false;
            result.dispatched = true;
        }
        // A native consumer may admit the current held input when A finishes.
        // Clearing/replacing B removes it here; there is no history to replay.
        if (armed && allowStart && !actionActive) {
            active = desired;
            armed = false;
            actionActive = startsAnimation;
            if (startsAnimation) state.actionIdle = Fact::False;
            delivered.push_back(active);
            result.dispatched = true;
            result.sessionId = active.sessionId;
            result.reason = "native_dispatched";
        }
        if (directionTicks > 0) --directionTicks;
        if (actionReleaseTicks > 0 && --actionReleaseTicks == 0)
            result.controlReleased = desired.kind == ActionKind::Stop;
    }

    void Complete() {
        actionActive = false;
        state.actionIdle = Fact::True;
        result.reason = "native_completed";
    }

    State state;
    mutable std::map<std::string, int> queries;
    std::map<std::uint32_t, Observation> terrains;
    bool supportsItems = true, supportsSkills = true, rejectClear = false, nativeNpcDomain = true;
    bool actionActive = false, legacyDelivery = false, advanceCharacter = true, armed = false, allowStart = true;
    bool startsAnimation = true;
    int actionReleaseTicks = 0, directionTicks = 0, releases = 0, beginCalls = 0, intentCalls = 0;
    Action desired, active;
    ActionResult result;
    std::vector<Action> requests, delivered;
    std::vector<std::vector<std::string>> changes;
    std::vector<std::string> directions, events, logs;
    std::function<void()> onIntent, onRelease, onLogs;
    std::function<void(const std::string&)> onDomain;
};

std::string Source(const std::string& body, TickGear gear = TickGear::Native) {
    return "-- @mode tick\n-- @tick.gear " + std::to_string(static_cast<int>(gear)) + "\n" + body;
}

void Start(TickRuntime& runtime, const std::string& id, const std::string& source, std::uint32_t limit = 0) {
    std::string error;
    Check(runtime.Start(id, source, limit, error), "start " + id + ": " + error);
    Check(Field(runtime.CurrentStatus(id), "error").Type() == Value::Kind::Null,
          "successful admission must not project an error");
}

void Step(NativeBoundary& native, TickRuntime& runtime, bool sceneChanged = false) {
    native.Advance();
    runtime.Tick(sceneChanged);
}

void StatusIs(const TickRuntime& runtime, const std::string& id, const std::string& status,
              const std::string& reason = {}) {
    const auto value = runtime.CurrentStatus(id);
    Check(Field(value, "status").Text() == status, "unexpected status for " + id + ": " + value.Dump());
    if (!reason.empty()) Check(Field(value, "reason").Text() == reason, "unexpected reason: " + value.Dump());
}

void Drain(NativeBoundary& native, TickRuntime& runtime, const std::string& id, const std::string& status,
           const std::string& reason = {}) {
    for (int i = 0; i < 8 && Field(runtime.CurrentStatus(id), "status").Text() == "running"; ++i) Step(native, runtime);
    StatusIs(runtime, id, status, reason);
    Check(Field(runtime.CurrentStatus(id), "control_released").Boolean(),
          "terminal session must confirm its own release");
}

void Declarations() {
    TickConfig config;
    std::string error;
    Check(ParseScriptMode("function main() end", error) == ScriptMode::Coroutine, "default mode is coroutine");
    Check(
        ParseTickConfig(
            "\n -- title\n-- @mode tick -- description\n-- @tick.budget_ms .5\n-- @tick.overrun skip\n-- @tick.abort_commit false\nfunction main() end",
            config, error),
        error);
    Check(config.mode == ScriptMode::Tick && config.budgetMs == .5 && config.skipOverrun && !config.abortCommit
              && config.gear == TickGear::ThirtyHz,
          "decimal budgets and explicit policies must not be truncated; default decision gear is 3");
    for (int gear = 1; gear <= 4; ++gear)
        Check(ParseTickConfig("-- @mode tick\n-- @tick.gear " + std::to_string(gear) + " -- cadence", config, error)
                  && static_cast<int>(config.gear) == gear,
              "each exact gear token must retain its selected value");
    for (const std::string& token : std::vector<std::string>{"", "0", "5", "01", "+1", "-1", "1.0", ".1", "1e0", "NaN",
                                                             "inf", "true", "1 2", "１", std::string(5000, '9')})
        Check(ParseScriptMode("-- @mode tick\n-- @tick.gear " + token, error) == ScriptMode::Invalid,
              "gear must be an exact supported ASCII token");
    const std::vector<std::string> invalid{"-- @mode unknown",
                                           "-- @mode tick\n-- @mode tick",
                                           "-- @tick.gear 1",
                                           "-- @mode coroutine\n-- @tick.gear 1",
                                           "-- @mode tick\n-- @tick.gear 1\n-- @tick.gear 1",
                                           "-- @tick.budget_ms 1",
                                           "-- @mode tick\n-- @tick.budget_ms 0",
                                           "-- @mode tick\n-- @tick.budget_ms -1",
                                           "-- @mode tick\n-- @tick.budget_ms 1e2",
                                           "-- @mode tick\n-- @tick.budget_ms +1",
                                           "-- @mode tick\n-- @tick.budget_ms NaN",
                                           "-- @mode tick\n-- @tick.budget_ms inf",
                                           "-- @mode tick\n-- @tick.overrun Skip",
                                           "-- @mode tick\n-- @tick.abort_commit 1",
                                           "-- @mode tick\n-- @tick.unknown true",
                                           "-- @mode coroutine\n-- @tick.overrun abort",
                                           "-- @mode tick\n-- @tick.budget_ms 1\n-- @tick.budget_ms 2"};
    for (const auto& text : invalid)
        Check(ParseScriptMode(text, error) == ScriptMode::Invalid && !error.empty(),
              "must reject declaration: " + text);
    Check(ParseScriptMode("--- @mode tick--说明\nfunction main() end", error) == ScriptMode::Tick,
          "documentation-style line comments must select the same engine as the CLI");
    Check(ParseScriptMode("---[[\n-- @mode tick\nfunction main() end", error) == ScriptMode::Tick,
          "three-dash comments are not Lua long comments");
    Check(ParseScriptMode("local x = 1\n-- @mode tick", error) == ScriptMode::Coroutine,
          "body comments cannot select the engine");
    Check(ParseScriptMode("--[=[\n-- @mode tick\n]=]\n-- @mode coroutine\nreturn", error) == ScriptMode::Coroutine,
          "long-comment contents are not metadata");
    Check(ParseScriptMode("local text = [[\n-- @mode tick\n]]", error) == ScriptMode::Coroutine,
          "Lua string contents are not metadata");
    Check(ParseTickConfig("-- @mode tick\n-- @tick.budget_ms 4294967296.25", config, error)
              && config.budgetMs == 4294967296.25,
          "large finite decimal budget must remain a double");
}

Value TickField(const TickRuntime& runtime, const std::string& id, const std::string& name) {
    return Field(Field(runtime.CurrentStatus(id), "tick"), name);
}

void Cadence() {
    using Clock = std::chrono::steady_clock;
    NativeBoundary native;
    auto now = Clock::time_point(std::chrono::seconds(100));
    TickRuntime runtime(native, [&] { return now; });
    const std::string body = R"lua(
function main(c)
  c.state.calls=(c.state.calls or 0)+1
  assert(c.tick.index==c.state.calls and c.tick.gear>=1 and c.tick.gear<=4)
  local elapsed=math.floor((c.tick.time-100)*1000+0.5)
  assert(c.game.character.x==elapsed and c.game.world.x==elapsed)
  assert(c.game.scene.monsters[1].x==elapsed+1 and c.game.scene.drops[1].x==elapsed+2)
  assert(c.game.inventory.status=='ok')
  if c.state.previous then assert(math.abs(c.tick.delta-(c.tick.time-c.state.previous))<1e-10)
  else assert(c.tick.delta==0) end
  c.state.previous=c.tick.time
  if c.tick.gear==4 and c.tick.index==2 then return 'done' end
end
)lua";
    Start(runtime, "default", "-- @mode tick\n" + body);
    Start(runtime, "slow", Source(body, TickGear::TenHz));
    Start(runtime, "medium", Source(body, TickGear::TwentyHz));
    Start(runtime, "native", Source(body));
    native.state.dropsKnown = true;
    native.state.drops.emplace_back();
    native.queries.clear();
    for (int elapsed = 0; elapsed <= 200; ++elapsed) {
        now = Clock::time_point(std::chrono::seconds(100)) + std::chrono::milliseconds(elapsed);
        native.state.x = elapsed;
        native.state.monsters[0].SetPosition(elapsed + 1, 3);
        native.state.drops[0].SetPosition(elapsed + 2, 4);
        Step(native, runtime);
    }
    Check(TickField(runtime, "default", "gear").Number() == 3 && TickField(runtime, "slow", "gear").Number() == 1
              && TickField(runtime, "medium", "gear").Number() == 2
              && TickField(runtime, "native", "gear").Number() == 4,
          "status must retain the same effective gear as the callback context");
    Check(TickField(runtime, "default", "index").Number() == 7 && TickField(runtime, "slow", "index").Number() == 3
              && TickField(runtime, "medium", "index").Number() == 5
              && TickField(runtime, "native", "index").Number() == 2,
          "independent gears must follow 30/10/20Hz and native cadence without cumulative phase drift");
    StatusIs(runtime, "native", "completed", "script_returned");
    for (const auto& id : {"default", "slow", "medium"}) StatusIs(runtime, id, "running");
    for (const auto& domain : {"character", "world", "scene", "inventory"})
        Check(native.queries[domain] == 10, "due sessions must share exactly one current core/lazy sample per frame");
    const auto profile = runtime.Profile();
    Check(Field(profile, "active_frames").Number() == 201 && Field(Field(profile, "observe"), "samples").Number() == 201
              && Field(Field(profile, "refresh_core"), "samples").Number() == 10
              && Field(Field(profile, "lua"), "samples").Number() == 17,
          "non-due frames advance lifecycle and observation, not main or core refresh");
    now += std::chrono::milliseconds(1);
    native.state.x = 201;
    native.Advance();
    Start(runtime, "initialization",
          "-- @mode tick\nlocal initial=game.character.x; assert(initial==201)\n"
          "function main(c) assert(initial==c.game.character.x); return 'done' end");
    Check(TickField(runtime, "initialization", "index").Number() == 0 && native.queries["character"] == 11
              && Field(Field(runtime.Profile(), "refresh_core"), "samples").Number() == 10,
          "Start must freshly sample legal initialization reads, without invoking main or counting a host refresh");
    Step(native, runtime);
    StatusIs(runtime, "initialization", "completed", "script_returned");
}

void CadencePhase() {
    using Clock = std::chrono::steady_clock;
    NativeBoundary native;
    const auto origin = Clock::time_point(std::chrono::seconds(100));
    auto now = origin;
    TickRuntime runtime(native, [&] { return now; });
    Start(runtime, "fast",
          Source(R"lua(function main(c)
  assert(c.game.inventory.status=='ok')
  if c.tick.index==4 then assert(c.game.character.x==500) end
end)lua",
                 TickGear::TwentyHz));
    Start(runtime, "slow",
          Source(R"lua(function main(c)
  assert(c.game.inventory.status=='ok')
  if c.tick.index==3 then assert(c.game.character.x==500) end
end)lua",
                 TickGear::TenHz));
    bool slowRead = false;
    native.onDomain = [&](const std::string& domain) {
        if (domain == "inventory" && slowRead) {
            slowRead = false;
            now += std::chrono::milliseconds(375); // Inside main's C binding, not Commit or Logs.
            native.state.x = 999;
        }
    };
    native.queries.clear();
    Step(native, runtime);
    now = origin + std::chrono::milliseconds(50);
    slowRead = true;
    Step(native, runtime);
    Check(TickField(runtime, "fast", "index").Number() == 2 && TickField(runtime, "slow", "index").Number() == 1,
          "an earlier main cannot make a non-due session join the fixed frame-start due set");
    Step(native, runtime); // now=425ms: only slow is due; fast skipped all intervals through its own return.
    Check(TickField(runtime, "fast", "index").Number() == 2 && TickField(runtime, "slow", "index").Number() == 2,
          "a long callback must not burst to catch up on the immediately following update");
    now = origin + std::chrono::milliseconds(449);
    Step(native, runtime);
    Check(TickField(runtime, "fast", "index").Number() == 2, "next absolute fast phase is 450ms");
    now = origin + std::chrono::milliseconds(450);
    Step(native, runtime);
    Check(TickField(runtime, "fast", "index").Number() == 3,
          "next phase is not callback-return time plus one period (475ms)");
    now = origin + std::chrono::milliseconds(500);
    native.state.x = 500;
    slowRead = true;
    Step(native, runtime); // Both due; slow sees the same 500ms core, but starts at 875ms.
    Check(std::abs(TickField(runtime, "fast", "time").Number() - 100.5) < 1e-10
              && std::abs(TickField(runtime, "slow", "time").Number() - 100.875) < 1e-10
              && std::abs(TickField(runtime, "slow", "delta").Number() - .45) < 1e-10,
          "each callback time/delta must include the real delay caused by earlier callbacks");
    Step(native, runtime);
    now = origin + std::chrono::milliseconds(899);
    Step(native, runtime);
    Check(TickField(runtime, "fast", "index").Number() == 4 && TickField(runtime, "slow", "index").Number() == 3
              && native.queries["character"] == 5 && native.queries["inventory"] == 5,
          "no catch-up callbacks or stale-core reads may occur before the next future phase");
    now = origin + std::chrono::milliseconds(900);
    Step(native, runtime);
    Check(TickField(runtime, "fast", "index").Number() == 5 && TickField(runtime, "slow", "index").Number() == 4
              && std::abs(TickField(runtime, "fast", "delta").Number() - .4) < 1e-10
              && std::abs(TickField(runtime, "slow", "delta").Number() - .025) < 1e-10,
          "missed periods are skipped without incrementing index or substituting nominal delta");
    Check(TickField(runtime, "fast", "overruns").Number() == 0 && TickField(runtime, "slow", "overruns").Number() == 0,
          "advancing scheduling time inside main must not advance the real execution-budget clock");
    NativeBoundary budgetNative;
    TickRuntime budgeted(budgetNative, [&] { return now; }); // Scheduling time stays frozen for both infinite loops.
    std::string error;
    Check(!budgeted.Start("frozen-init", Source("-- @tick.budget_ms 1\nwhile true do end"), 0, error),
          "a frozen scheduling clock cannot disable initialization's real-time budget");
    StatusIs(budgeted, "frozen-init", "rejected", "tick_overrun");
    Start(budgeted, "frozen-main", Source("-- @tick.budget_ms 1\nfunction main(c) while true do end end"));
    Step(budgetNative, budgeted);
    StatusIs(budgeted, "frozen-main", "cancelled", "tick_overrun");
    Check(TickField(budgeted, "frozen-main", "overruns").Number() == 1
              && Field(budgeted.CurrentStatus("frozen-main"), "last_resume_us").Number() >= 1000
              && Field(Field(budgeted.Profile(), "lua"), "max_us").Number() >= 1000,
          "budget hooks, post-call duration and profiling must all use actual wall time, not the scheduling seam");
}

void CadenceLifecycle() {
    using Clock = std::chrono::steady_clock;
    const auto origin = Clock::time_point(std::chrono::seconds(100));
    {
        NativeBoundary native;
        auto now = origin;
        TickRuntime runtime(native, [&] { return now; });
        Start(
            runtime, "owner",
            Source(
                "function main(c) if c.tick.index==1 then c.game.player.move('right'); c.game.player.attack() end end",
                TickGear::TenHz));
        Step(native, runtime);
        now += std::chrono::milliseconds(1);
        Start(runtime, "successor",
              Source("function main(c) if c.tick.index==1 then assert(c.game.player.skill(1001004)) end end",
                     TickGear::TwentyHz));
        Step(native, runtime);
        Check(native.delivered.size() == 1 && native.delivered[0].skillId == 0 && native.desired.skillId == 1001004,
              "non-due A remains active while a new session replaces its input with B");
        native.Complete();
        now += std::chrono::milliseconds(1);
        Step(native, runtime);
        Check(native.delivered.size() == 2 && native.ActiveAction()->skillId == 1001004
                  && native.directions == std::vector<std::string>{"right"} && native.beginCalls == 0,
              "native consumption advances held B without another Lua callback or Runtime Begin");
        runtime.Cancel("successor", "explicit_cancel");
        Step(native, runtime);
        Step(native, runtime);
        StatusIs(runtime, "successor", "cancelled", "explicit_cancel");
        Check(native.actionActive && native.ActionIntentSettled() && native.desired.kind == ActionKind::Stop,
              "a non-due cancelled session waits for input release, not its already-started animation");
        native.rejectClear = true;
        runtime.Cancel("owner", "explicit_cancel");
        Step(native, runtime);
        StatusIs(runtime, "owner", "running", "explicit_cancel");
        Check(!Field(runtime.CurrentStatus("owner"), "control_released").Boolean(),
              "a rejected key-up cannot confirm cancellation between callbacks");
        native.rejectClear = false;
        Step(native, runtime);
        StatusIs(runtime, "owner", "running");
        Step(native, runtime);
        StatusIs(runtime, "owner", "cancelled", "explicit_cancel");
        Check(Field(runtime.CurrentStatus("owner"), "control_released").Boolean()
                  && TickField(runtime, "owner", "index").Number() == 1
                  && TickField(runtime, "successor", "index").Number() == 1
                  && Field(Field(runtime.Profile(), "refresh_core"), "samples").Number() == 2,
              "release and final status progress without another main or core read");
    }
    {
        NativeBoundary native;
        auto now = origin;
        TickRuntime runtime(native, [&] { return now; });
        Start(runtime, "deadline", Source("function main(c) c.game.player.attack() end", TickGear::TenHz), 20);
        Step(native, runtime);
        now += std::chrono::milliseconds(20);
        Step(native, runtime);
        StatusIs(runtime, "deadline", "running", "time_limit");
        Check(native.desired.kind == ActionKind::Stop && native.actionActive,
              "a non-due deadline clears held input without interrupting the native animation");
        Step(native, runtime);
        Step(native, runtime);
        StatusIs(runtime, "deadline", "cancelled", "time_limit");
        Check(Field(runtime.CurrentStatus("deadline"), "control_released").Boolean()
                  && TickField(runtime, "deadline", "index").Number() == 1
                  && Field(Field(runtime.Profile(), "refresh_core"), "samples").Number() == 1,
              "deadline cancellation terminates on native release, without waiting for main or animation");
    }
    {
        NativeBoundary native;
        auto now = origin;
        TickRuntime runtime(native, [&] { return now; });
        Start(runtime, "scene",
              Source(R"lua(function main(c)
  if c.tick.index==1 then c.game.player.move('right'); c.game.player.attack()
  else assert(c.game.world.scene_generation==2 and c.game.scene.map_id==50000)
       assert(c.game.player.status().input_action==nil) end
end)lua",
                     TickGear::TenHz));
        Step(native, runtime);
        now += std::chrono::milliseconds(1);
        ++native.state.sceneGeneration;
        Step(native, runtime);
        native.Complete();
        Step(native, runtime);
        Check(native.directions.empty() && native.desired.kind == ActionKind::Stop
                  && TickField(runtime, "scene", "index").Number() == 1
                  && Field(Field(runtime.Profile(), "refresh_core"), "samples").Number() == 1,
              "non-due same-map scene changes clear direction and action without refreshing Lua");
        now = origin + std::chrono::milliseconds(100);
        Step(native, runtime);
        Check(native.directions.empty() && native.requests.size() == 1 && native.delivered.size() == 1
                  && TickField(runtime, "scene", "index").Number() == 2,
              "the next due callback sees the new scene without replaying old input");
        StatusIs(runtime, "scene", "running");
    }
}

void Entry() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(runtime, "wrapped", Source(R"lua(
local function main(c)
  assert(c.game == game and game.sleep == nil and game.tasks == nil and game.state == nil)
  assert(c.options.distance == 5 and c.route[1] == 50001 and c.scene.map_id == 50000)
  c.state.count = (c.state.count or 0) + 1
  assert(c.state.count == c.tick.index)
  assert(c.tick.time > 0 and c.tick.delta >= 0 and c.tick.scene_generation == 1)
  if c.tick.index == 3 then return {done=true} end
end
return {main=main, context={options={distance=5}, route={50001}, scene={
  instance_id='tick-contract',character_id=1,map_id=50000,scene_generation=1}}}
)lua"));
    Step(native, runtime);
    Step(native, runtime);
    Step(native, runtime);
    StatusIs(runtime, "wrapped", "completed", "script_returned");
    Check(Field(runtime.CurrentStatus("wrapped"), "resumes").Number() == 3, "main must run exactly once per frame");
    Start(runtime, "raw", Source("function main(c) assert(c.options==nil); return 'done' end"));
    Step(native, runtime);
    StatusIs(runtime, "raw", "completed");
    std::string error;
    for (const auto& anchor :
         {"instance_id='other'", "character_id=2", "map_id=2", "scene_generation=2", "character_id='1'"}) {
        const std::string id = "bad-" + std::to_string(runtime.Statuses().Elements().size());
        Check(!runtime.Start(id, Source("return {main=function() end,context={scene={" + std::string(anchor) + "}}}"),
                             0, error)
                  && error.find("strategy_context_changed") != std::string::npos,
              "must validate initial CLI scene identity: " + error);
    }
    Check(!runtime.Start("missing", Source("return {}"), 0, error), "missing entry must fail at admission");
    Check(runtime.CurrentStatus("absent").Type() == Value::Kind::Null, "unknown session is null");
}

void SceneContinuity() {
    NativeBoundary native;
    native.terrains[50000] = Terrain(50000, 10);
    native.terrains[50001] = Terrain(50001, 20);
    native.terrains[50002] = Terrain(50002, 30);
    TickRuntime runtime(native);
    Start(runtime, "route", Source(R"lua(
local maps, generations, xs = {50000,50001,50002,50002,50002}, {1,2,3,4,4}, {10,20,30,40,40}
local function main(c)
  local s, i = c.scene, c.tick.index
  assert(s.instance_id==c.game.world.instance_id and s.character_id==c.game.character.id)
  assert(s.map_id==maps[i] and s.map_id==c.game.world.map_id)
  assert(s.scene_generation==generations[i] and s.scene_generation==c.tick.scene_generation)
  assert(s.scene_generation==c.game.world.scene_generation)
  assert(s.terrain.status=='available' and s.terrain.source=='local-IMG-contract')
  assert(s.terrain.footholds[1].x1==xs[i] and s.terrain.ropes[1].x==xs[i]+50)
  assert(c.options.goal==50002 and c.route[2]==50001 and c.custom.label=='keep')
  c.state.calls=(c.state.calls or 0)+1
  assert(c.state.calls==i)
  if i==1 then c.state.self=c.state; c.state.route_index=2
  else
    assert(c.state.self==c.state and c.state.route_index==2)
    assert(c.state.previous.map_id==maps[i-1] and c.state.previous.scene_generation==generations[i-1])
    assert(c.state.previous.terrain.footholds[1].x1==xs[i-1])
    if i==5 then assert(c.state.previous==s) else assert(c.state.previous~=s) end
  end
  c.state.previous=s
  if i==5 then return 'done' end
end
return {main=main,context={options={goal=50002},route={50000,50001,50002},custom={label='keep'},scene={
  instance_id='tick-contract',character_id=1,map_id=50000,scene_generation=1,
  terrain={status='available',source='stale-caller',footholds={{x1=-999}},ropes={}}}}}
)lua"));
    Check(native.queries["terrain"] == 0, "admission must not parse static resources before a stable consumer");
    Step(native, runtime);
    for (std::uint32_t map : {50001, 50002}) {
        native.state.mapId = map;
        ++native.state.sceneGeneration;
        Step(native, runtime);
        Step(native, runtime);
        StatusIs(runtime, "route", "running");
    }
    native.terrains[50002] = Terrain(50002, 40);
    ++native.state.sceneGeneration; // Same map re-entered, new local scene lifetime.
    Step(native, runtime);
    Step(native, runtime);
    Step(native, runtime);
    StatusIs(runtime, "route", "completed", "script_returned");
    Check(native.queries["terrain"] == 4 && TickField(runtime, "route", "index").Number() == 5,
          "two map changes and same-map reentry must refresh terrain without restarting route state");
}

void SceneCadence() {
    using Clock = std::chrono::steady_clock;
    const auto origin = Clock::time_point(std::chrono::seconds(100));
    auto now = origin;
    NativeBoundary native;
    native.terrains[50000] = Terrain(50000, 10);
    native.terrains[50001] = Terrain(50001, 20);
    TickRuntime runtime(native, [&] { return now; });
    const std::string body = R"lua(function main(c)
  assert(c.game.terrain==nil and c.game.scene.terrain==nil)
  assert(c.scene.map_id==c.game.world.map_id and c.scene.scene_generation==c.tick.scene_generation)
  assert(c.scene.terrain.status=='available')
  assert(c.scene.terrain.footholds[1].x1==(c.scene.map_id==50000 and 10 or 20))
  c.state.calls=(c.state.calls or 0)+1
  assert(c.state.calls==c.tick.index)
end)lua";
    Start(runtime, "slow",
          Source(body + R"lua(
local original=main
function main(c)
  original(c)
  if c.tick.index==1 then c.game.player.move('right'); c.game.player.attack() end
end)lua",
                 TickGear::TenHz));
    Start(runtime, "fast", Source(body, TickGear::TwentyHz));
    Step(native, runtime);
    Check(native.queries["terrain"] == 1 && native.requests.size() == 1,
          "all initial consumers must share one local static read");
    now += std::chrono::milliseconds(1);
    native.state.mapId = 50001;
    ++native.state.sceneGeneration;
    Step(native, runtime);
    Check(native.directions.empty() && native.releases == 1 && native.queries["terrain"] == 1,
          "a non-due transition must release old input without reading new terrain");
    native.state.ready = native.state.mapKnown = native.state.characterKnown = false;
    Step(native, runtime);
    native.state.ready = native.state.mapKnown = native.state.characterKnown = true;
    Step(native, runtime);
    Check(native.queries["terrain"] == 1 && TickField(runtime, "slow", "index").Number() == 1
              && TickField(runtime, "fast", "index").Number() == 1,
          "unready and non-due stable frames cannot invoke Lua or parse terrain");
    now = origin + std::chrono::milliseconds(50);
    Step(native, runtime);
    Check(native.queries["terrain"] == 2 && TickField(runtime, "fast", "index").Number() == 2
              && TickField(runtime, "slow", "index").Number() == 1,
          "the first stable due consumer must obtain the new local map");
    now = origin + std::chrono::milliseconds(100);
    Step(native, runtime);
    Start(runtime, "newcomer", Source(body));
    Step(native, runtime);
    Check(native.queries["terrain"] == 2 && native.requests.size() == 1 && native.delivered.size() == 1
              && native.directions.empty(),
          "later and newly admitted consumers share the current scene without replaying old input");
    Step(native, runtime, true); // An explicit host transition also invalidates an otherwise equal identity.
    Check(native.queries["terrain"] == 2 && TickField(runtime, "newcomer", "index").Number() == 1,
          "an explicit transition cannot read terrain or invoke its native-gear main");
    Step(native, runtime);
    Check(native.queries["terrain"] == 3 && native.requests.size() == 1
              && TickField(runtime, "newcomer", "index").Number() == 2,
          "the next stable consumer must replace a transition-invalidated scene without replay");
    runtime.CancelAll("explicit_cancel");
    Step(native, runtime);
}

void SceneHeldIntents() {
    using Clock = std::chrono::steady_clock;
    const auto origin = Clock::time_point(std::chrono::seconds(100));
    auto now = origin;
    NativeBoundary native;
    native.terrains[50000] = Terrain(50000, 10);
    native.terrains[50001] = Terrain(50001, 20);
    TickRuntime runtime(native, [&] { return now; });
    Start(runtime, "scene-input",
          Source(R"lua(function main(c)
  local p, s = c.game.player, c.scene
  local status = p.status()
  assert(s.map_id==c.game.world.map_id and s.scene_generation==c.tick.scene_generation)
  assert(s.terrain.status=='available')
  c.state.calls=(c.state.calls or 0)+1
  if c.tick.index==1 then
    assert(s.map_id==50000 and s.terrain.footholds[1].x1==10)
    c.state.first=s
    p.move('up'); p.skill(1001004)
  else
    assert(c.state.calls==c.tick.index and s.map_id==50001 and s.terrain.footholds[1].x1==20)
    assert(c.state.first.map_id==50000 and c.state.first.scene_generation==1)
    assert(c.state.first.terrain.footholds[1].x1==10)
    if c.tick.index==2 then
      assert(status.input_action==nil and status.moving==nil)
      assert(status.busy==true and status.skill_id==1001004)
      p.move('left'); p.skill(1001005)
    elseif c.tick.index==3 then
      assert(status.input_skill_id==1001005 and status.skill_id==1001004)
      p.skill(nil); p.move(nil)
    else
      assert(status.input_action==nil and status.action==nil and status.busy==false)
      return 'done'
    end
  end
end)lua",
                 TickGear::TenHz));
    Step(native, runtime);
    now = origin + std::chrono::milliseconds(8);
    Step(native, runtime);
    Check(native.delivered.size() == 1 && native.active.skillId == 1001004,
          "the external native consumer must establish A before the scene changes");
    native.state.mapId = 50001;
    ++native.state.sceneGeneration;
    now = origin + std::chrono::milliseconds(16);
    Step(native, runtime);
    Check(native.desired.kind == ActionKind::Stop && native.directions.empty() && native.actionActive
              && native.active.skillId == 1001004 && native.queries["terrain"] == 1,
          "a non-due scene transition must withdraw input, not rewrite A or read terrain");
    now = origin + std::chrono::milliseconds(100);
    Step(native, runtime);
    Check(native.queries["terrain"] == 2 && native.desired.skillId == 1001005
              && native.directions == std::vector<std::string>{"left"} && native.active.skillId == 1001004,
          "new-map planning may hold B while native A remains independently busy");
    now = origin + std::chrono::milliseconds(108);
    Step(native, runtime);
    now = origin + std::chrono::milliseconds(200);
    Step(native, runtime);
    Check(native.desired.kind == ActionKind::Stop && native.directions.empty() && native.actionActive,
          "withdrawing new-map B must not interrupt native A");
    now = origin + std::chrono::milliseconds(208);
    Step(native, runtime);
    native.Complete(); // Only the native boundary decides that A has ended.
    now = origin + std::chrono::milliseconds(216);
    Step(native, runtime);
    now = origin + std::chrono::milliseconds(300);
    Step(native, runtime);
    Drain(native, runtime, "scene-input", "completed", "script_returned");
    Check(native.requests.size() == 2 && native.delivered.size() == 1 && native.beginCalls == 0
              && TickField(runtime, "scene-input", "index").Number() == 4,
          "scene refresh must preserve route state without replaying withdrawn B after A ends");
}

void SceneUnavailable() {
    NativeBoundary native;
    native.terrains[50000] = Terrain(50000, 10);
    native.terrains[50001] = {"unavailable",
                              Value::Object({{"message", "IMG missing"},
                                             {"details", Value::Object({{"map_id", 50001}})},
                                             {"footholds", Value::Array({Value::Object({{"x1", -999}})})},
                                             {"ropes", Value::Array()}}),
                              "local_terrain_missing"};
    native.terrains[50002] = {"unsupported", {}, "local_reference_map"}; // No data map identity is required.
    native.terrains[50003] = {"error", Value::Object({{"message", "IMG unreadable"}}), "local_read_failed"};
    native.terrains[50004] = Terrain(99999, 90); // A resource result cannot relabel another map's geometry.
    native.terrains[50005] = {"ok", Value::Object({{"footholds", Value::Array()}, {"ropes", Value::Array()}}), {}};
    TickRuntime runtime(native);
    Start(runtime, "missing", Source(R"lua(function main(c)
  local s=c.scene
  assert(s.map_id==c.game.world.map_id and s.scene_generation==c.game.world.scene_generation)
  if s.map_id==50000 then assert(s.terrain.status=='available')
  else
    assert(s.terrain.footholds==nil and s.terrain.ropes==nil)
    assert(type(s.terrain.error)=='string' and #s.terrain.error>0)
    if s.map_id==50001 then
      assert(s.terrain.status=='unavailable' and s.terrain.error=='local_terrain_missing')
      assert(s.terrain.message=='IMG missing' and s.terrain.details.map_id==50001)
    elseif s.map_id==50002 then assert(s.terrain.status=='unsupported' and s.terrain.error=='local_reference_map')
    elseif s.map_id==50003 then assert(s.terrain.status=='error' and s.terrain.message=='IMG unreadable')
    else assert(s.terrain.status=='unavailable') end
  end
  c.state.calls=(c.state.calls or 0)+1
  assert(c.state.calls==c.tick.index)
end)lua"));
    Step(native, runtime);
    for (std::uint32_t map = 50001; map <= 50005; ++map) {
        native.state.mapId = map;
        ++native.state.sceneGeneration;
        Step(native, runtime);
        Step(native, runtime);
        Step(native, runtime); // Explicit failure remains visible; no per-tick retries.
        StatusIs(runtime, "missing", "running");
    }
    Check(native.queries["terrain"] == 6 && TickField(runtime, "missing", "index").Number() == 11,
          "unavailable/reference/error/mismatched results must stay explicit without caller fallback or retries");
    runtime.CancelAll("explicit_cancel");

    NativeBoundary unknown;
    unknown.state.mapKnown = false;
    unknown.terrains[50000] = Terrain(50000, 10);
    TickRuntime waiting(unknown);
    Start(waiting, "unknown-map", Source(R"lua(function main(c)
  if c.tick.index==1 then
    assert(c.scene.map_id==nil and c.game.world.map_id==nil)
    assert(c.scene.terrain.status=='unavailable' and c.scene.terrain.footholds==nil)
    c.state.waited=true
  else
    assert(c.state.waited and c.scene.map_id==50000 and c.scene.terrain.status=='available')
    return 'done'
  end
end)lua"));
    Step(unknown, waiting);
    Check(unknown.queries["terrain"] == 0, "an unknown current map cannot authorize reading a stale numeric map ID");
    unknown.state.mapKnown = true;
    Step(unknown, waiting);
    StatusIs(waiting, "unknown-map", "completed");
    Check(unknown.queries["terrain"] == 1, "a known current identity must replace the explicit unavailable scene");

    for (const auto& change : {"instance", "character"}) {
        NativeBoundary io;
        io.terrains[50000] = Terrain(50000, 10);
        io.terrains[50001] = Terrain(50001, 20);
        TickRuntime engine(io);
        Start(engine, change, Source("function main(c) assert(c.scene.terrain.status=='available') end"));
        Step(io, engine);
        if (std::string(change) == "instance")
            io.state.instanceId = "other";
        else
            io.state.character.id = 2;
        io.state.mapId = 50001;
        ++io.state.sceneGeneration;
        Step(io, engine);
        Step(io, engine);
        StatusIs(engine, change, "cancelled", std::string(change) + "_changed");
        Check(io.queries["terrain"] == 1 && TickField(engine, change, "index").Number() == 1,
              "scene refresh cannot turn an instance/character change into a continuing session");
    }
}

void SceneScript(const std::string& path) {
    std::ifstream input(path);
    Check(static_cast<bool>(input), "scene script input required");
    const std::string source{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
    NativeBoundary native;
    native.terrains[50000] = Terrain(50000, 10);
    native.terrains[50001] = Terrain(50001, 20);
    TickRuntime runtime(native);
    Start(runtime, "script-scene", source);
    Step(native, runtime);
    Check(native.directions == std::vector<std::string>{"up"}, "script must begin its route in the first scene");
    native.state.mapId = 50001;
    ++native.state.sceneGeneration;
    Step(native, runtime);
    Check(native.directions.empty() && TickField(runtime, "script-scene", "index").Number() == 1,
          "scene transition cannot invoke main or retain the old portal input");
    Step(native, runtime);
    Drain(native, runtime, "script-scene", "completed", "script_returned");
    Check(native.queries["terrain"] == 2 && TickField(runtime, "script-scene", "index").Number() == 2,
          "compiled and direct entries must cross scenes in one unchanged native session");
}

void Domains() {
    NativeBoundary native;
    native.terrains[50000] = Terrain(50000, 10);
    TickRuntime runtime(native);
    Step(native, runtime);
    Check(native.queries.empty(), "an unused tick engine cannot collect domains or burden the coroutine path");
    Start(runtime, "domains", Source(R"lua(
function main(c)
  local g=c.game
  assert(type(print)=="function" and type(pcall)=="function" and type(xpcall)=="function")
  assert(type(load)=="function" and type(loadfile)=="function" and type(dofile)=="function")
  assert(type(require)=="function" and type(package)=="table" and type(io)=="table" and type(os)=="table")
  assert(type(debug)=="table" and type(coroutine)=="table" and type(rawset)=="function")
  assert(type(setmetatable)=="function" and type(getmetatable)=="function")
  assert(g.character == g.character and g.inventory == g.inventory)
  assert(g.character.id==1 and g.character.hp==100 and g.character.buffs==nil)
  assert(g.character.buffs_available==false)
  assert(g.world.map_id==50000 and g.world.dead==nil and g.world.position.x==g.world.x)
  assert(g.scene.monsters[1].object_id==7 and #g.scene.monsters==1 and g.scene.npcs[1].id==99)
  assert(g.scene.players==nil and g.scene.drops==nil)
  assert(g.inventory.items[1].quantity==2 and g.quests.status=='unavailable')
  assert(g.quests.error=='quest_sample_missing' and g.chat.status=='unsupported')
  local n=0; for key,value in pairs(g.scene.monsters[1]) do n=n+1 end; assert(n>0)
  if c.tick.index==1 then c.state.old=g.world; assert(g.world.x==1)
  else assert(c.state.old.x==1 and g.world.x==2); return 'done' end
end
)lua"));
    native.queries.clear();
    native.state.x = 1;
    Step(native, runtime);
    for (const auto& name : {"character", "world", "scene", "inventory", "quests", "chat"})
        Check(native.queries[name] == 1, std::string("one sample per frame/access: ") + name);
    Check(native.queries["shop"] == 0, "unused low-frequency domains must not be collected");
    native.state.x = 2;
    Step(native, runtime);
    StatusIs(runtime, "domains", "completed");
    const auto finishedQueries = native.queries;
    Step(native, runtime);
    Check(native.queries == finishedQueries, "terminal sessions cannot retain per-frame observation work");
    Check(native.queries["inventory"] == 2 && native.queries["character"] == 2, "fresh frame invalidates domain cache");
    const std::vector<std::string> writes{"game.character.hp=0",
                                          "game.scene.monsters[1].x=0",
                                          "game.scene.monsters[1]={}",
                                          "table.insert(game.scene.monsters,{})",
                                          "game.player.move=false",
                                          "c.game={}",
                                          "c.scene={}",
                                          "c.scene.map_id=0",
                                          "c.scene.terrain.status='available'",
                                          "c.scene.terrain.footholds[1].x1=0",
                                          "table.insert(c.scene.terrain.ropes,{})",
                                          "local f,t=pairs(c.scene); t.map_id=0",
                                          "c.tick.index=0",
                                          "local f,t=pairs(game.character); t.hp=0"};
    for (std::size_t index = 0; index < writes.size(); ++index) {
        const std::string id = "readonly-" + std::to_string(index);
        Start(runtime, id, Source("function main(c) " + writes[index] + " end"));
        Step(native, runtime);
        StatusIs(runtime, id, "cancelled", "script_error");
    }
}

void Draft() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(runtime, "draft", Source(R"lua(
function main(c)
  local p=c.game.player
  local public=p.status()
  assert(public.input_settled==nil and public.control_released==nil and p.clear_action==nil)
  for key in pairs(public) do assert(key~='input_settled' and key~='control_released') end
  if c.tick.index==1 then
    p.move('left'); p.move('right'); p.move('left'); p.move('right')
    assert(p.jump()); assert(p.status().input_action=='jump')
    assert(p.skill(1001004))
    local s=p.status(); assert(s.input_action=='skill' and s.input_skill_id==1001004 and s.skill_id==nil)
    assert(p.use_item(2000000))
    s=p.status(); assert(s.input_action=='use_item' and s.input_item_id==2000000 and s.input_skill_id==nil)
    assert(p.pickup()); assert(p.attack())
    s=p.status(); assert(s.input_action=='attack' and s.action==nil and s.busy==false)
    assert(s.pending_action==nil and s.input_item_id==nil)
    c.game.log('draft complete')
  elseif c.tick.index==2 then p.move('right'); assert(p.attack())
  elseif c.tick.index==3 then
    assert(p.skill(nil))
    local s=p.status(); assert(s.input_action==nil and s.action=='attack' and s.moving=='right')
  elseif c.tick.index==4 then p.move(nil)
  elseif c.tick.index==5 then
    p.move('left'); p.pickup(); assert(p.stop()); assert(p.status().input_action==nil)
  elseif c.tick.index==6 then return 'done' end
end
)lua"));
    Step(native, runtime);
    Check(native.requests.size() == 1 && native.requests[0].kind == ActionKind::Attack && native.beginCalls == 0,
          "only the final action draft reaches the native intent boundary, never Begin");
    Check(native.changes.size() == 1 && native.directions == std::vector<std::string>{"right"},
          "only the final directional draft is submitted");
    Check(native.events.front() == "logs", "native effects follow completion of the Lua entry");
    Step(native, runtime);
    Check(native.intentCalls == 1 && native.changes.size() == 1, "same-value drafts must not resend native input");
    Step(native, runtime);
    Check(native.desired.kind == ActionKind::Stop && native.directions == std::vector<std::string>{"right"}
              && native.actionActive,
          "skill(nil) removes the held action, preserving direction and already-started animation");
    Step(native, runtime);
    Check(native.directions.empty(), "move(nil) clears persistent direction");
    Step(native, runtime);
    Check(native.requests.size() == 1 && native.releases == 1 && native.directions.empty(),
          "stop discards earlier action and movement drafts without extra native edges");
    Drain(native, runtime, "draft", "completed");
    Check(native.actionActive, "script completion must not interrupt native animation");
}

void HeldIntents() {
    struct InputCase {
        const char* command;
        const char* name;
        ActionKind kind;
        std::uint32_t skillId;
        std::uint32_t itemId;
    };

    for (const auto& input : {InputCase{"jump()", "jump", ActionKind::Jump, 0, 0},
                              InputCase{"attack()", "attack", ActionKind::Attack, 0, 0},
                              InputCase{"pickup()", "pickup", ActionKind::Pickup, 0, 0},
                              InputCase{"skill(1001004)", "skill", ActionKind::Attack, 1001004, 0},
                              InputCase{"skill(1)", "skill", ActionKind::Attack, 1, 0},
                              InputCase{"skill(2147483647)", "skill", ActionKind::Attack, 2147483647, 0},
                              InputCase{"use_item(2000000)", "use_item", ActionKind::UseItem, 0, 2000000}}) {
        NativeBoundary native;
        TickRuntime runtime(native);
        Start(runtime, "hold",
              Source("function main(c) local p=c.game.player; if c.tick.index==1 then "
                     "p.move('right'); assert(p."
                     + std::string(input.command) + ") elseif c.tick.index==3 then assert(p." + input.command
                     + ") elseif c.tick.index==8 then assert(p.skill(nil)) "
                       "elseif c.tick.index==9 then assert(p.skill(nil)); return 'done' end end"));
        Step(native, runtime);
        Check(native.requests.size() == 1 && native.desired.kind == input.kind
                  && native.desired.skillId == input.skillId && native.desired.itemId == input.itemId,
              std::string("one setting must establish held ") + input.name);
        const auto submitted = Field(runtime.CurrentStatus("hold"), "player");
        Check(Field(submitted, "input_action").Text() == input.name && Field(submitted, "phase").Text() == "idle"
                  && !Field(submitted, "busy").Boolean(),
              "held input is independent of an idle native action phase");
        for (const auto& projection : {submitted, Field(runtime.Statuses().Elements().front(), "player")})
            for (const auto& member : projection.Members())
                Check(member.first != "input_settled" && member.first != "control_released",
                      "both bridge player projections must omit internal input/release handshakes");
        Step(native, runtime);
        Step(native, runtime);
        const auto status = Field(runtime.CurrentStatus("hold"), "player");
        Check(Field(status, "input_action").Text() == input.name && Field(status, "action").Text() == input.name
                  && native.actionActive,
              "held input and the independently started native action must both be observable");
        if (input.skillId != 0)
            Check(Field(status, "skill_id").Number() == input.skillId
                      && Field(status, "input_skill_id").Number() == input.skillId,
                  "actual and held skill metadata must be independently projected");
        if (input.itemId != 0)
            Check(Field(status, "item_id").Number() == input.itemId
                      && Field(status, "input_item_id").Number() == input.itemId,
                  "actual and held item metadata must be independently projected");
        native.Complete();
        for (int i = 0; i < 4; ++i) Step(native, runtime);
        Check(native.intentCalls == 1 && native.requests.size() == 1 && native.delivered.size() == 1
                  && native.beginCalls == 0 && native.desired.kind == input.kind,
              "holding or repeating the same Lua command must not replay native updates after animation completion");
        Check(native.directions == std::vector<std::string>{"right"} && native.changes.size() == 1,
              "pickup and item input, like attack and jump, must not pause persistent direction");
        const auto idle = Field(runtime.CurrentStatus("hold"), "player");
        Check(Field(idle, "input_action").Text() == input.name && Field(idle, "action").Type() == Value::Kind::Null
                  && !Field(idle, "busy").Boolean() && Field(idle, "phase").Text() == "idle",
              "held input cannot manufacture a busy native phase after actual animation completion");
        Step(native, runtime);
        Check(native.desired.kind == ActionKind::Stop && native.intentCalls == 2 && !native.ActionIntentSettled()
                  && native.directions == std::vector<std::string>{"right"},
              "skill(nil) must withdraw every action kind while preserving direction, before release is confirmed");
        Step(native, runtime);
        StatusIs(runtime, "hold", "running");
        Check(native.intentCalls == 2 && !Field(runtime.CurrentStatus("hold"), "control_released").Boolean(),
              "same nil must not repeat native release, and done must wait on its original native fence");
        Drain(native, runtime, "hold", "completed", "script_returned");
        Check(native.directions.empty() && native.delivered.size() == 1,
              "completion must release direction without replaying withdrawn input");
    }
    NativeBoundary noAnimation;
    noAnimation.startsAnimation = false;
    TickRuntime runtime(noAnimation);
    Start(runtime, "no-animation", Source(R"lua(function main(c)
  local p=c.game.player
  if c.tick.index==1 then assert(p.skill(1001004))
  elseif c.tick.index>=3 then
    local s=p.status()
    assert(s.input_action=='skill' and s.input_skill_id==1001004 and s.action==nil)
    assert(s.dispatched and s.busy==false and s.phase=='idle')
  end
end)lua"));
    for (int i = 0; i < 8; ++i) Step(noAnimation, runtime);
    Check(noAnimation.intentCalls == 1 && noAnimation.delivered.size() == 1 && noAnimation.beginCalls == 0,
          "a skill consumed without starting animation must not be reissued by Runtime while held");
    runtime.Cancel("no-animation", "explicit_cancel");
    Drain(noAnimation, runtime, "no-animation", "cancelled");
}

void Actions() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(runtime, "actions", Source(R"lua(
function main(c)
  local p=c.game.player; local i=c.tick.index
  if i==1 then p.move('right'); assert(p.skill(1001004))
  elseif i==2 then
    assert(p.use_item(2000000))
    local s=p.status()
    assert(s.input_action=='use_item' and s.input_item_id==2000000 and s.input_skill_id==nil)
    assert(s.action=='skill' and s.skill_id==1001004 and s.item_id==nil and s.busy==true)
    assert(s.pending_action==nil)
  elseif i==3 then
    assert(c.game.character.action_idle==nil)
    assert(p.use_item(2000000)); assert(p.skill(nil))
    local s=p.status(); assert(s.input_action==nil and s.input_item_id==nil and s.action=='skill' and s.busy==true)
    assert(s.moving=='right')
  elseif i==4 then assert(p.jump()); assert(p.pickup())
  elseif i==5 then
    local s=p.status(); assert(s.action=='pickup' and s.input_action=='pickup' and s.skill_id==nil)
    assert(s.moving=='right')
  elseif i==6 then
    assert(p.stop()); local s=p.status(); assert(s.input_action==nil and s.action=='pickup')
  elseif i==7 then return 'done' end
end
)lua"));
    Step(native, runtime);
    Step(native, runtime);
    StatusIs(runtime, "actions", "running");
    Check(native.requests.size() == 2 && native.delivered.size() == 1 && native.ActiveAction()->skillId == 1001004
              && native.desired.itemId == 2000000,
          "busy A must accept B as held input while keeping A's actual metadata");
    native.state.actionIdle = Fact::Unknown;
    Step(native, runtime);
    Check(native.actionActive && native.desired.kind == ActionKind::Stop,
          "clearing B must not interrupt A or leave deferred B armed");
    Step(native, runtime);
    Check(native.requests.size() == 3 && native.desired.kind == ActionKind::Pickup
              && native.ActiveAction()->skillId == 1001004,
          "the last draft C replaces B without replacing the native A animation");
    native.Complete();
    Step(native, runtime);
    Check(native.delivered.size() == 2 && native.delivered.back().kind == ActionKind::Pickup
              && native.directions == std::vector<std::string>{"right"} && native.changes.size() == 1,
          "after A finishes only current C may start; withdrawn B must never be replayed");
    Drain(native, runtime, "actions", "completed", "script_returned");
    Check(native.actionActive && native.desired.kind == ActionKind::Stop && native.directions.empty()
              && native.beginCalls == 0,
          "stop clears direction and held action without interrupting C or waiting for animation");

    NativeBoundary replaced;
    TickRuntime replacing(replaced);
    Start(replacing, "replace", Source(R"lua(function main(c)
  local p=c.game.player
  if c.tick.index==1 then assert(p.attack())
  elseif c.tick.index==2 then assert(p.use_item(2000000))
  elseif c.tick.index==3 then assert(p.skill(1001004)) end
end)lua"));
    Step(replaced, replacing);
    Step(replaced, replacing);
    Step(replaced, replacing);
    Check(replaced.ActiveAction()->skillId == 0 && replaced.desired.skillId == 1001004,
          "direct B-to-C replacement must leave actual A unchanged");
    replaced.Complete();
    Step(replaced, replacing);
    Check(replaced.delivered.size() == 2 && replaced.delivered.back().skillId == 1001004,
          "directly replaced B must never be dispatched when A finishes");
    replacing.Cancel("replace", "explicit_cancel");
    Drain(replaced, replacing, "replace", "cancelled");

    NativeBoundary unsupported;
    unsupported.supportsSkills = unsupported.supportsItems = false;
    TickRuntime other(unsupported);
    Start(other, "unsupported", Source(R"lua(function main(c)
  local p=c.game.player
  assert(p.attack())
  local ok,r=p.skill(1001004); assert(not ok and r=='unsupported')
  ok,r=p.use_item(2000000); assert(not ok and r=='unsupported')
  assert(p.status().input_action=='attack')
  ok,r=p.skill(nil); assert(ok and r==nil and p.status().input_action==nil)
  return 'done'
end)lua"));
    Step(unsupported, other);
    StatusIs(other, "unsupported", "completed");
    Check(unsupported.requests.empty(), "unsupported inputs have no native side effects");
    for (const auto& bad :
         {"p.move('LEFT')", "p.move(1)", "p.skill()", "p.skill(nil, 1)", "p.skill(1, nil)", "p.skill(0)", "p.skill(-1)",
          "p.skill(2147483648)", "p.skill(1.5)", "p.skill('1')", "p.skill(false)", "p.skill({})", "p.use_item(nil)",
          "p.use_item(2147483648)", "p.jump(1)", "p.stop(1)"}) {
        const auto id = "invalid-" + std::to_string(other.Statuses().Elements().size());
        Start(other, id, Source("function main(c) local p=c.game.player; " + std::string(bad) + " end"));
        Step(unsupported, other);
        StatusIs(other, id, "cancelled", "script_error");
    }
}

void IdleFacts() {
    NativeBoundary native;
    native.allowStart = false; // Native admission is external to draft acceptance.
    native.state.actionIdle = Fact::Unknown;
    TickRuntime runtime(native);
    Start(runtime, "idle", Source(R"lua(
function main(c)
  local p=c.game.player; local idle=c.game.character.action_idle
  if c.tick.index==1 then
    assert(idle==nil and p.status().busy==nil)
    assert(p.attack())
    local s=p.status(); assert(s.input_action=='attack' and s.action==nil and s.busy==nil)
  elseif c.tick.index==2 then assert(idle==true and p.status().busy==false)
  elseif c.tick.index==3 then
    assert(idle==false and p.status().busy==true and p.status().action==nil)
    assert(p.skill(1001004))
    local s=p.status(); assert(s.input_action=='skill' and s.input_skill_id==1001004)
    assert(p.skill(nil)); s=p.status(); assert(s.input_action==nil and s.input_skill_id==nil and s.busy==true)
  elseif c.tick.index==4 then
    assert(idle==nil and p.status().busy==nil)
    assert(p.skill(nil)); assert(p.status().busy==nil)
  elseif c.tick.index==5 then return 'done' end
end
)lua"));
    Step(native, runtime);
    native.state.actionIdle = Fact::True;
    Step(native, runtime);
    native.state.actionIdle = Fact::False;
    Step(native, runtime);
    native.state.actionIdle = Fact::Unknown;
    Step(native, runtime);
    Drain(native, runtime, "idle", "completed");
    Check(native.delivered.empty(), "held intent alone must not manufacture an actual native action");
    Check(Field(Field(runtime.CurrentStatus("idle"), "player"), "busy").Type() == Value::Kind::Null,
          "unknown native idle must remain null in host status, never a fabricated false");
}

void Sessions() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(runtime, "a", Source(R"lua(function main(c)
  count=(count or 0)+1; assert(count==c.tick.index and c.game.inventory.status=='ok')
  if count==1 then c.game.player.move('left'); c.game.player.attack() end
end)lua"));
    Start(runtime, "b", Source(R"lua(function main(c)
  count=(count or 0)+1; assert(count==c.tick.index and c.game.inventory.status=='ok')
  if count==1 then c.game.player.move('right') end
end)lua"));
    native.queries.clear();
    Step(native, runtime);
    Check(native.queries["inventory"] == 1, "low-frequency samples are shared across independent Lua states");
    Check(native.requests.size() == 1 && native.changes.size() == 1 && native.directions[0] == "right",
          "independent Lua states share frame-final input in admission order");
    Step(native, runtime);
    runtime.Cancel("absent", "explicit_cancel");
    runtime.Cancel("b", "explicit_cancel");
    Check(native.releases == 0 && native.actionActive && native.desired.sessionId == "a",
          "cancelling a direction owner must not release another session's action input");
    Start(runtime, "c", Source(R"lua(function main(c)
  if c.tick.index==1 then c.game.player.move('down'); assert(c.game.player.skill(1001004)) end
end)lua"));
    Step(native, runtime);
    StatusIs(runtime, "b", "cancelled", "explicit_cancel");
    Check(native.directions == std::vector<std::string>{"down"} && native.desired.sessionId == "c",
          "a later session replaces direction and action independently of the old native A");
    const auto directionChanges = native.changes.size();
    const auto actionUpdates = native.intentCalls;
    runtime.Cancel("a", "explicit_cancel");
    Drain(native, runtime, "a", "cancelled", "explicit_cancel");
    Check(native.intentCalls == actionUpdates && native.releases == 0
              && native.directions == std::vector<std::string>{"down"} && native.changes.size() == directionChanges
              && native.desired.sessionId == "c" && native.ActiveAction()->sessionId == "a",
          "old-session cancellation must not clear the successor B or interrupt already-started A");
    native.Complete();
    Step(native, runtime);
    Check(native.delivered.size() == 2 && native.delivered.back().sessionId == "c",
          "native consumption after A finishes uses only the successor's current input");
    Start(runtime, "d",
          Source("function main(c) if c.tick.index==1 then assert(c.game.player.skill(1001004)) end end"));
    Step(native, runtime);
    runtime.Cancel("c", "explicit_cancel");
    Drain(native, runtime, "c", "cancelled");
    Check(native.desired.sessionId == "d" && native.desired.skillId == 1001004 && native.requests.size() == 2
              && native.delivered.size() == 2 && native.directions.empty(),
          "same-value input transfers ownership without re-pressing; cancelling its old owner cannot release it");
    runtime.Cancel("d", "explicit_cancel");
    Drain(native, runtime, "d", "cancelled");
    Check(native.desired.kind == ActionKind::Stop && native.actionActive,
          "the final owner releases input without waiting for animation completion");
    std::string error;
    Check(!runtime.Start("a", Source("function main() end"), 0, error) && error == "script_session_exists",
          "retained ids cannot silently replace a prior session");
    Check(runtime.Statuses().Elements().size() == 4 && !runtime.Running(), "statuses retain all independent sessions");
}

void Budgets() {
    for (const bool commit : {true, false}) {
        NativeBoundary native;
        TickRuntime runtime(native);
        Start(
            runtime, "abort",
            Source(std::string("-- @tick.budget_ms 1\n-- @tick.abort_commit ") + (commit ? "true" : "false")
                   + "\nfunction main(c) c.game.player.move('right'); c.game.player.attack(); while true do end end"));
        Step(native, runtime);
        Check(native.requests.size() == (commit ? 1U : 0U) && native.delivered.empty(),
              "abort commit controls admission, not fabricated immediate dispatch");
        Check(native.desired.kind == ActionKind::Stop && native.beginCalls == 0,
              "abort_commit admission must never leave a terminated session's action held");
        Drain(native, runtime, "abort", "cancelled", "tick_overrun");
        Check(native.delivered.empty(), "abort release before native consumption must not replay the committed input");
        Check(native.directions.empty()
                  && Field(Field(runtime.CurrentStatus("abort"), "tick"), "overruns").Number() == 1,
              "abort releases input and records its own budget overrun");
    }
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(runtime, "skip", Source(R"lua(-- @tick.budget_ms 1
-- @tick.overrun skip
function main(c)
  c.state.n=(c.state.n or 0)+1
  if c.state.n==1 then c.game.player.move('right'); while true do end end
  assert(c.tick.overrun==true and c.state.n==2)
  return 'done'
end
)lua"));
    Start(runtime, "fair", Source("function main(c) c.game.log('another session ran'); return 'done' end"));
    Step(native, runtime);
    StatusIs(runtime, "skip", "running");
    StatusIs(runtime, "fair", "completed");
    Check(native.directions == std::vector<std::string>{"right"} && native.logs.size() == 1,
          "skip commits draft and does not prevent later sessions from running");
    Step(native, runtime);
    Drain(native, runtime, "skip", "completed");
    std::string error;
    const auto started = std::chrono::steady_clock::now();
    Check(
        !runtime.Start("init-loop", Source("-- @tick.budget_ms 1\n-- @tick.overrun skip\nwhile true do end"), 0, error),
        "initialization chunk must be budgeted even under skip");
    Check(std::chrono::steady_clock::now() - started < std::chrono::seconds(1),
          "top-level infinite loop cannot hang the host");
    StatusIs(runtime, "init-loop", "rejected", "tick_overrun");
    Start(
        runtime, "deadline",
        Source(
            "-- @tick.budget_ms 1\n-- @tick.overrun skip\nfunction main(c) c.game.player.move('right'); while true do end end"),
        3);
    Step(native, runtime);
    std::this_thread::sleep_for(std::chrono::milliseconds(4));
    Step(native, runtime, true);
    Drain(native, runtime, "deadline", "cancelled", "time_limit");
}

void Lifecycle() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(runtime, "release", Source("function main(c) if c.tick.index==1 then c.game.player.move('right') end end"));
    Step(native, runtime);
    native.Advance();
    native.rejectClear = true;
    runtime.Cancel("release", "explicit_cancel");
    StatusIs(runtime, "release", "running");
    Check(!Field(runtime.CurrentStatus("release"), "control_released").Boolean(),
          "rejected keyup is not release confirmation");
    Step(native, runtime);
    StatusIs(runtime, "release", "running");
    native.rejectClear = false;
    Step(native, runtime);
    StatusIs(runtime, "release", "running");
    Step(native, runtime);
    StatusIs(runtime, "release", "cancelled", "explicit_cancel");
    Check(native.releases == 0, "direction release uses its own consumption fence, not action release");

    for (const auto& change : {"instance", "character", "left"}) {
        NativeBoundary io;
        TickRuntime engine(io);
        Start(engine, change, Source("function main(c) c.game.player.move('right'); c.game.player.attack() end"));
        Step(io, engine);
        if (std::string(change) == "instance")
            io.state.instanceId = "other";
        else if (std::string(change) == "character")
            io.state.character.id = 2;
        else
            io.state.inGame = io.state.ready = false;
        Step(io, engine, true);
        Drain(io, engine, change, "cancelled",
              std::string(change) == "instance"    ? "instance_changed"
              : std::string(change) == "character" ? "character_changed"
                                                   : "left_game");
        Check(io.desired.kind == ActionKind::Stop && io.directions.empty(),
              "identity or game loss clears both owned direction and action");
    }
    for (const auto& ending : {"done", "error", "abort"}) {
        NativeBoundary io;
        TickRuntime engine(io);
        const auto endingCode = std::string(ending) == "done"    ? "return 'done'"
                                : std::string(ending) == "error" ? "error('failed')"
                                                                 : "while true do end";
        Start(engine, ending,
              Source(std::string("-- @tick.budget_ms 1\nfunction main(c) if c.tick.index==1 then ")
                     + "c.game.player.move('right'); c.game.player.attack() else " + endingCode + " end end"));
        Step(io, engine);
        Step(io, engine); // A starts before main terminates: release must not erase it.
        Check(io.actionActive && io.desired.kind == ActionKind::Stop && !io.ActionIntentSettled(),
              "all completion paths clear held input and wait for native acknowledgement, not animation");
        Drain(io, engine, ending, std::string(ending) == "done" ? "completed" : "cancelled",
              std::string(ending) == "done"    ? "script_returned"
              : std::string(ending) == "error" ? "script_error"
                                               : "tick_overrun");
        Check(io.actionActive && io.delivered.size() == 1 && io.directions.empty(),
              "terminal publication must neither wait for nor interrupt an already-started action");
        Check(!engine.Running() && Field(Field(engine.CurrentStatus(ending), "player"), "busy").Boolean(),
              "a terminal session may still observe an actual native animation");
        io.Complete(); // No Runtime Tick: historical status must read fresh native facts.
        const auto idle = Field(engine.CurrentStatus(ending), "player");
        Check(!Field(idle, "busy").Boolean() && Field(idle, "phase").Text() == "idle"
                  && Field(idle, "action").Type() == Value::Kind::Null,
              "native animation completion must refresh busy/phase even after every session is terminal");
        io.state.actionIdle = Fact::Unknown;
        const auto unknown = Field(engine.CurrentStatus(ending), "player");
        Check(Field(unknown, "busy").Type() == Value::Kind::Null && Field(unknown, "phase").Text() == "unknown",
              "a historical status must preserve a newly unknown idle fact without running Lua again");
    }
    for (const bool cancel : {false, true}) {
        NativeBoundary io;
        TickRuntime engine(io);
        Start(engine, "before-consume",
              Source(std::string("function main(c) c.game.player.use_item(2000000); ")
                     + (cancel ? "end" : "return 'done' end")));
        Step(io, engine);
        if (cancel) engine.Cancel("before-consume", "explicit_cancel");
        Drain(io, engine, "before-consume", cancel ? "cancelled" : "completed");
        io.Complete();
        for (int i = 0; i < 3; ++i) Step(io, engine);
        Check(io.desired.kind == ActionKind::Stop && io.delivered.empty(),
              "ending before native consumption cannot preserve or later replay a held input");
    }

    NativeBoundary scene;
    TickRuntime changing(scene);
    Start(changing, "scene", Source(R"lua(function main(c)
  if c.tick.index==1 then c.game.player.move('right'); c.game.player.attack()
  elseif c.tick.index==2 then assert(c.game.player.use_item(2000000)) end
end)lua"));
    Step(scene, changing);
    Step(scene, changing); // Old-scene A has started; B is held but not admitted.
    ++scene.state.sceneGeneration;
    ++scene.state.mapId;
    Step(scene, changing);
    Check(scene.directions.empty() && scene.desired.kind == ActionKind::Stop
              && Field(changing.CurrentStatus("scene"), "resumes").Number() == 2,
          "scene transition clears direction and action and skips only that Lua frame");
    scene.Complete();
    for (int i = 0; i < 3; ++i) Step(scene, changing);
    Check(scene.directions.empty() && scene.requests.size() == 2 && scene.delivered.size() == 1
              && Field(changing.CurrentStatus("scene"), "resumes").Number() == 5,
          "stable frames never replay old-scene B after the previous animation completes");
    changing.CancelAll("explicit_cancel");
}

void Isolation() {
    NativeBoundary legacyIo, tickIo;
    Runtime legacy(legacyIo);
    TickRuntime tick(tickIo);
    std::string error;
    Check(legacy.Start("old", "assert(game.player==nil); game.move('left',5)", 0, error), error);
    Start(
        tick, "new",
        Source(
            "function main(c) assert(game.sleep==nil and game.move==nil and game.spawn==nil and game.observe==nil); if c.tick.index==1 then c.game.player.move('right') else error('tick failure') end end"));
    legacyIo.Advance();
    legacy.Tick();
    Step(tickIo, tick);
    Check(legacy.Running() && tick.Running() && legacyIo.requests.size() == 1 && tickIo.directions.size() == 1,
          "both engines can independently own native I/O");
    Step(tickIo, tick);
    Drain(tickIo, tick, "new", "cancelled", "script_error");
    Check(legacy.Running() && legacyIo.releases == 0 && legacyIo.actionActive,
          "tick failure cannot release or cancel legacy input");
    Start(tick, "survivor", Source("function main(c) if c.tick.index==1 then c.game.player.move('right') end end"));
    Step(tickIo, tick);
    legacy.Cancel("explicit_cancel");
    Check(tick.Running() && tickIo.directions == std::vector<std::string>{"right"},
          "legacy cancellation cannot touch tick lifecycle");
    for (int i = 0; i < 4; ++i) {
        legacyIo.Advance();
        legacy.Tick();
    }
    Check(!legacy.Running(), "legacy keeps its existing release protocol");
    tick.CancelAll("explicit_cancel");
    Drain(tickIo, tick, "survivor", "cancelled");
}

void Reentrancy() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(runtime, "reentrant",
          Source("function main(c) assert(c.tick.index==1); c.game.log('once'); c.game.player.attack() end"));
    int callbacks = 0;
    native.onIntent = [&] {
        ++callbacks;
        runtime.Tick();
        std::string error;
        Check(!runtime.Start("nested", Source("function main() end"), 0, error) && error == "tick_runtime_busy",
              "native callback cannot mutate session storage during submission");
        runtime.Cancel("reentrant", "callback_cancel");
    };
    native.onRelease = [&] {
        runtime.Tick();
        runtime.Cancel("reentrant", "second_cancel");
    };
    native.onLogs = [&] { runtime.Tick(); };
    Step(native, runtime);
    Check(callbacks == 1 && native.requests.size() == 1 && native.releases == 1,
          "reentrant callback is deferred until submission safely completes");
    Drain(native, runtime, "reentrant", "cancelled", "callback_cancel");
    Check(Field(runtime.CurrentStatus("reentrant"), "resumes").Number() == 1,
          "native callback never recursively calls Lua");
}

void Profiling() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Step(native, runtime);
    auto profile = runtime.Profile();
    Check(Field(profile, "host_tick_calls").Number() == 1 && Field(profile, "active_frames").Number() == 0,
          "idle host calls must be visible without becoming active frames");
    Check(native.queries.empty() && Field(Field(profile, "refresh_core"), "samples").Number() == 0,
          "idle profiling must not add native observations");
    Start(runtime, "profile", Source("function main(c) end"));
    Check(Field(Field(runtime.Profile(), "refresh_core"), "samples").Number() == 0,
          "session initialization must not be counted as host-tick sampling");
    Step(native, runtime);
    Step(native, runtime, true);
    profile = runtime.Profile();
    Check(Field(profile, "scope").Text() == "runtime_lifetime" && Field(profile, "host_tick_calls").Number() == 3
              && Field(profile, "active_frames").Number() == 2,
          "profile must distinguish all host calls from active processing");
    Check(Field(Field(profile, "observe"), "samples").Number() == 2
              && Field(Field(profile, "refresh_core"), "samples").Number() == 1,
          "transition frames copy the host state but must not refresh Lua domains");
    Check(Field(Field(profile, "tick"), "samples").Number() == 3, "whole-tick timing includes the idle early return");
    Check(Field(Field(profile, "lua"), "samples").Number() == 1,
          "Lua timing counts main calls, not initialization or transition frames");
    for (const char* phase : {"tick", "observe", "refresh_core", "lua"}) {
        const auto timing = Field(profile, phase);
        Check(Field(timing, "total_us").Number() >= Field(timing, "max_us").Number()
                  && Field(timing, "max_us").Number() >= 0,
              "inclusive timing aggregates must remain nonnegative and bounded by their total");
    }
    Check(Field(Field(runtime.CurrentStatus("profile"), "tick"), "profile").Dump() == profile.Dump(),
          "session status must identify the same runtime aggregate, not claim exclusive cost");
}

void MotionObservations() {
    static_assert(std::is_base_of<MovableObject, Character>::value, "self is a movable object");
    static_assert(std::is_base_of<MovableObject, OtherPlayer>::value, "other players share the base");
    static_assert(std::is_base_of<MovableObject, Monster>::value, "monsters share the base");
    static_assert(std::is_base_of<MovableObject, Npc>::value, "NPCs share the base");
    static_assert(std::is_base_of<MovableObject, Projectile>::value, "projectiles share the base");
    static_assert(std::is_base_of<MovableObject, Drop>::value, "moving drops share the base");
    NativeBoundary native;
    native.state.monsters.front().velocity = {MotionVector::Source::Native, -25, 5};
    OtherPlayer other;
    other.reference = "other";
    other.SetPosition(9, 8);
    other.velocity = {MotionVector::Source::Native, 13, -7};
    native.state.playersKnown = true;
    native.state.players.push_back(other);
    Npc npc;
    npc.objectId = 12;
    npc.templateId = 1000;
    npc.SetPosition(14, 15);
    npc.velocity.source = MotionVector::Source::Native; // observed zero, not a default unknown
    native.state.npcsKnown = true;
    native.state.npcs.push_back(npc);
    Drop drop;
    drop.objectId = 23;
    drop.SetPosition(24, 25);
    drop.velocity = {MotionVector::Source::NativeUpdateDelta, 2, 3, 8};
    native.state.dropsKnown = true;
    native.state.drops.push_back(drop);
    Projectile projectile;
    projectile.SetPosition(34, 35);
    projectile.velocity = {MotionVector::Source::NativeUpdateDelta, 200, -50, 8};
    native.state.projectilesKnown = true;
    native.state.projectilesComplete = Fact::False;
    native.state.projectiles.push_back(projectile);
    native.state.character.velocity.source = MapleControl::MotionVector::Source::Native;
    native.state.character.velocity.x = 100;
    native.state.character.velocity.y = -200;
    native.state.character.movement.known = true;
    native.state.character.movement.model = "contract_reference";
    native.state.character.movement.maxSpeed = 100;
    native.state.character.movement.maxJumpHeight = 75;
    native.state.character.movement.effectiveSpeed = 100;
    native.state.character.movement.effectiveJump = 100;
    TickRuntime runtime(native);
    Start(runtime, "motion", Source(R"lua(
function main(c)
  local w=c.game.character; local movement=w.movement
  assert(c.game.world.velocity==nil and c.game.world.on_ground==nil)
  assert(w.x~=nil and w.y~=nil and w.native_updates~=nil)
  if c.tick.index==1 then
    assert(w.velocity.source=='native' and w.velocity.x==100 and w.velocity.y==-200)
    assert(movement.kind=='model' and movement.model=='contract_reference')
    assert(movement.max_speed==100 and movement.max_jump_height==75)
    assert(movement.effective_speed==100 and movement.effective_jump==100)
    assert(movement.conditions=='stationary_flat_ground_normal')
    local scene=c.game.scene
    assert(scene.monsters[1].velocity.x==-25 and scene.monsters[1].velocity.y==5)
    assert(scene.players[1].velocity.x==13 and scene.players[1].velocity.y==-7)
    assert(scene.npcs[1].velocity.x==0 and scene.npcs[1].velocity.y==0)
    assert(scene.npcs[1].ref=='native-npc-reference')
    assert(scene.drops[1].velocity.x==2 and scene.drops[1].velocity.y==3)
    assert(scene.projectiles[1].x==34 and scene.projectiles[1].velocity.x==200)
    assert(scene.projectiles[1].velocity.source=='native_update_delta')
    assert(scene.projectiles[1].velocity.interval_ms==8 and scene.projectiles_complete==false)
  elseif c.tick.index==2 then
    assert(w.velocity.x==-10 and w.velocity.y==0 and movement.max_speed==127.5)
    assert(c.game.scene.monsters[1].velocity==nil)
    assert(c.game.scene.npcs[1].velocity.x==0 and c.game.scene.npcs[1].ref==nil)
  elseif c.tick.index==3 then
    assert(w.velocity==nil and movement==nil)
    assert(c.game.scene.players==nil) -- unreadable membership is not an empty collection
    return 'done'
  end
end
)lua"));
    Step(native, runtime);
    StatusIs(runtime, "motion", "running");
    native.state.character.velocity.x = -10;
    native.state.character.velocity.y = 0;
    native.state.character.movement.maxSpeed = 127.5;
    native.state.monsters.front().velocity = {};
    native.nativeNpcDomain = false;
    Step(native, runtime);
    StatusIs(runtime, "motion", "running");
    native.state.character.velocity = {};
    native.state.character.movement = {};
    native.state.playersKnown = false;
    Step(native, runtime);
    Drain(native, runtime, "motion", "completed");
    native.state.character.velocity.source = MapleControl::MotionVector::Source::Native;
    native.state.character.movement.known = true;
    native.state.playersKnown = true;
    for (const auto& field :
         {"game.character.velocity.x", "game.character.movement.max_speed", "game.scene.players[1].velocity.x",
          "game.scene.npcs[1].velocity.x", "game.scene.drops[1].velocity.x", "game.scene.projectiles[1].velocity.x"}) {
        const std::string id = field;
        Start(runtime, id, Source("function main(c) " + id + "=0 end"));
        Step(native, runtime);
        StatusIs(runtime, id, "cancelled", "script_error");
        Check(Field(runtime.CurrentStatus(id), "error").Text().find("read-only") != std::string::npos,
              "nested motion data must reject writes, not fail because a field is missing");
    }
}

void HeldSkillExample(const std::string& path) {
    std::ifstream input(path);
    Check(input.good(), "compiled held-skill example required");
    const std::string source{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
    for (const bool animation : {false, true}) {
        NativeBoundary native;
        native.startsAnimation = animation;
        auto now = std::chrono::steady_clock::time_point(std::chrono::seconds(100));
        TickRuntime runtime(native, [&] { return now; });
        Start(runtime, "held-skill-example", source);
        Step(native, runtime);
        Check(native.desired.skillId == 1001004 && native.requests.size() == 1,
              "the example must set its selected skill once on first invocation");
        now += std::chrono::milliseconds(50);
        Step(native, runtime);
        now += std::chrono::milliseconds(49);
        Step(native, runtime);
        Check(native.desired.skillId == 1001004 && native.intentCalls == 1 && native.delivered.size() == 1,
              "the example holds input before its explicit duration without replaying native updates");
        now += std::chrono::milliseconds(2);
        Step(native, runtime);
        Check(native.desired.kind == ActionKind::Stop && !native.ActionIntentSettled() && runtime.Running()
                  && !Field(runtime.CurrentStatus("held-skill-example"), "control_released").Boolean(),
              "done withdraws input but Runtime cannot publish completion before native release");
        Step(native, runtime);
        Check(runtime.Running() && TickField(runtime, "held-skill-example", "index").Number() == 4,
              "Runtime must wait on its native fence without calling Lua again to poll release");
        Step(native, runtime);
        StatusIs(runtime, "held-skill-example", "completed", "script_returned");
        Check(Field(runtime.CurrentStatus("held-skill-example"), "control_released").Boolean()
                  && TickField(runtime, "held-skill-example", "index").Number() == 4 && native.actionActive == animation
                  && native.intentCalls == 2 && native.beginCalls == 0,
              "Runtime confirms release after done with or without an ongoing native animation");
    }
}

void JumpAttackExample(const std::string& path, const std::string& direction) {
    std::ifstream input(path);
    Check(input.good(), "compiled example required");
    const std::string source{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
    for (bool groundKnown : {true, false}) {
        NativeBoundary native;
        native.state.onGround = groundKnown ? Fact::True : Fact::Unknown;
        native.state.character.velocity.source = MapleControl::MotionVector::Source::Native;
        native.state.character.movement.known = true;
        native.state.character.movement.model = "contract_reference";
        native.state.character.movement.maxSpeed = 100;
        native.state.character.movement.maxJumpHeight = 75;
        TickRuntime runtime(native);
        Start(runtime, "example", source, 2000);
        Step(native, runtime);
        if (!groundKnown) {
            StatusIs(runtime, "example", "cancelled", "script_error");
            Check(native.requests.empty() && native.changes.empty(),
                  "unknown ground facts must not be replaced with a positional landing guess");
            continue;
        }
        const std::vector<std::string> expected{direction};
        Check(native.requests.empty() && native.directions == expected,
              "the example must run up, not jump from rest with its first move");
        const double sign = direction == "right" ? 1 : -1;
        native.state.x = sign * 100;
        native.state.character.velocity.x = sign * 50;
        for (int i = 0; i < 4; ++i) Step(native, runtime);
        Check(native.requests.empty(), "distance or a low-speed plateau must not trigger takeoff");
        native.state.character.velocity.x = -sign * 100;
        Step(native, runtime);
        Check(native.requests.empty(), "speed in the wrong direction must not satisfy run-up");
        native.state.character.velocity.x = sign * 99.5;
        Step(native, runtime);
        Check(native.requests.size() == 1 && native.requests[0].kind == ActionKind::Jump,
              "the example must jump once its directed speed approaches the current reference");
        Check(native.directions == expected && native.changes.size() == 1,
              "jump must not pause the selected movement direction");

        // Supply external native animation/ground facts, not simulated game success:
        // jump animation can end while the character is still above the floor.
        native.state.y = -20;
        native.state.character.velocity = {};
        native.state.character.movement = {}; // air/landing do not depend on these facts
        native.state.onGround = groundKnown ? Fact::False : Fact::Unknown;
        Step(native, runtime);
        native.Complete();
        for (int i = 0; i < 16 && native.requests.size() < 2; ++i) Step(native, runtime);
        Check(native.requests.size() == 2 && native.requests.back().kind == ActionKind::Attack,
              "example must set its attack intent after liftoff, before landing");
        Check(native.directions == expected && native.changes.size() == 1,
              "air attack must preserve uninterrupted movement");
        native.allowStart = false;
        for (int i = 0; i < 3; ++i) Step(native, runtime);
        Check(native.desired.kind == ActionKind::Attack && native.delivered.size() == 1 && native.result.dispatched
                  && native.directions == expected,
              "airborne facts and the previous jump dispatch cannot withdraw an unstarted attack");
        native.allowStart = true;
        Step(native, runtime);
        Check(native.delivered.size() == 2 && native.active.kind == ActionKind::Attack
                  && native.desired.kind == ActionKind::Stop && native.actionActive,
              "only the actual native attack and dispatch permit withdrawal without interrupting its animation");
        native.Complete();
        for (int i = 0; i < 8; ++i) Step(native, runtime);
        Check(runtime.Running() && native.directions == expected && native.requests.size() == 2,
              "native action idle is not landing and must not resend the attack intent");

        native.state.y = 0;
        native.state.onGround = Fact::Unknown;
        native.advanceCharacter = false;
        for (int i = 0; i < 4; ++i) Step(native, runtime);
        Check(runtime.Running() && native.directions == expected,
              "repeated equal-height render samples cannot replace a missing native ground fact");
        native.advanceCharacter = true;
        native.state.onGround = Fact::True;
        for (int i = 0; i < 32 && runtime.Running(); ++i) {
            Step(native, runtime);
            if (native.directions.empty()) {
                // Restore the facts needed to confirm stopping, after actual landing release.
                native.state.character.velocity = {MotionVector::Source::Native, 0, 0};
                native.state.character.movement.known = true;
                native.state.character.movement.maxSpeed = 100;
            }
        }
        StatusIs(runtime, "example", "completed", "script_returned");
        Check(native.changes == std::vector<std::vector<std::string>>{expected, {}},
              "movement must have exactly one keydown and one final landing release");
        Check(Field(runtime.CurrentStatus("example"), "control_released").Boolean(),
              "example completed before native direction release was consumed");
        Check(native.delivered.size() == 2, "jump and attack intent must both reach the native consumer");
    }
}
}

int main(int argc, char** argv) {
    Check(argc == 2
              || (argc == 3 && (std::string(argv[1]) == "held-skill-example" || std::string(argv[1]) == "scene-script"))
              || (argc == 4 && std::string(argv[1]) == "jump-attack-example"),
          "scenario required");
    const std::string scenario = argv[1];
    if (scenario == "declarations")
        Declarations();
    else if (scenario == "cadence")
        Cadence();
    else if (scenario == "cadence-phase")
        CadencePhase();
    else if (scenario == "cadence-lifecycle")
        CadenceLifecycle();
    else if (scenario == "entry")
        Entry();
    else if (scenario == "scene-continuity")
        SceneContinuity();
    else if (scenario == "scene-cadence")
        SceneCadence();
    else if (scenario == "scene-held-intents")
        SceneHeldIntents();
    else if (scenario == "scene-unavailable")
        SceneUnavailable();
    else if (scenario == "scene-script")
        SceneScript(argv[2]);
    else if (scenario == "domains")
        Domains();
    else if (scenario == "draft")
        Draft();
    else if (scenario == "actions")
        Actions();
    else if (scenario == "held-intents")
        HeldIntents();
    else if (scenario == "idle-facts")
        IdleFacts();
    else if (scenario == "sessions")
        Sessions();
    else if (scenario == "budgets")
        Budgets();
    else if (scenario == "lifecycle")
        Lifecycle();
    else if (scenario == "isolation")
        Isolation();
    else if (scenario == "reentrancy")
        Reentrancy();
    else if (scenario == "profiling")
        Profiling();
    else if (scenario == "motion")
        MotionObservations();
    else if (scenario == "held-skill-example") {
        Check(argc == 3, "compiled held-skill example path required");
        HeldSkillExample(argv[2]);
    } else if (scenario == "jump-attack-example") {
        Check(argc == 4, "compiled example path and direction required");
        JumpAttackExample(argv[2], argv[3]);
    } else
        Check(false, "unknown scenario");
}
