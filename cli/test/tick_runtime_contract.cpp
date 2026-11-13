// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TickRuntime.h"

#include <algorithm>
#include <chrono>
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

class NativeBoundary final : public TickAdapter {
public:
    NativeBoundary() {
        state.instanceId = "tick-contract";
        state.inGame = state.ready = state.mapKnown = state.characterKnown = state.positionKnown = true;
        state.sceneGeneration = 1;
        state.mapId = 50000;
        state.character.id = 1;
        state.character.name = "contract";
        state.character.known.fill(true);
        state.character.values[6] = 100;
        state.monstersKnown = true;
        state.monsters.push_back({7, 100100, true, "snail", 12, 3, true, 100, 1});
    }

    const char* Backend() const override { return "contract"; }

    const State& Observe() const override { return state; }

    Observation ObserveDomain(const std::string& domain) const override {
        ++queries[domain];
        if (domain == "character")
            return {"ok",
                    Value::Object({{"buffs", {}},
                                   {"buffs_available", false},
                                   {"unavailable", Value::Array({"native_buff_details_unavailable"})}}),
                    {}};
        if (domain == "scene")
            return {
                "ok", Value::Object({{"npcs", Value::Array({Value::Object({{"id", 99}, {"name", "guide"}})})}}), {}};
        if (domain == "inventory")
            return {"ok",
                    Value::Object({{"items", Value::Array({Value::Object({{"item_id", 2000000}, {"quantity", 2}})})}}),
                    {}};
        if (domain == "quests") return {"unavailable", {}, "quest_sample_missing"};
        return {"unsupported", {}, "unsupported_observation_domain"};
    }

    bool Supports(ActionKind kind) const override { return kind != ActionKind::UseItem || supportsItems; }

    bool SupportsSkill() const override { return supportsSkills; }

    bool Begin(const Action& requested, std::string& error) override {
        if (!Released()) {
            error = "native_action_busy";
            return false;
        }
        requests.push_back(requested);
        events.push_back("begin");
        actionActive = pendingDelivery = true;
        result = {};
        result.dispatched = false;
        result.sessionId = requested.sessionId;
        result.reason = "native_dispatched";
        if (onBegin) onBegin();
        return true;
    }

    ActionResult Result() const override { return result; }

    void Release() override {
        ReleaseAction();
        if (!directions.empty()) {
            directions.clear();
            directionTicks = 1;
        }
    }

    void ReleaseAction() override {
        ++releases;
        events.push_back("release_action");
        actionActive = pendingDelivery = false;
        actionReleaseTicks = 2;
        result.controlReleased = false;
        if (onRelease) onRelease();
    }

    bool Released() const override { return !actionActive && actionReleaseTicks == 0; }

    bool ReleasePending() const override { return actionReleaseTicks != 0; }

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
        ++state.sequence;
        if (actionActive && pendingDelivery) {
            delivered.push_back(requests.back());
            pendingDelivery = false;
            result.dispatched = true;
        }
        if (directionTicks > 0) --directionTicks;
        if (actionReleaseTicks > 0 && --actionReleaseTicks == 0) result.controlReleased = true;
    }

    void Complete() {
        actionActive = false;
        result.controlReleased = true;
        result.reason = "native_completed";
    }

    State state;
    mutable std::map<std::string, int> queries;
    bool supportsItems = true, supportsSkills = true, rejectClear = false;
    bool actionActive = false, pendingDelivery = false;
    int actionReleaseTicks = 0, directionTicks = 0, releases = 0;
    ActionResult result;
    std::vector<Action> requests, delivered;
    std::vector<std::vector<std::string>> changes;
    std::vector<std::string> directions, events, logs;
    std::function<void()> onBegin, onRelease, onLogs;
};

