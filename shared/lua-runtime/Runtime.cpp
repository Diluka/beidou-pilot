// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Runtime.h"
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>

namespace MapleControl {
namespace {
std::uint64_t NowMs() {
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch())
            .count());
}

void Integer(lua_State* lua, const char* name, std::uint64_t value) {
    lua_pushinteger(lua, static_cast<lua_Integer>(value));
    lua_setfield(lua, -2, name);
}

void Number(lua_State* lua, const char* name, double value) {
    lua_pushnumber(lua, value);
    lua_setfield(lua, -2, name);
}

void Boolean(lua_State* lua, const char* name, bool value) {
    lua_pushboolean(lua, value);
    lua_setfield(lua, -2, name);
}

void String(lua_State* lua, const char* name, const std::string& value) {
    lua_pushlstring(lua, value.data(), value.size());
    lua_setfield(lua, -2, name);
}

void ObservedFact(lua_State* lua, const char* name, Fact value) {
    if (value == Fact::Unknown)
        lua_pushnil(lua);
    else
        lua_pushboolean(lua, value == Fact::True);
    lua_setfield(lua, -2, name);
}

const char* ActionName(ActionKind kind) {
    switch (kind) {
    case ActionKind::Move:
        return "move";
    case ActionKind::Face:
        return "face";
    case ActionKind::Jump:
        return "jump";
    case ActionKind::Attack:
        return "attack";
    case ActionKind::Pickup:
        return "pickup";
    case ActionKind::UseItem:
        return "use_item";
    case ActionKind::Stop:
        return "stop";
    case ActionKind::Equip:
        return "equip";
    case ActionKind::Unequip:
        return "unequip";
    case ActionKind::Revive:
        return "revive";
    case ActionKind::Activate:
        return "activate";
    case ActionKind::AllocateAp:
        return "allocate_ap";
    case ActionKind::AllocateSp:
        return "allocate_sp";
    case ActionKind::Window:
        return "window";
    }
    return "unsupported";
}

void PushValue(lua_State* lua, const Value& value);

void PushResult(lua_State* lua, const ActionResult& result) {
    lua_createtable(lua, 0, 5);
    if (!result.sessionId.empty()) String(lua, "session_id", result.sessionId);
    Boolean(lua, "dispatched", result.dispatched);
    Boolean(lua, "control_released", result.controlReleased);
    ObservedFact(lua, "settled", result.settled);
    String(lua, "effect", result.effect);
    if (!result.reason.empty()) String(lua, "reason", result.reason);
    if (result.allocation.Type() != Value::Kind::Null) {
        PushValue(lua, result.allocation);
        lua_setfield(lua, -2, "allocation");
    }
    if (result.ui.Type() != Value::Kind::Null) {
        PushValue(lua, result.ui);
        lua_setfield(lua, -2, "ui");
    }
    if (result.equipment.Type() != Value::Kind::Null) {
        PushValue(lua, result.equipment);
        lua_setfield(lua, -2, "equipment");
    }
    if (result.skillRequested) {
        Boolean(lua, "skill_dispatched", result.skill.dispatched);
        if (result.skill.nativeResultKnown) Integer(lua, "skill_native_result", result.skill.nativeResult);
        if (!result.skill.reason.empty()) String(lua, "skill_reason", result.skill.reason);
    }
}

void PushState(lua_State* lua, const State& state) {
    lua_newtable(lua);
    String(lua, "instance_id", state.instanceId);
    Integer(lua, "seq", state.sequence);
    Integer(lua, "observed_at_ms", state.observedAtMs);
    Integer(lua, "scene_generation", state.sceneGeneration);
    Boolean(lua, "ready", state.ready);
    Boolean(lua, "in_game", state.inGame);
    if (state.mapKnown) Integer(lua, "map_id", state.mapId);
    if (state.characterKnown) {
        lua_newtable(lua);
        Integer(lua, "id", state.character.id);
        String(lua, "name", state.character.name);
        static const char* names[]{"level",  "job", "strength", "dexterity",      "intelligence", "luck",      "hp",
                                   "max_hp", "mp",  "max_mp",   "ability_points", "skill_points", "experience"};
        for (std::size_t index = 0; index < state.character.values.size(); ++index)
            if (state.character.known[index]) Integer(lua, names[index], state.character.values[index]);
        lua_setfield(lua, -2, "character");
    }
    if (state.positionKnown) {
        lua_newtable(lua);
        Number(lua, "x", state.x);
        Number(lua, "y", state.y);
        lua_setfield(lua, -2, "position");
    }
    if (state.facingKnown) {
        lua_pushstring(lua, state.facingLeft ? "Left" : "Right");
        lua_setfield(lua, -2, "facing");
    }
    ObservedFact(lua, "settled", state.settled);
    ObservedFact(lua, "dead", state.dead);
    ObservedFact(lua, "revive_requestable", state.reviveRequestable);
    if (state.monstersKnown) {
        lua_createtable(lua, static_cast<int>(state.monsters.size()), 0);
        lua_Integer index = 1;
        for (const auto& monster : state.monsters) {
            lua_newtable(lua);
            Integer(lua, "object_id", monster.objectId);
            if (monster.templateKnown) Integer(lua, "template_id", monster.templateId);
            if (!monster.name.empty()) String(lua, "name", monster.name);
            Number(lua, "x", monster.x);
            Number(lua, "y", monster.y);
            Boolean(lua, "active", monster.active);
            if (monster.hpSequence != 0) {
                Integer(lua, "hp_percent", monster.hpPercent);
                Integer(lua, "hp_sequence", monster.hpSequence);
                String(lua, "hp_source", "server_mob_hp");
            }
            lua_rawseti(lua, -2, index++);
        }
        lua_setfield(lua, -2, "monsters");
    }
    if (state.inventoryKnown) {
        lua_createtable(lua, static_cast<int>(state.inventory.size()), 0);
        lua_Integer index = 1;
        for (const auto& item : state.inventory) {
            lua_newtable(lua);
            Integer(lua, "inventory_type", item.inventoryType);
            lua_pushinteger(lua, item.slot);
            lua_setfield(lua, -2, "slot");
            Integer(lua, "item_id", item.itemId);
            if (item.quantityKnown) Integer(lua, "quantity", item.quantity);
            lua_rawseti(lua, -2, index++);
        }
        lua_setfield(lua, -2, "inventory");
    }
    if (state.dropsKnown) {
        lua_createtable(lua, static_cast<int>(state.drops.size()), 0);
        lua_Integer index = 1;
        for (const auto& drop : state.drops) {
            lua_newtable(lua);
            Integer(lua, "object_id", drop.objectId);
            Number(lua, "x", drop.x);
            Number(lua, "y", drop.y);
            if (drop.itemKnown) Integer(lua, "item_id", drop.itemId);
            if (drop.moneyKnown) Integer(lua, "money", drop.money);
            ObservedFact(lua, "landed", drop.landed);
            lua_rawseti(lua, -2, index++);
        }
        lua_setfield(lua, -2, "drops");
    }
    if (state.playersKnown) {
        ObservedFact(lua, "players_complete", state.playersComplete);
        lua_createtable(lua, static_cast<int>(state.players.size()), 0);
        lua_Integer index = 1;
        for (const auto& player : state.players) {
            lua_newtable(lua);
            if (!player.reference.empty()) String(lua, "reference", player.reference);
            if (player.characterIdKnown) Integer(lua, "character_id", player.characterId);
            if (!player.name.empty()) String(lua, "name", player.name);
            if (player.levelKnown) Integer(lua, "level", player.level);
            Number(lua, "x", player.x);
            Number(lua, "y", player.y);
            if (player.facingKnown) String(lua, "facing", player.facingLeft ? "Left" : "Right");
            lua_rawseti(lua, -2, index++);
        }
        lua_setfield(lua, -2, "players");
    }
}

void PushValue(lua_State* lua, const Value& value) {
    switch (value.Type()) {
    case Value::Kind::Null:
        lua_pushnil(lua);
        break;
    case Value::Kind::Boolean:
        lua_pushboolean(lua, value.Boolean());
        break;
    case Value::Kind::Number: {
        const auto number = value.Number();
        const auto minimum = static_cast<double>(std::numeric_limits<lua_Integer>::min());
        if (number >= minimum && number < -minimum && std::trunc(number) == number)
            lua_pushinteger(lua, static_cast<lua_Integer>(number));
        else
            lua_pushnumber(lua, number);
        break;
    }
    case Value::Kind::String:
        lua_pushlstring(lua, value.Text().data(), value.Text().size());
        break;
    case Value::Kind::Array: {
        lua_createtable(lua, static_cast<int>(value.Elements().size()), 0);
        lua_Integer index = 1;
        for (const auto& entry : value.Elements()) {
            PushValue(lua, entry);
            lua_rawseti(lua, -2, index++);
        }
        break;
    }
    case Value::Kind::Object:
        lua_createtable(lua, 0, static_cast<int>(value.Members().size()));
        for (const auto& entry : value.Members()) {
            lua_pushlstring(lua, entry.first.data(), entry.first.size());
            PushValue(lua, entry.second);
            lua_rawset(lua, -3);
        }
        break;
    }
}

unsigned int Duration(lua_State* lua, int argument, double defaultSeconds, bool allowZero) {
    const double seconds = luaL_optnumber(lua, argument, defaultSeconds);
    if (!std::isfinite(seconds) || seconds > 30 || (allowZero ? seconds < 0 : seconds <= 0))
        luaL_error(lua, "duration must be %s 30 seconds", allowZero ? "between 0 and" : "greater than 0 and at most");
    return static_cast<unsigned int>(std::ceil(seconds * 1000));
}
}

struct Runtime::Impl {
    struct UpdateScope {
        bool& updating;

        explicit UpdateScope(bool& flag) : updating(flag) { updating = true; }

        ~UpdateScope() { updating = false; }
    };
    enum class WaitFor { None, Sleep, Action, RawKeys, Release, Control };

    struct Task {
        lua_State* coroutine = nullptr;
        int reference = LUA_NOREF;
        TaskStatus report;
        WaitFor wait = WaitFor::None;
        std::uint64_t wakeAt = 0;
        std::uint64_t requestOrder = 0;
        ActionResult result;
        bool resultReady = false;
        bool preempted = false;
        bool finished = false;
    };

    explicit Impl(Adapter& native) : adapter(native) {}

    ~Impl() { CloseLua(); }

    Adapter& adapter;
    lua_State* main = nullptr;
    std::vector<std::unique_ptr<Task>> tasks;
    Task* current = nullptr;
    Task* owner = nullptr;
    Task* actionOwner = nullptr;
    Status report;
    std::uint32_t actorId = 0;
    std::uint64_t limitAt = 0;
    std::uint64_t nextRequest = 0;
    std::uint64_t nextRevision = 0;
    TaskChangeResult changeResult;
    Task* changeTarget = nullptr;
    TaskOperation changeOperation = TaskOperation::Add;
    int replacementReference = LUA_NOREF;
    int replacementPriority = 0;
    std::uint64_t replacementGeneration = 0;
    bool updating = false;
    bool finishing = false;
    std::string finalStatus;
    std::string finalReason;
    std::vector<std::string> logs;
    std::size_t logBytes = 0;

    Task* FindTask(const std::string& name) const {
        for (auto task = tasks.rbegin(); task != tasks.rend(); ++task)
            if ((*task)->report.name == name) return task->get();
        return nullptr;
    }

    void DropReplacement() {
        if (replacementReference == LUA_NOREF) return;
        luaL_unref(main, LUA_REGISTRYINDEX, replacementReference);
        replacementReference = LUA_NOREF;
    }

    void CancelTaskChange(const std::string& reason) {
        if (changeResult.status != "pending") return;
        DropReplacement();
        changeTarget = nullptr;
        changeResult.status = "cancelled";
        changeResult.reason = reason;
    }

    Task* WaitingControl() const {
        Task* next = nullptr;
        for (const auto& task : tasks) {
            if (task->finished || task.get() == owner || task->wait != WaitFor::Control) continue;
            if (next == nullptr || task->report.priority > next->report.priority
                || (task->report.priority == next->report.priority && task->requestOrder < next->requestOrder))
                next = task.get();
        }
        return next;
    }

    void UpdateStatus() {
        report.tasks.clear();
        for (const auto& task : tasks) {
            auto status = task->report;
            switch (task->wait) {
            case WaitFor::None:
                status.wait = "none";
                break;
            case WaitFor::Sleep:
                status.wait = "sleep";
                break;
            case WaitFor::Action:
                status.wait = "action";
                break;
            case WaitFor::RawKeys:
                status.wait = "raw_keys";
                break;
            case WaitFor::Release:
                status.wait = "release";
                break;
            case WaitFor::Control:
                status.wait = "control";
                break;
            }
            if (!task->finished && task->wait != WaitFor::None) status.status = "waiting";
            report.tasks.push_back(std::move(status));
        }
        report.control.owner = owner == nullptr ? "" : owner->report.name;
        const auto* pending = WaitingControl();
        report.control.pending = pending == nullptr ? "" : pending->report.name;
    }