std::string Source(const std::string& body) {
    return "-- @mode tick\n" + body;
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
    Check(config.mode == ScriptMode::Tick && config.budgetMs == .5 && config.skipOverrun && !config.abortCommit,
          "decimal budgets and explicit policies must not be truncated");
    const std::vector<std::string> invalid{"-- @mode unknown",
                                           "-- @mode tick\n-- @mode tick",
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

void Domains() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Step(native, runtime);
    Check(native.queries.empty(), "an unused tick engine cannot collect domains or burden the coroutine path");
    Start(runtime, "domains", Source(R"lua(
function main(c)
  local g=c.game
  assert(rawset==nil and getmetatable==nil and setmetatable==nil and debug==nil)
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
                                          "c.tick.index=0",
                                          "local f,t=pairs(game.character); t.hp=0",
                                          "rawset(game.character,'hp',0)"};
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
  if c.tick.index==1 then
    p.move('left'); p.move('right'); p.move('left'); p.move('right')
    p.jump(); p.pickup(); p.attack(); c.game.log('draft complete')
  elseif c.tick.index==2 then p.move('right'); assert(p.attack())
  elseif c.tick.index==3 then p.move(nil)
  elseif c.tick.index==4 then p.stop(); p.move('left'); p.stop()
  elseif c.tick.index==5 then return 'done' end
end
)lua"));
    Step(native, runtime);
    Check(native.requests.size() == 1 && native.requests[0].kind == ActionKind::Attack,
          "only final action draft is dispatched");
    Check(native.changes.size() == 1 && native.directions == std::vector<std::string>{"right"},
          "only final directional draft is submitted");
    Check(native.events.front() == "logs", "native effects must follow completion of the Lua entry");
    Step(native, runtime);
    Check(native.requests.size() == 1 && native.changes.size() == 1, "repeated intents must not replay input");
    Step(native, runtime);
    Check(native.directions.empty(), "move(nil) clears persistent input");
    Step(native, runtime);
    Check(native.requests.size() == 1 && native.releases == 1 && native.directions.empty(),
          "stop discards all earlier draft commands");
    Drain(native, runtime, "draft", "completed");
}

void Actions() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(runtime, "actions", Source(R"lua(
function main(c)
  local p=c.game.player; local i=c.tick.index
  if i==1 then p.move('right'); assert(p.attack())
  elseif i==2 then local ok,r=p.jump(); assert(not ok and r=='busy'); assert(p.attack())
  elseif i==3 then p.jump(); local ok,r=p.use_item(2000000); assert(not ok and r=='busy')
  elseif i==4 then assert(p.attack())
  elseif i==5 then p.jump(); p.pickup()
  elseif i==8 then local s=p.status(); assert(s.action=='pickup' and s.busy and s.moving=='right' and #s.held==1)
  elseif i==9 then local s=p.status(); assert(not s.busy and s.effect=='unknown')
  elseif i==10 then p.stop()
  elseif i==11 then return 'done' end
end
)lua"));
    for (int i = 1; i <= 5; ++i) {
        Step(native, runtime);
        Check(native.requests.size() == 1, "busy submissions and current-action idempotence cannot replay");
        const auto pending = Field(Field(runtime.CurrentStatus("actions"), "player"), "pending_action");
        if (i == 2 || i == 4)
            Check(pending.Type() == Value::Kind::Null, "last idempotent current action clears conflicting draft/queue");
        if (i == 3) Check(pending.Text() == "use_item", "only last busy action is queued");
        if (i == 5) Check(pending.Text() == "pickup", "queue is a single last-write slot");
    }
    native.result.controlReleased = true; // key-up consumed, animation still busy
    Step(native, runtime);
    Check(Field(Field(runtime.CurrentStatus("actions"), "player"), "held").Elements().size() == 1,
          "busy animation must not fabricate an attack key after native key-up");
    native.Complete();
    // The queued pickup begins at the end of this frame; inspect it next frame.
    Step(native, runtime);
    Check(native.requests.size() == 2 && native.requests.back().kind == ActionKind::Pickup && native.directions.empty(),
          "queued pickup starts once and pauses movement");
    Step(native, runtime); // next-frame status observes the queued pickup
    native.Complete();
    Step(native, runtime);
    Check(native.directions == std::vector<std::string>{"right"}, "completion automatically restores movement intent");
    Step(native, runtime);
    Drain(native, runtime, "actions", "completed");

    NativeBoundary completion;
    TickRuntime completing(completion);
    Start(completing, "done-item", Source("function main(c) c.game.player.use_item(2000000); return 'done' end"));
    Step(completion, completing);
    StatusIs(completing, "done-item", "running", "script_returned");
    Check(completion.releases == 0 && completion.delivered.empty(),
          "normal done cannot cancel a deferred native submission");
    Step(completion, completing);
    Check(completion.delivered.size() == 1 && Field(completing.CurrentStatus("done-item"), "resumes").Number() == 1,
          "draining performs actual native delivery without invoking Lua again");
    completion.Complete();
    Drain(completion, completing, "done-item", "completed");
    Start(completing, "cancel-drain", Source("function main(c) c.game.player.use_item(2000000); return 'done' end"));
    Step(completion, completing);
    completing.Cancel("cancel-drain", "explicit_cancel");
    Drain(completion, completing, "cancel-drain", "cancelled", "explicit_cancel");
    Check(completion.delivered.size() == 1, "explicit cancellation interrupts draining before native delivery");

    NativeBoundary unsupported;
    unsupported.supportsSkills = unsupported.supportsItems = false;
    TickRuntime other(unsupported);
    Start(
        other, "unsupported",
        Source(
            "function main(c) local p=c.game.player; local ok,r=p.skill(1001004); assert(not ok and r=='unsupported'); ok,r=p.use_item(2000000); assert(not ok and r=='unsupported'); return 'done' end"));
    Step(unsupported, other);
    StatusIs(other, "unsupported", "completed");
    Check(unsupported.requests.empty(), "unsupported inputs have no native side effects");
    for (const auto& bad :
         {"p.move('LEFT')", "p.move(1)", "p.skill(0)", "p.skill('1')", "p.use_item(2147483648)", "p.jump(1)"}) {
        const auto id = "invalid-" + std::to_string(other.Statuses().Elements().size());
        Start(other, id, Source("function main(c) local p=c.game.player; " + std::string(bad) + " end"));
        Step(unsupported, other);
        StatusIs(other, id, "cancelled", "script_error");
    }
    NativeBoundary skill;
    TickRuntime skills(skill);
    Start(skills, "skill", Source("function main(c) if c.tick.index==1 then c.game.player.skill(1001004) end end"));
    Step(skill, skills);
    Check(skill.requests.size() == 1 && skill.requests[0].kind == ActionKind::Attack
              && skill.requests[0].skillId == 1001004,
          "skill shares the action slot but preserves its native skill id");
}

void Sessions() {
    NativeBoundary native;
    TickRuntime runtime(native);
    Start(
        runtime, "a",
        Source(
            "function main(c) count=(count or 0)+1; assert(count==c.tick.index and c.game.inventory.status=='ok'); if count==1 then c.game.player.move('left'); c.game.player.attack() end end"));
    Start(
        runtime, "b",
        Source(
            "function main(c) count=(count or 0)+1; assert(count==c.tick.index and c.game.inventory.status=='ok'); if count==1 then c.game.player.move('right') end end"));
    native.queries.clear();
    Step(native, runtime);
    Check(native.queries["inventory"] == 1, "low-frequency samples are reused across all Lua states in one host tick");
    Check(native.requests.size() == 1 && native.changes.size() == 1 && native.directions[0] == "right",
          "independent Lua states share one frame-final state machine, in admission order");
    runtime.Cancel("absent", "explicit_cancel");
    runtime.Cancel("b", "explicit_cancel");
    Check(native.releases == 0 && native.actionActive,
          "cancelling movement owner cannot release another session's action");
    StatusIs(runtime, "b", "running");
    Start(runtime, "c", Source("function main(c) if c.tick.index==1 then c.game.player.move('down') end end"));
    Step(native, runtime);
    StatusIs(runtime, "b", "cancelled", "explicit_cancel");
    Check(native.directions == std::vector<std::string>{"down"},
          "new session can take movement without waiting for empty keys");
    Start(runtime, "queued", Source("function main(c) if c.tick.index==1 then c.game.player.jump() end end"));
    Step(native, runtime);
    runtime.Cancel("queued", "explicit_cancel");
    Check(native.releases == 0 && native.requests.size() == 1,
          "cancelling a queue owner neither releases nor replays another action");
    const auto directionChanges = native.changes.size();
    runtime.Cancel("a", "explicit_cancel");
    Check(native.releases == 1 && native.directions == std::vector<std::string>{"down"}
              && native.changes.size() == directionChanges && native.directionTicks == 0,
          "cancelling the action owner cannot emit directional edges for another session");
    Drain(native, runtime, "a", "cancelled", "explicit_cancel");
    Check(native.requests.size() == 1, "cancelled pending action is never dispatched");
    runtime.Cancel("c", "explicit_cancel");
    Drain(native, runtime, "c", "cancelled");
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
        if (commit) {
            StatusIs(runtime, "abort", "running", "tick_overrun");
            Check(native.releases == 0, "abort_commit true cannot erase an action before the next native frame");
            Step(native, runtime);
            Check(native.delivered.size() == 1,
                  "committed action must actually reach the native consumer exactly once");
            native.Complete();
        }
        Drain(native, runtime, "abort", "cancelled", "tick_overrun");
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
    Check(native.releases == 0, "directional release uses its own consumption fence, not whole-adapter action release");

    for (const auto& change : {"instance", "character", "left"}) {
        NativeBoundary io;
        TickRuntime engine(io);
        Start(engine, change, Source("function main(c) c.game.player.move('right') end"));
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
    }
    NativeBoundary pending;
    TickRuntime draining(pending);
    Start(draining, "active", Source("function main(c) if c.tick.index==1 then c.game.player.attack() end end"));
    Step(pending, draining);
    Start(draining, "queued-done", Source("function main(c) c.game.player.use_item(2000000); return 'done' end"), 20);
    Step(pending, draining);
    StatusIs(draining, "queued-done", "running", "script_returned");
    Check(pending.requests.size() == 1, "returned session retains its own pending action behind the occupied slot");
    pending.Complete();
    Step(pending, draining);
    Check(pending.requests.size() == 2 && pending.requests.back().kind == ActionKind::UseItem,
          "draining session's queued one-shot must execute after the previous owner completes");
    // Deadline remains authoritative while a returned entry drains native work.
    std::this_thread::sleep_for(std::chrono::milliseconds(21));
    Step(pending, draining);
    Drain(pending, draining, "queued-done", "cancelled", "time_limit");
    Check(pending.releases == 1, "session deadline can interrupt an already returned entry's native drain");
    draining.CancelAll("explicit_cancel");

    NativeBoundary scene;
    TickRuntime changing(scene);
    Start(changing, "scene", Source("function main(c) if c.tick.index==1 then c.game.player.move('right') end end"));
    Step(scene, changing);
    ++scene.state.sceneGeneration;
    ++scene.state.mapId;
    Step(scene, changing);
    Check(scene.directions.empty() && Field(changing.CurrentStatus("scene"), "resumes").Number() == 1,
          "scene transition releases old intent and skips only that Lua frame");
    Step(scene, changing);
    Check(scene.directions.empty() && Field(changing.CurrentStatus("scene"), "resumes").Number() == 2,
          "stable frame never automatically replays old-scene movement");
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
    native.onBegin = [&] {
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
    for (const char* phase : {"tick", "observe", "refresh_core"}) {
        const auto timing = Field(profile, phase);
        Check(Field(timing, "total_us").Number() >= Field(timing, "max_us").Number()
                  && Field(timing, "max_us").Number() >= 0,
              "inclusive timing aggregates must remain nonnegative and bounded by their total");
    }
    Check(Field(Field(runtime.CurrentStatus("profile"), "tick"), "profile").Dump() == profile.Dump(),
          "session status must identify the same runtime aggregate, not claim exclusive cost");
}

void JumpAttackExample(const std::string& path, const std::string& direction) {
    std::ifstream input(path);
    Check(input.good(), "compiled example required");
    const std::string source{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
    for (bool groundKnown : {true, false}) {
        NativeBoundary native;
        native.state.onGround = groundKnown ? Fact::True : Fact::Unknown;
        TickRuntime runtime(native);
        Start(runtime, "example", source, 2000);
        Step(native, runtime);
        const std::vector<std::string> expected{direction};
        Check(native.requests.size() == 1 && native.requests[0].kind == ActionKind::Jump,
              "example must jump once with the first directional intent");
        Check(native.directions == expected && native.changes.size() == 1,
              "jump must not pause the selected movement direction");

        // The fixture supplies external native facts, not simulated game success:
        // jump key-up is consumed while the character is still above the floor.
        native.state.y = -20;
        native.state.onGround = groundKnown ? Fact::False : Fact::Unknown;
        Step(native, runtime);
        native.Complete();
        for (int i = 0; i < 16 && native.requests.size() < 2; ++i) Step(native, runtime);
        Check(native.requests.size() == 2 && native.requests.back().kind == ActionKind::Attack,
              "example must submit its single attack after liftoff, before landing");
        Check(native.directions == expected && native.changes.size() == 1,
              "air attack must preserve uninterrupted movement");
        Step(native, runtime);
        native.Complete();
        for (int i = 0; i < 8; ++i) Step(native, runtime);
        Check(runtime.Running() && native.directions == expected && native.requests.size() == 2,
              "action-slot idle is not landing and must not repeat the attack");

        native.state.y = 0;
        native.state.onGround = groundKnown ? Fact::True : Fact::Unknown;
        for (int i = 0; i < 32 && runtime.Running(); ++i) Step(native, runtime);
        StatusIs(runtime, "example", "completed", "script_returned");
        Check(native.changes == std::vector<std::vector<std::string>>{expected, {}},
              "movement must have exactly one keydown and one final landing release");
        Check(Field(runtime.CurrentStatus("example"), "control_released").Boolean(),
              "example completed before native direction release was consumed");
        Check(native.delivered.size() == 2, "both one-shot inputs must reach the native consumer");
    }
}
}

int main(int argc, char** argv) {
    Check(argc == 2 || (argc == 4 && std::string(argv[1]) == "jump-attack-example"), "scenario required");
    const std::string scenario = argv[1];
    if (scenario == "declarations")
        Declarations();
    else if (scenario == "entry")
        Entry();
    else if (scenario == "domains")
        Domains();
    else if (scenario == "draft")
        Draft();
    else if (scenario == "actions")
        Actions();
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
    else if (scenario == "jump-attack-example") {
        Check(argc == 4, "compiled example path and direction required");
        JumpAttackExample(argv[2], argv[3]);
    } else
        Check(false, "unknown scenario");
}