    void Transition(const Task* from, const Task* to, const char* reason) {
        report.control.from = from == nullptr ? "" : from->report.name;
        report.control.to = to == nullptr ? "" : to->report.name;
        report.control.reason = reason;
    }

    void CaptureResult() {
        if (actionOwner == nullptr || !adapter.Released()) return;
        auto& task = *actionOwner;
        if (task.wait == WaitFor::Release) {
            task.result = ActionResult{};
            task.result.dispatched = true;
            task.result.controlReleased = true;
            task.result.settled = adapter.Observe().settled;
            task.result.reason = "control_released";
        } else {
            task.result = adapter.Result();
            task.result.controlReleased = true;
        }
        if (task.preempted) task.result.reason = "control_preempted";
        task.resultReady = true;
        task.preempted = false;
        actionOwner = nullptr;
    }

    void ReleaseControl(Task& task, const char* reason, Task* next = nullptr) {
        if (owner != &task) return;
        owner = nullptr;
        Transition(&task, next, reason);
        if (actionOwner == &task && next != nullptr) task.preempted = true;
        if (!adapter.Released() && !adapter.ReleasePending()) adapter.Release();
        CaptureResult();
    }

    void GrantControl() {
        auto* next = WaitingControl();
        if (next == nullptr) return;
        if (owner != nullptr && next->report.priority > owner->report.priority)
            ReleaseControl(*owner, "priority_preempted", next);
        CaptureResult();
        if (owner == nullptr && adapter.Released()) {
            if (report.control.to != next->report.name || report.control.reason != "priority_preempted")
                Transition(nullptr, next, "acquired");
            owner = next;
        }
    }

    void ReleaseCoroutine(Task& task) {
        luaL_unref(main, LUA_REGISTRYINDEX, task.reference);
        task.reference = LUA_NOREF;
        task.coroutine = nullptr;
    }

    void FinishTask(Task& task, const char* status, const std::string& reason) {
        ReleaseControl(task, reason.c_str());
        task.finished = true;
        task.report.status = status;
        task.report.reason = reason;
        task.wait = WaitFor::None;
        if (current != &task) ReleaseCoroutine(task);
    }

    Task& AddTask(const std::string& name, int priority, lua_State* source, int function) {
        auto task = std::make_unique<Task>();
        task->report.name = name;
        task->report.revision = ++nextRevision;
        task->report.priority = priority;
        task->report.status = "running";
        function = lua_absindex(source, function);
        task->coroutine = lua_newthread(main);
        task->reference = luaL_ref(main, LUA_REGISTRYINDEX);
        lua_pushvalue(source, function);
        lua_xmove(source, task->coroutine, 1);
        lua_sethook(task->coroutine, Budget, LUA_MASKCOUNT, 50000);
        tasks.push_back(std::move(task));
        return *tasks.back();
    }

    void CompleteTaskChange() {
        if (changeResult.status != "pending" || actionOwner == changeTarget) return;
        if (changeOperation == TaskOperation::Replace) {
            lua_rawgeti(main, LUA_REGISTRYINDEX, replacementReference);
            auto& replacement = AddTask(changeResult.name, replacementPriority, main, -1);
            lua_pop(main, 1);
            DropReplacement();
            changeResult.revision = replacement.report.revision;
        }
        changeResult.status = "completed";
        changeResult.reason = changeOperation == TaskOperation::Replace ? "task_replaced" : "task_stopped";
        changeResult.changed = changeOperation == TaskOperation::Replace || changeResult.changed;
        changeResult.controlReleased = true;
        changeTarget = nullptr;
        UpdateStatus();
    }

    static Impl& Self(lua_State* lua) { return **static_cast<Impl**>(lua_getextraspace(lua)); }

    static void RequireRunning(lua_State* lua) {
        const auto& runtime = Self(lua);
        if (runtime.report.status != "running" || runtime.finishing || runtime.current->finished)
            luaL_error(lua, "game actions require a running task");
    }

    static void RequireControl(lua_State* lua) {
        RequireRunning(lua);
        auto& runtime = Self(lua);
        if (runtime.tasks.size() == 1 && runtime.owner == nullptr && runtime.adapter.Released()) {
            runtime.owner = runtime.current;
            runtime.Transition(nullptr, runtime.owner, "acquired");
        }
        if (runtime.owner != runtime.current) luaL_error(lua, "control_not_owned: call game.acquire and observe again");
    }

    static int Observe(lua_State* lua) {
        PushState(lua, Self(lua).adapter.Observe());
        return 1;
    }

    static int ObserveDomain(lua_State* lua) {
        static const char* domains[]{"stage",  "scene", "inventory", "character",   "quests",        "hotkeys",
                                     "dialog", "ui",    "shop",      "interaction", "notifications", nullptr};
        const auto domain = domains[luaL_checkoption(lua, 1, nullptr, domains)];
        const auto& adapter = Self(lua).adapter;
        const auto& state = adapter.Observe();
        const auto observation = !state.ready && std::strcmp(domain, "stage") != 0
                                     ? Observation{"unavailable", {}, "native_client_not_in_game"}
                                     : adapter.ObserveDomain(domain);
        lua_newtable(lua);
        String(lua, "domain", domain);
        String(lua, "status", observation.status);
        String(lua, "source", "client-native-api");
        Boolean(lua, "readonly", true);
        String(lua, "backend", adapter.Backend());
        String(lua, "instance_id", state.instanceId);
        Integer(lua, "seq", state.sequence);
        Integer(lua, "scene_generation", state.sceneGeneration);
        Integer(lua, "observed_at_ms", state.observedAtMs);
        Boolean(lua, "ready", state.ready);
        Boolean(lua, "in_game", state.inGame);
        if (state.characterKnown) Integer(lua, "character_id", state.character.id);
        if (state.mapKnown) Integer(lua, "map_id", state.mapId);
        PushValue(lua, observation.data);
        lua_setfield(lua, -2, "data");
        if (!observation.error.empty()) String(lua, "error", observation.error);
        return 1;
    }

    static int Capabilities(lua_State* lua) {
        const auto& adapter = Self(lua).adapter;
        lua_newtable(lua);
        String(lua, "backend", adapter.Backend());
        for (ActionKind kind :
             {ActionKind::Move, ActionKind::Face, ActionKind::Jump, ActionKind::Attack, ActionKind::Pickup,
              ActionKind::UseItem, ActionKind::Stop, ActionKind::Equip, ActionKind::Unequip, ActionKind::Revive,
              ActionKind::Activate, ActionKind::AllocateAp, ActionKind::AllocateSp, ActionKind::Window})
            Boolean(lua, ActionName(kind), adapter.Supports(kind));
        Boolean(lua, "raw_keys", adapter.SupportsRawKeys());
        Boolean(lua, "skill", adapter.SupportsSkill());
        Boolean(lua, "attack_move", adapter.Supports(ActionKind::Attack));
        Boolean(lua, "monster_hp_percent", adapter.SupportsMonsterHpPercent());
        return 1;
    }

    static int ReturnAction(lua_State* lua, int, lua_KContext) {
        const auto& runtime = Self(lua);
        PushResult(lua, runtime.current->result);
        return 1;
    }

    static void RequireAction(lua_State* lua, ActionKind kind) {
        RequireControl(lua);
        if (!Self(lua).adapter.Supports(kind)) luaL_error(lua, "unsupported: %s", ActionName(kind));
    }

    bool Begin(const Action& action, lua_State* lua) {
        CaptureResult();
        std::string error;
        Action bound = action;
        bound.sessionId = report.id;
        if (!adapter.Begin(bound, error)) {
            lua_pushlstring(lua, error.data(), error.size());
            return false;
        }
        return true;
    }

    static int FinishAction(lua_State* lua, bool accepted) {
        if (!accepted) return lua_error(lua);
        auto& runtime = Self(lua);
        runtime.actionOwner = runtime.current;
        runtime.current->resultReady = false;
        runtime.current->wait = WaitFor::Action;
        return lua_yieldk(lua, 0, 0, ReturnAction);
    }

    static int BeginSemantic(lua_State* lua, ActionKind kind, const char* direction, std::uint32_t durationMs,
                             std::uint32_t itemId, int sourceSlot = 0, int destinationSlot = 0,
                             std::uint32_t skillId = 0) {
        RequireAction(lua, kind);
        bool accepted;
        {
            Action action;
            action.kind = kind;
            action.direction = direction;
            action.durationMs = durationMs;
            action.itemId = itemId;
            action.skillId = skillId;
            action.sourceSlot = sourceSlot;
            action.destinationSlot = destinationSlot;
            accepted = Self(lua).Begin(action, lua);
        }
        return FinishAction(lua, accepted);
    }

    static const char* Direction(lua_State* lua, bool vertical) {
        const char* direction = luaL_checkstring(lua, 1);
        if (std::strcmp(direction, "left") == 0 || std::strcmp(direction, "right") == 0
            || (vertical && (std::strcmp(direction, "up") == 0 || std::strcmp(direction, "down") == 0)))
            return direction;
        luaL_error(lua, "unsupported direction");
        return "";
    }

    static int Move(lua_State* lua) {
        const char* direction = Direction(lua, true);
        const auto duration = Duration(lua, 2, 0.3, false);
        return BeginSemantic(lua, ActionKind::Move, direction, duration, 0);
    }

    static int Face(lua_State* lua) {
        const char* direction = Direction(lua, false);
        return BeginSemantic(lua, ActionKind::Face, direction, 40, 0);
    }

    static int Jump(lua_State* lua) {
        return BeginSemantic(lua, ActionKind::Jump, "", Duration(lua, 1, 0.06, false), 0);
    }

    static int Attack(lua_State* lua) {
        const auto duration = Duration(lua, 1, 0.06, false);
        const char* direction = "";
        if (!lua_isnoneornil(lua, 2)) {
            direction = luaL_checkstring(lua, 2);
            if (std::strcmp(direction, "left") != 0 && std::strcmp(direction, "right") != 0)
                return luaL_error(lua, "unsupported attack direction");
        }
        const auto skillId = lua_isnoneornil(lua, 3) ? 0 : luaL_checkinteger(lua, 3);
        if (!lua_isnoneornil(lua, 3) && (skillId < 1 || skillId > 2147483647))
            return luaL_error(lua, "skill id must be a positive int32");
        if (skillId != 0 && !Self(lua).adapter.SupportsSkill()) return luaL_error(lua, "unsupported: skill");
        return BeginSemantic(lua, ActionKind::Attack, direction, duration, 0, 0, 0,
                             static_cast<std::uint32_t>(skillId));
    }

    static int Pickup(lua_State* lua) {
        return BeginSemantic(lua, ActionKind::Pickup, "", Duration(lua, 1, 0.06, false), 0);
    }

    static int UseItem(lua_State* lua) {
        const auto itemId = luaL_checkinteger(lua, 1);
        if (itemId < 1 || itemId > 2147483647) return luaL_error(lua, "item id must be a positive int32");
        return BeginSemantic(lua, ActionKind::UseItem, "", 60, static_cast<std::uint32_t>(itemId));
    }

    static int Revive(lua_State* lua) {
        return BeginSemantic(lua, ActionKind::Revive, "", Duration(lua, 1, 6, false), 0);
    }

    static int Activate(lua_State* lua) {
        if (lua_gettop(lua) != 1) return luaL_error(lua, "activate accepts only a control reference");
        size_t length = 0;
        const auto* reference = luaL_checklstring(lua, 1, &length);
        if (length == 0 || length > 128) return luaL_error(lua, "control reference must contain 1..128 bytes");
        RequireAction(lua, ActionKind::Activate);
        bool accepted;
        {
            Action action;
            action.kind = ActionKind::Activate;
            action.reference.assign(reference, length);
            action.durationMs = 60;
            accepted = Self(lua).Begin(action, lua);
        }
        return FinishAction(lua, accepted);
    }

    static int ChangeEquipment(lua_State* lua, ActionKind kind) {
        if (lua_gettop(lua) < 2 || lua_gettop(lua) > 4)
            return luaL_error(lua, "equipment requires two slots, optional timeout and optional object reference");
        const auto sourceSlot = luaL_checkinteger(lua, 1);
        const auto destinationSlot = luaL_checkinteger(lua, 2);
        if (sourceSlot < std::numeric_limits<int>::min() || sourceSlot > std::numeric_limits<int>::max()
            || destinationSlot < std::numeric_limits<int>::min() || destinationSlot > std::numeric_limits<int>::max())
            return luaL_error(lua, "equipment slots must fit an int");
        if (kind == ActionKind::Equip) {
            if (sourceSlot <= 0 || destinationSlot >= 0)
                return luaL_error(lua, "equip requires a positive backpack slot and a negative equipped slot");
        } else if (sourceSlot >= 0 || destinationSlot <= 0)
            return luaL_error(lua, "unequip requires a negative equipped slot and a positive backpack slot");
        const auto duration = Duration(lua, 3, 3, false);
        std::size_t referenceLength = 0;
        const char* reference = "";
        if (!lua_isnoneornil(lua, 4)) {
            reference = luaL_checklstring(lua, 4, &referenceLength);
            if (referenceLength == 0 || referenceLength > 128 || std::memchr(reference, 0, referenceLength) != nullptr)
                return luaL_error(lua, "equipment reference must contain 1..128 bytes without NUL");
        }
        RequireAction(lua, kind);
        bool accepted;
        {
            Action action;
            action.kind = kind;
            action.durationMs = duration;
            action.sourceSlot = static_cast<int>(sourceSlot);
            action.destinationSlot = static_cast<int>(destinationSlot);
            action.reference.assign(reference, referenceLength);
            accepted = Self(lua).Begin(action, lua);
        }
        return FinishAction(lua, accepted);
    }

    static int Equip(lua_State* lua) { return ChangeEquipment(lua, ActionKind::Equip); }

    static int Unequip(lua_State* lua) { return ChangeEquipment(lua, ActionKind::Unequip); }

    static int Allocate(lua_State* lua, bool skill) {
        if (lua_gettop(lua) < 2 || lua_gettop(lua) > 3)
            return luaL_error(lua, "allocation requires a target, count and optional per-point timeout");
        const auto count = luaL_checkinteger(lua, 2);
        if (count < 1 || count > 100) return luaL_error(lua, "allocation count must be 1..100");
        const char* stat = "";
        lua_Integer skillId = 0;
        if (skill) {
            skillId = luaL_checkinteger(lua, 1);
            if (skillId < 1 || skillId > 2147483647) return luaL_error(lua, "skill id must be a positive int32");
        } else {
            stat = luaL_checkstring(lua, 1);
            if (std::strcmp(stat, "strength") != 0 && std::strcmp(stat, "dexterity") != 0
                && std::strcmp(stat, "intelligence") != 0 && std::strcmp(stat, "luck") != 0)
                return luaL_error(lua, "allocation requires a basic attribute");
        }
        const auto timeout = Duration(lua, 3, 1.2, false);
        RequireAction(lua, skill ? ActionKind::AllocateSp : ActionKind::AllocateAp);
        bool accepted;
        {
            Action action;
            action.kind = skill ? ActionKind::AllocateSp : ActionKind::AllocateAp;
            action.allocation.skill = skill;
            action.allocation.stat = stat;
            action.allocation.skillId = static_cast<std::uint32_t>(skillId);
            action.allocation.count = static_cast<unsigned>(count);
            action.allocation.timeoutMs = timeout;
            accepted = Self(lua).Begin(action, lua);
        }
        return FinishAction(lua, accepted);
    }

    static int AllocateAp(lua_State* lua) { return Allocate(lua, false); }

    static int AllocateSp(lua_State* lua) { return Allocate(lua, true); }

    static int Window(lua_State* lua) {
        if (lua_gettop(lua) < 2 || lua_gettop(lua) > 3)
            return luaL_error(lua, "window requires a name, open boolean and optional timeout");
        const char* name = luaL_checkstring(lua, 1);
        if (std::strcmp(name, "inventory") != 0 && std::strcmp(name, "stats") != 0 && std::strcmp(name, "skills") != 0)
            return luaL_error(lua, "window must be inventory, stats or skills");
        luaL_checktype(lua, 2, LUA_TBOOLEAN);
        const bool opened = lua_toboolean(lua, 2) != 0;
        const auto duration = Duration(lua, 3, 3, false);
        RequireAction(lua, ActionKind::Window);
        bool accepted;
        {
            Action action;
            action.kind = ActionKind::Window;
            action.reference = name;
            action.direction = opened ? "open" : "close";
            action.durationMs = duration;
            accepted = Self(lua).Begin(action, lua);
        }
        return FinishAction(lua, accepted);
    }

    static int Focus(lua_State* lua) {
        if (lua_gettop(lua) > 1) return luaL_error(lua, "focus accepts only an optional timeout");
        const auto duration = Duration(lua, 1, 3, false);
        RequireAction(lua, ActionKind::Window);
        bool accepted;
        {
            Action action;
            action.kind = ActionKind::Window;
            action.reference = "game";
            action.direction = "focus";
            action.durationMs = duration;
            accepted = Self(lua).Begin(action, lua);
        }
        return FinishAction(lua, accepted);
    }

    static int Sleep(lua_State* lua) {
        RequireRunning(lua);
        auto& runtime = Self(lua);
        runtime.current->wakeAt = NowMs() + Duration(lua, 1, 0, true);
        runtime.current->wait = WaitFor::Sleep;
        return lua_yield(lua, 0);
    }

    static int ReturnRelease(lua_State* lua, int, lua_KContext) {
        PushResult(lua, Self(lua).current->result);
        return 1;
    }

    static int Stop(lua_State* lua) {
        RequireRunning(lua);
        auto& runtime = Self(lua);
        auto& task = *runtime.current;
        if (!runtime.adapter.Supports(ActionKind::Stop)) return luaL_error(lua, "unsupported: stop");
        if (runtime.owner != &task) {
            if (runtime.actionOwner == &task && !runtime.adapter.Released()) {
                task.wait = WaitFor::Release;
                task.resultReady = false;
                return lua_yieldk(lua, 0, 0, ReturnRelease);
            }
            ActionResult result;
            result.controlReleased = true;
            result.reason = "control_not_owned";
            PushResult(lua, result);
            return 1;
        }
        runtime.CaptureResult();
        task.wait = WaitFor::Release;
        task.resultReady = false;
        runtime.actionOwner = &task;
        runtime.ReleaseControl(task, "released");
        return lua_yieldk(lua, 0, 0, ReturnRelease);
    }

    static int Spawn(lua_State* lua) {
        RequireRunning(lua);
        std::size_t size = 0;
        const char* name = luaL_checklstring(lua, 1, &size);
        const auto priority = luaL_checkinteger(lua, 2);
        luaL_checktype(lua, 3, LUA_TFUNCTION);
        if (size == 0 || size > 64 || std::memchr(name, '\0', size) != nullptr)
            return luaL_error(lua, "task name must contain 1..64 bytes without NUL");
        if (priority < std::numeric_limits<int>::min() || priority > std::numeric_limits<int>::max())
            return luaL_error(lua, "task priority must be int32");
        auto& runtime = Self(lua);
        for (const auto& task : runtime.tasks)
            if (task->report.name == name) return luaL_error(lua, "task name already exists");
        runtime.AddTask(name, static_cast<int>(priority), lua, 3);
        lua_pushvalue(lua, 1);
        return 1;
    }

    static int ReturnAcquire(lua_State*, int, lua_KContext) { return 0; }

    static int Acquire(lua_State* lua) {
        RequireRunning(lua);
        auto& runtime = Self(lua);
        auto& task = *runtime.current;
        if (runtime.owner == &task) return 0;
        task.requestOrder = ++runtime.nextRequest;
        task.wait = WaitFor::Control;
        runtime.GrantControl();
        return lua_yieldk(lua, 0, 0, ReturnAcquire);
    }

    static int CancelTask(lua_State* lua) {
        RequireRunning(lua);
        const char* name = luaL_checkstring(lua, 1);
        auto& runtime = Self(lua);
        auto* target = runtime.FindTask(name);
        if (target == nullptr) return luaL_error(lua, "unknown task");
        const bool cancelled = !target->finished;
        if (cancelled) runtime.FinishTask(*target, "cancelled", "task_cancelled");
        if (target == runtime.current && cancelled) return lua_yield(lua, 0);
        lua_pushboolean(lua, cancelled);
        return 1;
    }

    static int Tasks(lua_State* lua) {
        auto& runtime = Self(lua);
        runtime.UpdateStatus();
        lua_newtable(lua);
        lua_createtable(lua, static_cast<int>(runtime.report.tasks.size()), 0);
        lua_Integer index = 1;
        for (const auto& task : runtime.report.tasks) {
            lua_newtable(lua);
            String(lua, "name", task.name);
            lua_pushinteger(lua, static_cast<lua_Integer>(task.revision));
            lua_setfield(lua, -2, "revision");
            lua_pushinteger(lua, task.priority);
            lua_setfield(lua, -2, "priority");
            String(lua, "status", task.status);
            String(lua, "wait", task.wait);
            if (!task.reason.empty()) String(lua, "reason", task.reason);
            if (!task.error.empty()) String(lua, "error", task.error);
            lua_rawseti(lua, -2, index++);
        }
        lua_setfield(lua, -2, "tasks");
        lua_newtable(lua);
        const auto& control = runtime.report.control;
        if (!control.owner.empty()) String(lua, "owner", control.owner);
        if (!control.pending.empty()) String(lua, "pending", control.pending);
        if (!control.from.empty()) String(lua, "from", control.from);
        if (!control.to.empty()) String(lua, "to", control.to);
        if (!control.reason.empty()) String(lua, "reason", control.reason);
        lua_setfield(lua, -2, "control");
        return 1;
    }

    bool ApplyRawKeys(lua_State* lua, std::uint32_t durationMs) {
        std::vector<std::string> keys;
        if (lua_type(lua, 1) == LUA_TSTRING) {
            std::size_t size = 0;
            const char* value = lua_tolstring(lua, 1, &size);
            keys.emplace_back(value, size);
        } else {
            const auto count = lua_rawlen(lua, 1);
            for (std::size_t index = 0; index < count; ++index) {
                lua_rawgeti(lua, 1, static_cast<lua_Integer>(index + 1));
                std::size_t size = 0;
                const char* value = lua_tolstring(lua, -1, &size);
                keys.emplace_back(value, size);
                lua_pop(lua, 1);
            }
        }
        std::string error;
        if (!adapter.RawKeys(keys, durationMs, error)) {
            lua_pushlstring(lua, error.data(), error.size());
            return false;
        }
        return true;
    }

    static void CheckRawKeys(lua_State* lua) {
        if (!Self(lua).adapter.SupportsRawKeys()) luaL_error(lua, "unsupported: raw_keys");
        if (lua_type(lua, 1) == LUA_TSTRING) return;
        luaL_checktype(lua, 1, LUA_TTABLE);
        const auto count = lua_rawlen(lua, 1);
        if (count > 16) luaL_error(lua, "at most 16 keys are supported");
        for (std::size_t index = 0; index < count; ++index) {
            lua_rawgeti(lua, 1, static_cast<lua_Integer>(index + 1));
            luaL_checktype(lua, -1, LUA_TSTRING);
            lua_pop(lua, 1);
        }
    }

    static int Press(lua_State* lua) {
        RequireControl(lua);
        CheckRawKeys(lua);
        const auto duration = Duration(lua, 2, 0.06, false);
        auto& runtime = Self(lua);
        runtime.CaptureResult();
        if (!runtime.ApplyRawKeys(lua, duration)) return lua_error(lua);
        runtime.actionOwner = runtime.current;
        runtime.current->resultReady = false;
        runtime.current->wait = WaitFor::RawKeys;
        return lua_yieldk(lua, 0, 0, ReturnRelease);
    }

    static int Keys(lua_State* lua) {
        RequireControl(lua);
        CheckRawKeys(lua);
        const auto duration = Duration(lua, 2, 0.1, false);
        auto& runtime = Self(lua);
        runtime.CaptureResult();
        if (!runtime.ApplyRawKeys(lua, duration)) return lua_error(lua);
        runtime.actionOwner = runtime.current;
        runtime.current->resultReady = false;
        return 0;
    }

    bool CallSkill(lua_State* lua, std::uint32_t skillId) {
        SkillResult result;
        std::string error;
        if (!adapter.Skill(skillId, result, error)) {
            lua_pushlstring(lua, error.data(), error.size());
            return false;
        }
        lua_newtable(lua);
        if (result.nativeResultKnown) Integer(lua, "native_result", result.nativeResult);
        Boolean(lua, "dispatched", result.dispatched);
        String(lua, "effect", "unknown");
        if (!result.reason.empty()) String(lua, "reason", result.reason);
        return true;
    }

    static int Skill(lua_State* lua) {
        RequireControl(lua);
        if (!Self(lua).adapter.SupportsSkill()) return luaL_error(lua, "unsupported: skill");
        const auto skillId = luaL_checkinteger(lua, 1);
        if (skillId < 1 || skillId > 2147483647) return luaL_error(lua, "skill id must be a positive int32");
        if (!Self(lua).CallSkill(lua, static_cast<std::uint32_t>(skillId))) return lua_error(lua);
        return 1;
    }

    static int Time(lua_State* lua) {
        lua_pushnumber(lua, static_cast<lua_Number>(NowMs()) / 1000);
        return 1;
    }

    static int Log(lua_State* lua) {
        RequireRunning(lua);
        auto& runtime = Self(lua);
        std::size_t size = 0;
        const char* text = luaL_checklstring(lua, 1, &size);
        if (size > 4096 || runtime.logBytes + size > 65536)
            return luaL_error(lua, "script log limit exceeded for this resume");
        if (runtime.current->report.name == "main")
            runtime.logs.emplace_back(text, size);
        else
            runtime.logs.push_back("[" + runtime.current->report.name + "] " + std::string(text, size));
        runtime.logBytes += size;
        return 0;
    }

    static void Budget(lua_State* lua, lua_Debug*) {
        if (!lua_isyieldable(lua)) {
            luaL_error(lua, "instruction budget exhausted in a non-yieldable call");
            return;
        }
        ++Self(lua).report.budgetYields;
        lua_yield(lua, 0);
    }

    void Finish(const std::string& status, const std::string& reason) {
        CancelTaskChange(reason);
        finishing = true;
        finalStatus = status;
        finalReason = reason;
        owner = nullptr;
        for (auto& task : tasks)
            if (!task->finished) {
                task->finished = true;
                task->report.status = "cancelled";
                task->report.reason = reason;
                task->wait = WaitFor::None;
            }
        if (!adapter.Released() && !adapter.ReleasePending()) adapter.Release();
        UpdateStatus();
    }

    void CloseLua() {
        DropReplacement();
        if (main != nullptr) lua_close(main);
        main = nullptr;
        tasks.clear();
        owner = current = actionOwner = nullptr;
    }
};

Runtime::Runtime(Adapter& adapter) : impl(new Impl(adapter)) {}

Runtime::~Runtime() = default;

bool Runtime::Start(const std::string& scriptId, const std::string& source, std::uint32_t limitMs, std::string& error) {
    if (Running()) {
        error = "script_running";
        return false;
    }
    auto& runtime = *impl;
    runtime.CloseLua();
    runtime.report = Status{};
    runtime.report.id = scriptId;
    runtime.report.status = "rejected";
    runtime.nextRequest = 0;
    runtime.nextRevision = 0;
    runtime.changeResult = TaskChangeResult{};
    runtime.changeTarget = nullptr;
    runtime.finishing = false;
    runtime.finalStatus.clear();
    runtime.finalReason.clear();
    runtime.logs.clear();
    runtime.logBytes = 0;
    const auto& state = runtime.adapter.Observe();
    runtime.actorId = state.character.id;
    runtime.limitAt = limitMs == 0 ? 0 : NowMs() + limitMs;
    runtime.main = luaL_newstate();
    if (runtime.main == nullptr) {
        runtime.report.reason = error = "lua_state_unavailable";
        return false;
    }
    *static_cast<Impl**>(lua_getextraspace(runtime.main)) = &runtime;
    static const luaL_Reg libraries[]{{LUA_GNAME, luaopen_base},        {LUA_TABLIBNAME, luaopen_table},
                                      {LUA_STRLIBNAME, luaopen_string}, {LUA_MATHLIBNAME, luaopen_math},
                                      {LUA_UTF8LIBNAME, luaopen_utf8},  {nullptr, nullptr}};
    for (const auto* library = libraries; library->func != nullptr; ++library) {
        luaL_requiref(runtime.main, library->name, library->func, 1);
        lua_pop(runtime.main, 1);
    }
    for (const char* name :
         {"dofile", "loadfile", "load", "print", "pcall", "xpcall", "setmetatable", "getmetatable"}) {
        lua_pushnil(runtime.main);
        lua_setglobal(runtime.main, name);
    }
    static const luaL_Reg functions[]{{"state", Impl::Observe},
                                      {"observe", Impl::ObserveDomain},
                                      {"capabilities", Impl::Capabilities},
                                      {"time", Impl::Time},
                                      {"sleep", Impl::Sleep},
                                      {"log", Impl::Log},
                                      {"move", Impl::Move},
                                      {"face", Impl::Face},
                                      {"jump", Impl::Jump},
                                      {"attack", Impl::Attack},
                                      {"pickup", Impl::Pickup},
                                      {"use_item", Impl::UseItem},
                                      {"equip", Impl::Equip},
                                      {"unequip", Impl::Unequip},
                                      {"allocate_ap", Impl::AllocateAp},
                                      {"allocate_sp", Impl::AllocateSp},
                                      {"window", Impl::Window},
                                      {"focus", Impl::Focus},
                                      {"revive", Impl::Revive},
                                      {"activate", Impl::Activate},
                                      {"stop", Impl::Stop},
                                      {"press", Impl::Press},
                                      {"keys", Impl::Keys},
                                      {"skill", Impl::Skill},
                                      {"spawn", Impl::Spawn},
                                      {"acquire", Impl::Acquire},
                                      {"cancel", Impl::CancelTask},
                                      {"tasks", Impl::Tasks},
                                      {nullptr, nullptr}};
    luaL_newlib(runtime.main, functions);
    lua_setglobal(runtime.main, "game");
    const int loaded = luaL_loadbufferx(runtime.main, source.data(), source.size(), scriptId.c_str(), "t");
    if (loaded != LUA_OK) {
        const char* message = lua_tostring(runtime.main, -1);
        runtime.report.reason = "script_load_error";
        runtime.report.error = message != nullptr ? message : "Lua load failed";
        error = runtime.report.error;
        runtime.CloseLua();
        return false;
    }
    runtime.owner = &runtime.AddTask("main", 0, runtime.main, -1);
    runtime.Transition(nullptr, runtime.owner, "acquired");
    runtime.report.status = "running";
    runtime.UpdateStatus();
    return true;
}

void Runtime::Tick(bool sceneChanged) {
    auto& runtime = *impl;
    if (runtime.updating || runtime.report.status != "running") return;
    Impl::UpdateScope scope(runtime.updating);
    const auto& state = runtime.adapter.Observe();
    runtime.CaptureResult();
    if (runtime.finishing) {
        if (!runtime.adapter.Released()) return;
        runtime.UpdateStatus();
        runtime.report.status = runtime.finalStatus;
        runtime.report.reason = runtime.finalReason;
        runtime.CloseLua();
        return;
    }
    if (state.characterKnown && state.character.id != runtime.actorId) {
        runtime.Finish("cancelled", "character_changed");
        return;
    }
    if (!state.inGame) {
        runtime.Finish("cancelled", "left_game");
        return;
    }
    const auto now = NowMs();
    if (runtime.limitAt != 0 && now >= runtime.limitAt) {
        runtime.Finish("cancelled", "time_limit");
        return;
    }
    if (runtime.changeResult.status == "pending" && runtime.changeOperation == TaskOperation::Replace
        && state.sceneGeneration != runtime.replacementGeneration)
        runtime.CancelTaskChange("task_context_changed");
    runtime.CompleteTaskChange();
    if (sceneChanged) return;
    runtime.GrantControl();
    std::vector<Impl::Task*> scheduled;
    for (const auto& task : runtime.tasks)
        if (!task->finished) scheduled.push_back(task.get());
    std::stable_sort(scheduled.begin(), scheduled.end(), [](const auto* left, const auto* right) {
        return left->report.priority > right->report.priority;
    });
    for (auto* task : scheduled) {
        if (task->finished) continue;
        if (task->wait == Impl::WaitFor::Sleep && now < task->wakeAt) continue;
        if ((task->wait == Impl::WaitFor::Action || task->wait == Impl::WaitFor::RawKeys
             || task->wait == Impl::WaitFor::Release)
            && !task->resultReady)
            continue;
        if (task->wait == Impl::WaitFor::Control && runtime.owner != task) continue;
        task->wait = Impl::WaitFor::None;
        task->resultReady = false;
        runtime.current = task;
        const auto started = std::chrono::steady_clock::now();
        int results = 0;
        const int status = lua_resume(task->coroutine, nullptr, 0, &results);
        const auto elapsed = std::chrono::steady_clock::now() - started;
        ++runtime.report.resumes;
        runtime.report.lastResumeUs = std::chrono::duration<double, std::micro>(elapsed).count();
        runtime.report.maxResumeUs = (std::max)(runtime.report.maxResumeUs, runtime.report.lastResumeUs);
        if (!runtime.logs.empty() && !runtime.adapter.Logs(runtime.report.id, runtime.logs))
            runtime.Finish("cancelled", "script_log_write_failed");
        runtime.logs.clear();
        runtime.logBytes = 0;
        runtime.current = nullptr;
        if (runtime.finishing) break;
        if (task->finished)
            runtime.ReleaseCoroutine(*task);
        else if (status == LUA_OK)
            runtime.FinishTask(*task, "completed", "script_returned");
        else if (status != LUA_YIELD) {
            const char* message = lua_tostring(task->coroutine, -1);
            task->report.error = message != nullptr ? message : "Lua runtime error";
            runtime.report.error = task->report.error;
            runtime.Finish("cancelled", "script_error");
            break;
        }
        runtime.CaptureResult();
        runtime.GrantControl();
    }
    if (!runtime.finishing && runtime.changeResult.status != "pending"
        && std::all_of(runtime.tasks.begin(), runtime.tasks.end(), [](const auto& task) { return task->finished; }))
        runtime.Finish("completed", "script_returned");
    runtime.UpdateStatus();
}

void Runtime::Cancel(const std::string& reason) {
    if (Running() && !impl->finishing) impl->Finish("cancelled", reason);
}

TaskChangeResult Runtime::ManageTask(const TaskChange& change) {
    auto& runtime = *impl;
    TaskChangeResult result;
    result.requestId = change.requestId;
    result.scriptId = change.scriptId;
    result.name = change.name;
    result.status = "rejected";
    if (change.scriptId != runtime.report.id) {
        result.reason = "script_session_mismatch";
        return result;
    }
    if (!Running() || runtime.finishing) {
        result.reason = "script_session_unavailable";
        return result;
    }
    if (runtime.updating || runtime.changeResult.status == "pending") {
        result.reason = "task_management_busy";
        return result;
    }
    Impl::UpdateScope scope(runtime.updating);
    if (change.name.empty() || change.name.size() > 64 || change.name.find('\0') != std::string::npos) {
        result.reason = "invalid_task_name";
        return result;
    }
    if (change.name == "main") {
        result.reason = "reserved_task_name";
        return result;
    }
    auto* target = runtime.FindTask(change.name);
    if (change.operation == TaskOperation::Add) {
        if (target != nullptr) {
            result.reason = "task_name_exists";
            return result;
        }
    } else {
        if (target == nullptr) {
            result.reason = "unknown_task";
            return result;
        }
        result.revision = target->report.revision;
        if (change.expectedRevision != target->report.revision) {
            result.reason = "task_revision_mismatch";
            return result;
        }
    }
    if (change.operation == TaskOperation::Stop && target->finished && runtime.actionOwner != target) {
        result.status = "completed";
        result.reason = "task_already_finished";
        result.controlReleased = true;
        return result;
    }
    if (change.operation != TaskOperation::Stop) {
        const int top = lua_gettop(runtime.main);
        const auto chunkName = change.scriptId + "/" + change.name + "/" + change.requestId;
        const int loaded =
            luaL_loadbufferx(runtime.main, change.source.data(), change.source.size(), chunkName.c_str(), "t");
        if (loaded != LUA_OK) {
            const char* message = lua_tostring(runtime.main, -1);
            result.reason = "task_load_error";
            result.error = message != nullptr ? message : "Lua load failed";
            lua_settop(runtime.main, top);
            return result;
        }
        if (change.operation == TaskOperation::Add) {
            auto& task = runtime.AddTask(change.name, change.priority, runtime.main, -1);
            result.revision = task.report.revision;
            result.status = "completed";
            result.reason = "task_added";
            result.changed = result.controlReleased = true;
            lua_settop(runtime.main, top);
            runtime.UpdateStatus();
            return result;
        }
        runtime.replacementReference = luaL_ref(runtime.main, LUA_REGISTRYINDEX);
        runtime.replacementPriority = change.priority;
        runtime.replacementGeneration = runtime.adapter.Observe().sceneGeneration;
        lua_settop(runtime.main, top);
    }
    runtime.changeOperation = change.operation;
    runtime.changeTarget = target;
    result.status = "pending";
    result.changed = !target->finished;
    runtime.changeResult = result;
    if (!target->finished)
        runtime.FinishTask(*target, "cancelled",
                           change.operation == TaskOperation::Replace ? "task_replaced" : "task_stopped");
    runtime.CaptureResult();
    runtime.CompleteTaskChange();
    runtime.UpdateStatus();
    return runtime.changeResult;
}

const TaskChangeResult* Runtime::CurrentTaskChange() const {
    return impl->changeResult.requestId.empty() ? nullptr : &impl->changeResult;
}

bool Runtime::Running() const {
    return impl->report.status == "running";
}

const Status* Runtime::CurrentStatus() const {
    if (impl->main != nullptr) impl->UpdateStatus();
    return impl->report.id.empty() ? nullptr : &impl->report;
}

}
