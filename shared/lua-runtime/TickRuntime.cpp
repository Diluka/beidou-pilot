// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TickRuntime.h"
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <set>
#include <utility>

namespace MapleControl {
namespace {
using Clock = std::chrono::steady_clock;

struct Timing {
    std::uint64_t samples = 0;
    double totalUs = 0, maxUs = 0;

    void Record(double us) {
        ++samples;
        totalUs += us;
        maxUs = (std::max)(maxUs, us);
    }

    Value Status() const { return Value::Object({{"samples", samples}, {"total_us", totalUs}, {"max_us", maxUs}}); }
};

// Inclusive wall time, including early returns and exception unwinding. Nested
// phase timings are subsets of Tick, not additional costs to sum with it.
struct ScopedTiming {
    explicit ScopedTiming(Timing& target) : timing(target), started(Clock::now()) {}

    ~ScopedTiming() { timing.Record(std::chrono::duration<double, std::micro>(Clock::now() - started).count()); }

    Timing& timing;
    Clock::time_point started;
};

std::string Trim(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\r\n\f\v");
    if (first == std::string::npos) return {};
    return text.substr(first, text.find_last_not_of(" \t\r\n\f\v") - first + 1);
}

const char* ActionName(const Action& action) {
    switch (action.kind) {
    case ActionKind::Jump:
        return "jump";
    case ActionKind::Attack:
        return action.skillId == 0 ? "attack" : "skill";
    case ActionKind::UseItem:
        return "use_item";
    case ActionKind::Pickup:
        return "pickup";
    default:
        return "stop";
    }
}

bool SameAction(const Action& left, const Action& right) {
    return left.kind == right.kind && left.skillId == right.skillId && left.itemId == right.itemId;
}

void PushValue(lua_State* lua, const Value& value) {
    switch (value.Type()) {
    case Value::Kind::Null:
        lua_pushnil(lua);
        break;
    case Value::Kind::Boolean:
        lua_pushboolean(lua, value.Boolean());
        break;
    case Value::Kind::Number:
        lua_pushnumber(lua, value.Number());
        break;
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
            PushValue(lua, entry.second);
            lua_setfield(lua, -2, entry.first.c_str());
        }
        break;
    }
}

int ReadOnly(lua_State* lua) {
    return luaL_error(lua, "runtime observation is read-only");
}

int ReadOnlyLength(lua_State* lua) {
    lua_pushinteger(lua, static_cast<lua_Integer>(lua_rawlen(lua, lua_upvalueindex(1))));
    return 1;
}

int ReadOnlyPairs(lua_State* lua) {
    // Return the proxy as iterator state, never the mutable backing table.
    lua_pushvalue(lua, lua_upvalueindex(1));
    lua_pushcclosure(
        lua,
        [](lua_State* state) -> int {
            lua_settop(state, 2);
            lua_pushvalue(state, 2);
            if (lua_next(state, lua_upvalueindex(1)) == 0) return 0;
            return 2;
        },
        1);
    lua_pushvalue(lua, 1);
    lua_pushnil(lua);
    return 3;
}

// Replace a value table with an empty recursive proxy. No backing tables are
// exposed by pairs, metatables or raw operations in the tick environment.
void Protect(lua_State* lua) {
    if (!lua_istable(lua, -1)) return;
    const int backing = lua_absindex(lua, -1);
    lua_pushnil(lua);
    while (lua_next(lua, backing) != 0) {
        Protect(lua);
        lua_pushvalue(lua, -2);
        lua_pushvalue(lua, -2);
        lua_rawset(lua, backing);
        lua_pop(lua, 1);
    }
    lua_newtable(lua);
    lua_newtable(lua);
    lua_pushvalue(lua, backing);
    lua_setfield(lua, -2, "__index");
    lua_pushcfunction(lua, ReadOnly);
    lua_setfield(lua, -2, "__newindex");
    lua_pushvalue(lua, backing);
    lua_pushcclosure(lua, ReadOnlyLength, 1);
    lua_setfield(lua, -2, "__len");
    lua_pushvalue(lua, backing);
    lua_pushcclosure(lua, ReadOnlyPairs, 1);
    lua_setfield(lua, -2, "__pairs");
    lua_pushboolean(lua, 0);
    lua_setfield(lua, -2, "__metatable");
    lua_setmetatable(lua, -2);
    lua_remove(lua, backing);
}

void Merge(Value& target, const Value& source) {
    if (source.Type() != Value::Kind::Object) return;
    for (const auto& member : source.Members()) target[member.first] = member.second;
}

void SetFact(Value& value, const char* name, Fact fact) {
    if (fact != Fact::Unknown) value[name] = fact == Fact::True;
}
}

bool ParseTickConfig(const std::string& source, TickConfig& config, std::string& error) {
    config = {};
    error.clear();
    std::set<std::string> seen;
    bool hasTick = false;
    std::size_t position = 0;
    while (position < source.size()) {
        position = source.find_first_not_of(" \t\r\n\f\v", position);
        if (position == std::string::npos || source.compare(position, 2, "--") != 0) break;
        position += 2;
        // Lua long comments are not declarations, including nested-looking
        // short comments in their text. Match the exact bracket level.
        if (position < source.size() && source[position] == '[') {
            auto bracket = position + 1;
            while (bracket < source.size() && source[bracket] == '=') ++bracket;
            if (bracket < source.size() && source[bracket] == '[') {
                const std::string close = "]" + source.substr(position + 1, bracket - position - 1) + "]";
                const auto end = source.find(close, bracket + 1);
                if (end == std::string::npos) break; // The Lua compiler reports the unclosed comment.
                position = end + close.size();
                continue;
            }
        }
        const auto end = source.find('\n', position);
        auto line = source.substr(position, end == std::string::npos ? end : end - position);
        const auto content = line.find_first_not_of('-');
        line = content == std::string::npos ? std::string{} : Trim(line.substr(content));
        position = end == std::string::npos ? source.size() : end + 1;
        const auto split = line.find_first_of(" \t\r\f\v");
        const auto key = line.substr(0, split);
        const auto declaration = [&line](const std::string& prefix) {
            if (line.compare(0, prefix.size(), prefix) != 0) return false;
            if (line.size() == prefix.size()) return true;
            const char next = line[prefix.size()];
            return !((next >= 'a' && next <= 'z') || (next >= 'A' && next <= 'Z') || (next >= '0' && next <= '9')
                     || next == '_');
        };
        if (!declaration("@mode") && !declaration("@tick")) continue;
        if (!seen.insert(key).second) {
            error = "duplicate script declaration: " + key;
            return false;
        }
        auto value = split == std::string::npos ? std::string{} : line.substr(split + 1);
        const auto comment = value.find("--");
        if (comment != std::string::npos) value.resize(comment);
        value = Trim(value);
        if (key == "@mode") {
            if (value == "tick")
                config.mode = ScriptMode::Tick;
            else if (value == "coroutine")
                config.mode = ScriptMode::Coroutine;
            else {
                error = "invalid @mode: " + value;
                return false;
            }
        } else if (key == "@tick.gear") {
            if (value.size() != 1 || value[0] < '1' || value[0] > '4') {
                error = "@tick.gear must be 1, 2, 3 or 4";
                return false;
            }
            config.gear = static_cast<TickGear>(value[0] - '0');
            hasTick = true;
        } else if (key == "@tick.budget_ms") {
            double number = 0, fraction = 0.1;
            bool dot = false, digit = false, valid = !value.empty();
            for (const char c : value) {
                if (c == '.' && !dot) {
                    dot = true;
                    continue;
                }
                if (c < '0' || c > '9') {
                    valid = false;
                    break;
                }
                digit = true;
                if (dot) {
                    number += (c - '0') * fraction;
                    fraction *= 0.1;
                } else
                    number = number * 10 + (c - '0');
            }
            if (!valid || !digit || !std::isfinite(number) || number <= 0) {
                error = "@tick.budget_ms must be a positive finite decimal";
                return false;
            }
            config.budgetMs = number;
            hasTick = true;
        } else if (key == "@tick.overrun") {
            if (value != "abort" && value != "skip") {
                error = "@tick.overrun must be abort or skip";
                return false;
            }
            config.skipOverrun = value == "skip";
            hasTick = true;
        } else if (key == "@tick.abort_commit") {
            if (value != "true" && value != "false") {
                error = "@tick.abort_commit must be true or false";
                return false;
            }
            config.abortCommit = value == "true";
            hasTick = true;
        } else {
            error = "unknown tick declaration: " + key;
            return false;
        }
    }
    if (hasTick && config.mode != ScriptMode::Tick) {
        error = "@tick declarations require @mode tick";
        return false;
    }
    return true;
}

ScriptMode ParseScriptMode(const std::string& source, std::string& error) {
    TickConfig config;
    return ParseTickConfig(source, config, error) ? config.mode : ScriptMode::Invalid;
}

struct TickRuntime::Impl {
    struct Session {
        explicit Session(Impl& owner) : runtime(owner) {}

        ~Session() {
            if (lua != nullptr) lua_close(lua);
        }

        Impl& runtime;
        lua_State* lua = nullptr;
        int main = LUA_NOREF;
        int context = LUA_NOREF;
        int publicContext = LUA_NOREF;
        int game = LUA_NOREF;
        std::vector<std::pair<std::string, int>> domains;
        std::string id;
        std::string status = "rejected", reason, error;
        std::string finalStatus;
        TickConfig config;
        std::string instanceId;
        std::uint32_t actorId = 0;
        bool actorKnown = false;
        Clock::time_point deadline{}, started{}, previous{}, nextDue{};
        Clock::duration period{};
        bool limited = false, invoked = false, overran = false, previousOverrun = false, directionFence = false;
        bool actionFence = false;
        std::uint64_t index = 0, overruns = 0;
        double time = 0, delta = 0, lastUs = 0, maxUs = 0;
        std::uint64_t generation = 0;
        std::vector<std::string> logs;
        std::size_t logBytes = 0;

        bool Active() const { return status == "running" && finalStatus.empty(); }

        bool Due(Clock::time_point now) const {
            return Active() && (!invoked || config.gear == TickGear::Native || now >= nextDue);
        }
    };

    struct Draft {
        bool movementSet = false;
        std::string movement;
        Session* movementOwner = nullptr;
        bool actionSet = false;
        Action action;
        Session* actionOwner = nullptr;
    };

    Impl(TickAdapter& native, Now scheduleNow) : adapter(native), now(std::move(scheduleNow)) {}

    TickAdapter& adapter;
    Now now;
    std::vector<std::unique_ptr<Session>> sessions;
    State observed;
    bool sampled = false;
    std::uint64_t lastGeneration = 0;
    std::vector<std::pair<std::string, Value>> core, lazyDomains;
    // Only the current native scene is retained, including an unavailable result.
    // Transitions discard it; there is no per-map cache or background retry.
    Value scene;
    bool scenePending = true;
    Session* current = nullptr;
    Session* movementOwner = nullptr;
    Session* actionOwner = nullptr;
    std::string inputError;
    std::vector<std::pair<std::string, std::string>> cancellations;
    std::string movement;
    std::vector<std::string> held;
    Action input;
    bool inputActive = false, updating = false;
    ActionResult result;
    Draft draft;
    std::uint64_t hostTickCalls = 0, activeFrames = 0, reentrantTickCalls = 0;
    Timing tickTiming, observeTiming, refreshCoreTiming, luaTiming;

    Value ProfileValue() const {
        return Value::Object({{"scope", "runtime_lifetime"},
                              {"host_tick_calls", hostTickCalls},
                              {"active_frames", activeFrames},
                              {"reentrant_tick_calls", reentrantTickCalls},
                              {"tick", tickTiming.Status()},
                              {"observe", observeTiming.Status()},
                              {"refresh_core", refreshCoreTiming.Status()},
                              {"lua", luaTiming.Status()}});
    }

    // Native I/O may pump a host frame. Defer cancellation until no Lua or
    // native submission is on the stack, and never recursively invoke main.
    struct UpdateScope {
        explicit UpdateScope(Impl& owner) : runtime(owner) { runtime.updating = true; }

        ~UpdateScope() {
            runtime.DrainCancellations();
            runtime.updating = false;
        }

        Impl& runtime;
    };

    void DrainCancellations() {
        while (!cancellations.empty()) {
            auto requests = std::move(cancellations);
            cancellations.clear();
            for (const auto& request : requests)
                for (auto& session : sessions)
                    if (session->id == request.first) {
                        Finish(*session, "cancelled", request.second);
                        break;
                    }
        }
    }

    static Session& Self(lua_State* lua) { return **static_cast<Session**>(lua_getextraspace(lua)); }

    static void Budget(lua_State* lua, lua_Debug*) {
        auto& session = Self(lua);
        if (std::chrono::duration<double, std::milli>(Clock::now() - session.started).count()
            >= session.config.budgetMs) {
            session.overran = true;
            luaL_error(lua, "tick execution budget exceeded");
        }
    }

    static Session& Invocation(lua_State* lua) {
        auto& session = Self(lua);
        if (session.runtime.current != &session || !session.Active())
            luaL_error(lua, "player input is only available inside main(context)");
        return session;
    }

    static int Reply(lua_State* lua, bool ok, const char* reason = nullptr) {
        lua_pushboolean(lua, ok);
        if (reason != nullptr)
            lua_pushstring(lua, reason);
        else
            lua_pushnil(lua);
        return 2;
    }

    static int Move(lua_State* lua) {
        auto& session = Invocation(lua);
        if (lua_gettop(lua) > 1) return luaL_error(lua, "move accepts one direction or nil");
        const char* direction = "";
        if (!lua_isnoneornil(lua, 1)) {
            luaL_checktype(lua, 1, LUA_TSTRING);
            direction = lua_tostring(lua, 1);
            if (std::strlen(direction) != lua_rawlen(lua, 1)
                || (std::strcmp(direction, "left") != 0 && std::strcmp(direction, "right") != 0
                    && std::strcmp(direction, "up") != 0 && std::strcmp(direction, "down") != 0))
                return luaL_error(lua, "undefined movement direction");
        }
        auto& target = session.runtime.draft;
        target.movementSet = true;
        target.movement = direction;
        target.movementOwner = &session;
        return Reply(lua, true);
    }

    static int Submit(lua_State* lua, ActionKind kind, bool skill = false) {
        auto& session = Invocation(lua);
        const bool idRequired = skill || kind == ActionKind::UseItem;
        if (lua_gettop(lua) != (idRequired ? 1 : 0)) return luaL_error(lua, "invalid player action arguments");
        if (skill && lua_isnil(lua, 1)) {
            auto& target = session.runtime.draft;
            target.actionSet = true;
            target.action = {};
            target.actionOwner = nullptr;
            return Reply(lua, true);
        }
        lua_Integer id = 0;
        if (idRequired) {
            if (!lua_isinteger(lua, 1)) return luaL_error(lua, "action id must be an integer");
            id = lua_tointeger(lua, 1);
            if (id < 1 || id > 2147483647) return luaL_error(lua, "action id must be between 1 and 2147483647");
        }
        auto& runtime = session.runtime;
        if (!runtime.adapter.Supports(kind) || (skill && !runtime.adapter.SupportsSkill()))
            return Reply(lua, false, "unsupported");
        Action requested;
        requested.kind = kind;
        requested.skillId = skill ? static_cast<std::uint32_t>(id) : 0;
        requested.itemId = kind == ActionKind::UseItem ? static_cast<std::uint32_t>(id) : 0;
        requested.sessionId = session.id;
        runtime.draft.actionSet = true;
        runtime.draft.action = requested;
        runtime.draft.actionOwner = &session;
        return Reply(lua, true);
    }

    static int Jump(lua_State* lua) { return Submit(lua, ActionKind::Jump); }

    static int Attack(lua_State* lua) { return Submit(lua, ActionKind::Attack); }

    static int Skill(lua_State* lua) { return Submit(lua, ActionKind::Attack, true); }

    static int UseItem(lua_State* lua) { return Submit(lua, ActionKind::UseItem); }

    static int Pickup(lua_State* lua) { return Submit(lua, ActionKind::Pickup); }

    static int Stop(lua_State* lua) {
        auto& session = Invocation(lua);
        if (lua_gettop(lua) != 0) return luaL_error(lua, "stop accepts no arguments");
        auto& target = session.runtime.draft;
        target.movementSet = target.actionSet = true;
        target.movement.clear();
        target.movementOwner = &session;
        target.action = {};
        target.actionOwner = nullptr;
        return Reply(lua, true);
    }

    Value Player() const {
        const auto* active = adapter.ActiveAction();
        const auto* desired = current != nullptr && draft.actionSet
                                  ? (draft.action.kind == ActionKind::Stop ? nullptr : &draft.action)
                                  : (inputActive ? &input : nullptr);
        Value keys = Value::Array();
        for (const auto& key : held) keys.Add(key);
        if (inputActive) keys.Add(ActionName(input));
        const auto idle = current != nullptr ? observed.actionIdle : adapter.Observe().actionIdle;
        const bool nativeBusy = active != nullptr || idle == Fact::False;
        const Value busy = nativeBusy ? Value(true) : idle == Fact::True ? Value(false) : Value{};
        Value value = Value::Object({{"moving", movement.empty() ? Value{} : Value(movement)},
                                     {"input_action", desired != nullptr ? Value(ActionName(*desired)) : Value{}},
                                     {"action", active != nullptr ? Value(ActionName(*active)) : Value{}},
                                     {"phase", nativeBusy           ? "running"
                                               : idle == Fact::True ? "idle"
                                                                    : "unknown"},
                                     {"busy", busy},
                                     {"held", keys},
                                     {"reason", inputError.empty() ? result.reason : inputError},
                                     {"effect", result.effect},
                                     {"dispatched", result.dispatched}});
        if (desired != nullptr && desired->skillId != 0) value["input_skill_id"] = desired->skillId;
        if (desired != nullptr && desired->itemId != 0) value["input_item_id"] = desired->itemId;
        if (active != nullptr && active->skillId != 0) value["skill_id"] = active->skillId;
        if (active != nullptr && active->itemId != 0) value["item_id"] = active->itemId;
        return value;
    }

    static int PlayerStatus(lua_State* lua) {
        PushValue(lua, Self(lua).runtime.Player());
        Protect(lua);
        return 1;
    }

    static int Log(lua_State* lua) {
        auto& session = Self(lua);
        luaL_checktype(lua, 1, LUA_TSTRING);
        std::size_t length = 0;
        const auto* text = lua_tolstring(lua, 1, &length);
        if (length > 4096 || session.logBytes + length > 65536)
            return luaL_error(lua, "script log limit exceeded for this tick");
        session.logs.emplace_back(text, length);
        session.logBytes += length;
        return 0;
    }

    Value Domain(const std::string& name) {
        auto observation = adapter.ObserveDomain(name);
        Value value = Value::Object();
        Merge(value, observation.data);
        value["status"] = observation.status;
        if (!observation.error.empty()) value["error"] = observation.error;
        if (name == "character") {
            if (observed.characterKnown) {
                value["status"] = "ok";
                value["id"] = observed.character.id;
                value["name"] = observed.character.name;
                static const char* names[]{"level",          "job",          "strength",  "dexterity", "intelligence",
                                           "luck",           "hp",           "max_hp",    "mp",        "max_mp",
                                           "ability_points", "skill_points", "experience"};
                static const char* shortNames[]{"level",  "job", "str",    "dex", "int", "luk", "hp",
                                                "max_hp", "mp",  "max_mp", "ap",  "sp",  "exp"};
                for (std::size_t index = 0; index < observed.character.values.size(); ++index) {
                    if (!observed.character.known[index]) continue;
                    value[names[index]] = observed.character.values[index];
                    value[shortNames[index]] = observed.character.values[index];
                }
            }
            Merge(value, observed.character.MotionDocument());
            value["movement"] = observed.character.movement.Document();
            if (observed.characterUpdatesKnown) value["native_updates"] = observed.characterUpdates;
            SetFact(value, "on_ground", observed.onGround);
            SetFact(value, "attacking", observed.attacking);
            SetFact(value, "action_idle", observed.actionIdle);
        } else if (name == "world") {
            value["status"] = "ok";
            value["instance_id"] = observed.instanceId;
            value["scene_generation"] = observed.sceneGeneration;
            value["ready"] = observed.ready;
            value["in_game"] = observed.inGame;
            if (observed.mapKnown) value["map_id"] = observed.mapId;
            if (observed.positionKnown) {
                value["x"] = observed.x;
                value["y"] = observed.y;
                value["position"] = Value::Object({{"x", observed.x}, {"y", observed.y}});
            }
            if (observed.facingKnown) value["facing"] = observed.facingLeft ? "Left" : "Right";
            SetFact(value, "settled", observed.settled);
            SetFact(value, "dead", observed.dead);
            SetFact(value, "revive_requestable", observed.reviveRequestable);
        } else if (name == "scene") {
            if (observed.mapKnown) value["map_id"] = observed.mapId;
            if (observed.monstersKnown) {
                value["monsters"] = Value::Array();
                for (const auto& monster : observed.monsters) {
                    auto item = monster.MotionDocument();
                    item["object_id"] = monster.objectId;
                    item["active"] = monster.active;
                    if (monster.templateKnown) item["template_id"] = monster.templateId;
                    if (!monster.name.empty()) item["name"] = monster.name;
                    if (monster.hpSequence != 0) {
                        item["hp_percent"] = monster.hpPercent;
                        item["hp_sequence"] = monster.hpSequence;
                        item["hp_source"] = "server_mob_hp";
                    }
                    value["monsters"].Add(item);
                }
            }
            if (observed.dropsKnown) {
                value["drops"] = Value::Array();
                for (const auto& drop : observed.drops) {
                    auto item = drop.MotionDocument();
                    item["object_id"] = drop.objectId;
                    if (drop.itemKnown) item["item_id"] = drop.itemId;
                    if (drop.moneyKnown) item["money"] = drop.money;
                    SetFact(item, "landed", drop.landed);
                    value["drops"].Add(item);
                }
            }
            if (observed.playersKnown) {
                value["players"] = Value::Array();
                for (const auto& player : observed.players) {
                    auto item = player.MotionDocument();
                    item["reference"] = player.reference;
                    if (player.characterIdKnown) item["character_id"] = player.characterId;
                    if (!player.name.empty()) item["name"] = player.name;
                    if (player.levelKnown) item["level"] = player.level;
                    if (player.facingKnown) item["facing"] = player.facingLeft ? "Left" : "Right";
                    value["players"].Add(item);
                }
                SetFact(value, "players_complete", observed.playersComplete);
            }
            // Native NPC rows also carry interaction references and backend facts.
            // Both adapters serialize their typed movable objects here; preserve
            // those complete rows, using the snapshot only as a native-domain fallback.
            if (observed.npcsKnown && value["npcs"].Type() != Value::Kind::Array) {
                value["npcs"] = Value::Array();
                for (const auto& npc : observed.npcs) {
                    auto item = npc.MotionDocument();
                    item["object_id"] = npc.objectId;
                    item["template_id"] = npc.templateId;
                    if (!npc.name.empty()) item["name"] = npc.name;
                    value["npcs"].Add(item);
                }
            }
            if (observed.projectilesKnown) {
                value["projectiles"] = Value::Array();
                for (const auto& projectile : observed.projectiles)
                    value["projectiles"].Add(projectile.MotionDocument());
                SetFact(value, "projectiles_complete", observed.projectilesComplete);
            }
            if (observed.monstersKnown || observed.playersKnown || observed.dropsKnown || observed.npcsKnown
                || observed.projectilesKnown)
                value["status"] = "ok";
        }
        return value;
    }

    static int GameIndex(lua_State* lua) {
        auto& session = Self(lua);
        lua_pushvalue(lua, 2);
        lua_rawget(lua, lua_upvalueindex(1));
        if (!lua_isnil(lua, -1)) return 1;
        lua_pop(lua, 1);
        if (lua_type(lua, 2) != LUA_TSTRING) {
            lua_pushnil(lua);
            return 1;
        }
        const auto* key = lua_tostring(lua, 2);
        static const char* domains[]{"character", "world", "scene", "inventory", "quests",      "chat",
                                     "dialog",    "shop",  "ui",    "hotkeys",   "interaction", "notifications"};
        if (std::none_of(std::begin(domains), std::end(domains),
                         [key](const char* name) { return std::string(name) == key; })) {
            lua_pushnil(lua);
            return 1;
        }
        for (const auto& cached : session.domains)
            if (cached.first == key) {
                lua_rawgeti(lua, LUA_REGISTRYINDEX, cached.second);
                return 1;
            }
        const auto& values = session.runtime.core;
        const auto cached =
            std::find_if(values.begin(), values.end(), [key](const auto& entry) { return entry.first == key; });
        if (cached != values.end())
            PushValue(lua, cached->second);
        else {
            auto& lazy = session.runtime.lazyDomains;
            auto sample =
                std::find_if(lazy.begin(), lazy.end(), [key](const auto& entry) { return entry.first == key; });
            if (sample == lazy.end()) {
                lazy.emplace_back(key, session.runtime.Domain(key));
                sample = lazy.end() - 1;
            }
            PushValue(lua, sample->second);
        }
        Protect(lua);
        lua_pushvalue(lua, -1);
        session.domains.emplace_back(key, luaL_ref(lua, LUA_REGISTRYINDEX));
        return 1;
    }

    void Open(Session& session) {
        auto* lua = session.lua;
        *static_cast<Session**>(lua_getextraspace(lua)) = &session;
        // Standard libraries are provided as-is; the runtime owns scheduling, budgets
        // and native I/O only, with no capability trimming for its own scripts.
        luaL_openlibs(lua);
        static const luaL_Reg player[]{{"move", Move},   {"jump", Jump},           {"attack", Attack},
                                       {"skill", Skill}, {"use_item", UseItem},    {"pickup", Pickup},
                                       {"stop", Stop},   {"status", PlayerStatus}, {nullptr, nullptr}};
        lua_newtable(lua); // backing of game proxy
        luaL_newlib(lua, player);
        Protect(lua);
        lua_setfield(lua, -2, "player");
        lua_pushcfunction(lua, Log);
        lua_setfield(lua, -2, "log");
        lua_newtable(lua);
        lua_newtable(lua);
        lua_pushvalue(lua, -3);
        lua_pushcclosure(lua, GameIndex, 1);
        lua_setfield(lua, -2, "__index");
        lua_pushcfunction(lua, ReadOnly);
        lua_setfield(lua, -2, "__newindex");
        lua_pushboolean(lua, 0);
        lua_setfield(lua, -2, "__metatable");
        lua_setmetatable(lua, -2);
        lua_remove(lua, -2);
        lua_pushvalue(lua, -1);
        session.game = luaL_ref(lua, LUA_REGISTRYINDEX);
        lua_setglobal(lua, "game");
        lua_sethook(lua, Budget, LUA_MASKCOUNT, 1000);
    }

    bool SameScene() {
        return scene.Type() == Value::Kind::Object && scene["instance_id"].Text() == observed.instanceId
               && scene["scene_generation"].Number() == observed.sceneGeneration
               && (scene["character_id"].Type() == Value::Kind::Number) == observed.characterKnown
               && (!observed.characterKnown || scene["character_id"].Number() == observed.character.id)
               && (scene["map_id"].Type() == Value::Kind::Number) == observed.mapKnown
               && (!observed.mapKnown || scene["map_id"].Number() == observed.mapId);
    }

    void InstallScene(Session& session) {
        if (session.lua == nullptr || session.context == LUA_NOREF) return;
        auto* lua = session.lua;
        lua_rawgeti(lua, LUA_REGISTRYINDEX, session.context);
        PushValue(lua, scene);
        Protect(lua);
        lua_setfield(lua, -2, "scene");
        lua_pop(lua, 1);
    }

    void RefreshScene(bool readTerrain) {
        Value terrain = Value::Object({{"status", "unavailable"}, {"error", "scene_transition"}});
        scenePending = !readTerrain;
        if (readTerrain) {
            if (observed.ready && observed.mapKnown && observed.characterKnown) {
                auto observation = adapter.ObserveDomain("terrain");
                // Geometry is validated at the resource boundary. Here only its
                // map identity may authorize attaching it to this native scene.
                if (observation.status == "ok") {
                    const auto& map = observation.data["map_id"];
                    if (map.Type() == Value::Kind::Number && map.Number() == observed.mapId)
                        terrain = Value::Object({{"status", "available"},
                                                 {"source", observation.data["source"]},
                                                 {"footholds", observation.data["footholds"]},
                                                 {"ropes", observation.data["ropes"]}});
                    else
                        terrain = Value::Object({{"status", "unavailable"}, {"error", "terrain_map_mismatch"}});
                } else {
                    terrain = Value::Object({{"status", observation.status}});
                    for (const auto& entry : observation.data.Members())
                        if (entry.first == "source" || entry.first == "message" || entry.first == "details"
                            || entry.first == "error")
                            terrain[entry.first] = entry.second;
                    if (!observation.error.empty()) terrain["error"] = observation.error;
                }
            } else
                terrain["error"] = "scene_identity_unavailable";
        }
        scene = Value::Object({{"instance_id", observed.instanceId},
                               {"scene_generation", observed.sceneGeneration},
                               {"terrain", std::move(terrain)}});
        if (observed.characterKnown) scene["character_id"] = observed.character.id;
        if (observed.mapKnown) scene["map_id"] = observed.mapId;
        // Replace whole read-only snapshots, never relabel old geometry. Even a
        // non-due session loses its old available scene as soon as it changes.
        for (auto& session : sessions) InstallScene(*session);
    }

    bool Context(Session& session, std::string& error) {
        auto* lua = session.lua;
        // The chunk result is the only wrapper protocol. Global main gets a new
        // empty context; user globals cannot smuggle stale CLI identity into it.
        if (lua_istable(lua, -1)) {
            lua_getfield(lua, -1, "main");
            if (!lua_isfunction(lua, -1)) {
                error = "tick chunk must return a main function";
                return false;
            }
            session.main = luaL_ref(lua, LUA_REGISTRYINDEX);
            lua_getfield(lua, -1, "context");
            if (!lua_istable(lua, -1)) {
                error = "tick chunk must return a context table";
                return false;
            }
        } else {
            lua_getglobal(lua, "main");
            if (!lua_isfunction(lua, -1)) {
                error = "tick script must define main(context)";
                return false;
            }
            session.main = luaL_ref(lua, LUA_REGISTRYINDEX);
            lua_newtable(lua);
        }
        const int context = lua_absindex(lua, -1);
        if (lua_getmetatable(lua, context)) {
            error = "tick context must be a plain table";
            return false;
        }
        lua_getfield(lua, context, "scene");
        if (!lua_isnil(lua, -1)) {
            if (!lua_istable(lua, -1)) {
                error = "context.scene must be a table";
                return false;
            }
            const int scene = lua_absindex(lua, -1);
            lua_getfield(lua, scene, "instance_id");
            if (!lua_isnil(lua, -1)
                && (lua_type(lua, -1) != LUA_TSTRING || observed.instanceId.size() != lua_rawlen(lua, -1)
                    || observed.instanceId != lua_tostring(lua, -1))) {
                error = "strategy_context_changed: instance_id";
                return false;
            }
            lua_pop(lua, 1);
            const std::pair<const char*, std::pair<bool, std::uint64_t>> anchors[]{
                {"character_id", {observed.characterKnown, observed.character.id}},
                {"map_id", {observed.mapKnown, observed.mapId}},
                {"scene_generation", {true, observed.sceneGeneration}}};
            for (const auto& anchor : anchors) {
                lua_getfield(lua, scene, anchor.first);
                if (!lua_isnil(lua, -1)
                    && (!anchor.second.first || !lua_isinteger(lua, -1) || lua_tointeger(lua, -1) < 0
                        || static_cast<std::uint64_t>(lua_tointeger(lua, -1)) != anchor.second.second)) {
                    error = std::string("strategy_context_changed: ") + anchor.first;
                    return false;
                }
                lua_pop(lua, 1);
            }
        }
        lua_pop(lua, 1);
        lua_newtable(lua);
        lua_setfield(lua, context, "state");
        lua_rawgeti(lua, LUA_REGISTRYINDEX, session.game);
        lua_setfield(lua, context, "game");
        // Keep runtime-owned game/tick/scene slots behind a context proxy too. Script
        // state and caller-supplied payload remain writable across ticks.
        lua_newtable(lua);
        lua_newtable(lua);
        lua_pushvalue(lua, context);
        lua_setfield(lua, -2, "__index");
        lua_pushvalue(lua, context);
        lua_pushcclosure(
            lua,
            [](lua_State* state) -> int {
                if (lua_type(state, 2) == LUA_TSTRING) {
                    const std::string key = lua_tostring(state, 2);
                    if (key == "game" || key == "tick" || key == "scene")
                        return luaL_error(state, "runtime context slot is read-only");
                }
                lua_pushvalue(state, 2);
                lua_pushvalue(state, 3);
                lua_rawset(state, lua_upvalueindex(1));
                return 0;
            },
            1);
        lua_setfield(lua, -2, "__newindex");
        lua_pushboolean(lua, 0);
        lua_setfield(lua, -2, "__metatable");
        lua_setmetatable(lua, -2);
        session.publicContext = luaL_ref(lua, LUA_REGISTRYINDEX);
        lua_pushvalue(lua, context);
        session.context = luaL_ref(lua, LUA_REGISTRYINDEX);
        // Caller anchors above are checked before native scene replacement.
        // Initial terrain is sampled only on a stable, due host frame.
        if (SameScene())
            InstallScene(session);
        else
            RefreshScene(false);
        lua_settop(lua, 0);
        return true;
    }

    void ClearDomains(Session& session) {
        for (const auto& entry : session.domains) luaL_unref(session.lua, LUA_REGISTRYINDEX, entry.second);
        session.domains.clear();
    }

    void RefreshCore() {
        core.clear();
        lazyDomains.clear();
        for (const char* name : {"character", "world", "scene"}) core.emplace_back(name, Domain(name));
    }

    std::vector<std::string> WantedKeys() const {
        std::vector<std::string> wanted;
        if (!movement.empty()) wanted.push_back(movement);
        return wanted;
    }

    void SyncHeld() {
        const auto wanted = WantedKeys();
        if (wanted == held) return;
        std::string error;
        if (adapter.SetHeldKeys(wanted, error))
            held = wanted;
        else {
            result.reason = error.empty() ? "native_input_rejected" : error;
            result.effect = "unknown";
            // A native rejection is an action-level fact, not a Lua error.
        }
    }

    void SetInput(const Action& requested, Session* owner) {
        if (inputActive == (requested.kind != ActionKind::Stop) && SameAction(input, requested) && actionOwner == owner)
            return;
        auto* previousOwner = actionOwner;
        std::string error;
        if (adapter.SetActionIntent(requested, error)) {
            input = requested;
            inputActive = requested.kind != ActionKind::Stop;
            actionOwner = inputActive ? owner : nullptr;
            inputError.clear();
        } else {
            // A rejected replacement must not leave an obsolete input held.
            adapter.ReleaseAction();
            input = {};
            inputActive = false;
            actionOwner = nullptr;
            inputError = error.empty() ? "native_input_rejected" : error;
        }
        if (previousOwner != nullptr) previousOwner->actionFence = !adapter.ActionIntentSettled();
        result = adapter.Result();
    }

    void Poll() {
        result = adapter.Result();
        if (adapter.HeldKeysSettled() && held == WantedKeys())
            for (auto& session : sessions) session->directionFence = false;
        if (adapter.ActionIntentSettled())
            for (auto& session : sessions) session->actionFence = false;
        for (auto& session : sessions) {
            if (session->finalStatus.empty()) continue;
            if (actionOwner == session.get() || movementOwner == session.get() || session->directionFence
                || session->actionFence)
                continue;
            session->status = session->finalStatus;
            session->finalStatus.clear();
            if (session->lua != nullptr) {
                lua_close(session->lua);
                session->lua = nullptr;
            }
            session->domains.clear();
            session->main = session->context = session->publicContext = session->game = LUA_NOREF;
        }
    }

    void Commit() {
        if (draft.movementSet) {
            if (movementOwner != nullptr && movement != draft.movement) movementOwner->directionFence = true;
            movement = draft.movement;
            movementOwner = movement.empty() ? nullptr : draft.movementOwner;
        }
        if (draft.actionSet) SetInput(draft.action, draft.actionOwner);
        SyncHeld();
        draft = {};
    }

    void Finish(Session& session, const std::string& status, const std::string& reason) {
        if (session.status != "running" || !session.finalStatus.empty()) return;
        session.reason = reason;
        session.finalStatus = status;
        if (movementOwner == &session) {
            movement.clear();
            movementOwner = nullptr;
            session.directionFence = !held.empty() || !adapter.HeldKeysSettled();
        }
        if (actionOwner == &session) SetInput({}, nullptr);
        SyncHeld();
        Poll();
    }

    Value StatusValue(const Session& session) const {
        const bool owned =
            actionOwner == &session || movementOwner == &session || session.directionFence || session.actionFence;
        return Value::Object({{"id", session.id},
                              {"status", session.status},
                              {"reason", session.reason.empty() ? Value{} : Value(session.reason)},
                              {"error", session.error.empty() ? Value{} : Value(session.error)},
                              {"mode", "tick"},
                              {"resumes", session.index},
                              {"budget_yields", session.overruns},
                              {"last_resume_us", session.lastUs},
                              {"max_resume_us", session.maxUs},
                              {"tasks", Value::Array()},
                              {"control", Value::Object({{"owner", movementOwner != nullptr ? movementOwner->id : ""},
                                                         {"pending", ""},
                                                         {"from", ""},
                                                         {"to", ""},
                                                         {"reason", ""}})},
                              {"control_released", !owned},
                              {"tick", Value::Object({{"index", session.index},
                                                      {"gear", static_cast<int>(session.config.gear)},
                                                      {"time", session.time},
                                                      {"delta", session.delta},
                                                      {"scene_generation", session.generation},
                                                      {"overrun", session.previousOverrun},
                                                      {"overruns", session.overruns},
                                                      {"budget_ms", session.config.budgetMs},
                                                      {"overrun_policy", session.config.skipOverrun ? "skip" : "abort"},
                                                      {"abort_commit", session.config.abortCommit},
                                                      {"profile", ProfileValue()}})},
                              {"player", Player()}});
    }
};

TickRuntime::TickRuntime(TickAdapter& adapter, Now now) : impl(new Impl(adapter, std::move(now))) {}

TickRuntime::~TickRuntime() {
    CancelAll("runtime_closed");
}

bool TickRuntime::Start(const std::string& scriptId, const std::string& source, std::uint32_t limitMs,
                        std::string& error) {
    auto& runtime = *impl;
    error.clear();
    if (runtime.updating) {
        error = "tick_runtime_busy";
        return false;
    }
    Impl::UpdateScope scope(runtime);
    if (scriptId.empty()) {
        error = "script_id_required";
        return false;
    }
    for (const auto& session : runtime.sessions)
        if (session->id == scriptId) {
            error = "script_session_exists";
            return false;
        }
    auto created = std::unique_ptr<Impl::Session>(new Impl::Session(runtime));
    auto& session = *created;
    session.id = scriptId;
    runtime.sessions.push_back(std::move(created));
    auto reject = [&](const std::string& reason) {
        session.reason = reason;
        session.error = error;
        if (session.lua != nullptr) {
            lua_close(session.lua);
            session.lua = nullptr;
        }
        return false;
    };
    if (!ParseTickConfig(source, session.config, error)) return reject("script_load_error");
    if (session.config.mode != ScriptMode::Tick) {
        error = "tick runtime requires @mode tick";
        return reject("script_load_error");
    }
    runtime.observed = runtime.adapter.Observe();
    if (!runtime.observed.ready || !runtime.observed.inGame) {
        error = "not_in_game";
        return reject("not_in_game");
    }
    if (!runtime.sampled) {
        runtime.lastGeneration = runtime.observed.sceneGeneration;
        runtime.sampled = true;
    }
    session.instanceId = runtime.observed.instanceId;
    session.actorId = runtime.observed.character.id;
    session.actorKnown = runtime.observed.characterKnown;
    session.generation = runtime.observed.sceneGeneration;
    session.limited = limitMs != 0;
    if (session.limited) session.deadline = runtime.now() + std::chrono::milliseconds(limitMs);
    if (session.config.gear != TickGear::Native) {
        static const int rates[]{10, 20, 30};
        session.period = std::chrono::duration_cast<Clock::duration>(
            std::chrono::duration<double>(1.0 / rates[static_cast<int>(session.config.gear) - 1]));
    }
    session.lua = luaL_newstate();
    if (session.lua == nullptr) {
        error = "lua_state_unavailable";
        return reject("lua_state_unavailable");
    }
    runtime.Open(session);
    runtime.RefreshCore();
    if (luaL_loadbufferx(session.lua, source.data(), source.size(), scriptId.c_str(), "t") != LUA_OK) {
        const auto* message = lua_tostring(session.lua, -1);
        error = message != nullptr ? message : "Lua load failed";
        return reject("script_load_error");
    }
    session.started = Clock::now();
    const int loaded = lua_pcall(session.lua, 0, 1, 0);
    if (session.overran
        || std::chrono::duration<double, std::milli>(Clock::now() - session.started).count()
               >= session.config.budgetMs) {
        error = "tick execution budget exceeded during initialization";
        return reject("tick_overrun");
    }
    if (loaded != LUA_OK) {
        const auto* message = lua_tostring(session.lua, -1);
        error = message != nullptr ? message : "Lua initialization failed";
        return reject("script_error");
    }
    if (!runtime.Context(session, error)) return reject("script_load_error");
    if (!session.logs.empty() && !runtime.adapter.Logs(session.id, session.logs)) {
        error = "script_log_write_failed";
        return reject("script_log_write_failed");
    }
    session.logs.clear();
    session.logBytes = 0;
    session.status = "running";
    return true;
}

void TickRuntime::Tick(bool sceneChanged) {
    auto& runtime = *impl;
    ScopedTiming tickTiming(runtime.tickTiming);
    ++runtime.hostTickCalls;
    if (runtime.updating) {
        ++runtime.reentrantTickCalls;
        return;
    }
    if (!Running()) return;
    ++runtime.activeFrames;
    Impl::UpdateScope scope(runtime);
    {
        ScopedTiming observeTiming(runtime.observeTiming);
        runtime.observed = runtime.adapter.Observe();
    }
    const bool transition = sceneChanged || !runtime.observed.ready
                            || (runtime.sampled && runtime.lastGeneration != runtime.observed.sceneGeneration);
    runtime.sampled = true;
    runtime.lastGeneration = runtime.observed.sceneGeneration;
    runtime.Poll();
    const auto now = runtime.now();
    // A scene-transition frame still handles cancellation, deadlines and native
    // completion; only Lua invocation is deferred until the next stable frame.
    for (auto& session : runtime.sessions) {
        if (session->status != "running") continue;
        if (runtime.observed.instanceId != session->instanceId)
            runtime.Finish(*session, "cancelled", "instance_changed");
        else if (session->actorKnown && runtime.observed.characterKnown
                 && runtime.observed.character.id != session->actorId)
            runtime.Finish(*session, "cancelled", "character_changed");
        else if (!runtime.observed.inGame)
            runtime.Finish(*session, "cancelled", "left_game");
        else if (session->limited && now >= session->deadline)
            runtime.Finish(*session, "cancelled", "time_limit");
    }
    if (transition) {
        // Never replay an old scene's intent after the host has independently
        // released its input. A stable subsequent main call must choose again.
        if (runtime.movementOwner != nullptr) runtime.movementOwner->directionFence = true;
        runtime.movement.clear();
        runtime.movementOwner = nullptr;
        runtime.SetInput({}, nullptr);
        std::string error;
        if (runtime.adapter.SetHeldKeys({}, error))
            runtime.held.clear();
        else
            runtime.result.reason = error;
        runtime.RefreshScene(false);
    }
    runtime.draft = {};

    struct Ending {
        Impl::Session* session;
        std::string status, reason;
    };

    std::vector<Ending> endings;
    if (!transition) {
        const bool hasDue = std::any_of(runtime.sessions.begin(), runtime.sessions.end(),
                                        [now](const auto& session) { return session->Due(now); });
        if (hasDue) {
            ScopedTiming refreshCoreTiming(runtime.refreshCoreTiming);
            if (runtime.scenePending || !runtime.SameScene()) runtime.RefreshScene(true);
            runtime.RefreshCore();
        }
        for (auto& owned : runtime.sessions) {
            auto& session = *owned;
            // Keep the due set fixed at frame start, even if another main is slow.
            if (!session.Due(now)) continue;
            runtime.ClearDomains(session);
            const auto callAt = runtime.now();
            if (!session.invoked) session.nextDue = callAt;
            session.delta = session.invoked ? std::chrono::duration<double>(callAt - session.previous).count() : 0;
            session.previous = callAt;
            session.invoked = true;
            session.time = std::chrono::duration<double>(callAt.time_since_epoch()).count();
            session.generation = runtime.observed.sceneGeneration;
            ++session.index;
            auto* lua = session.lua;
            lua_rawgeti(lua, LUA_REGISTRYINDEX, session.context);
            const int backing = lua_absindex(lua, -1);
            PushValue(lua, Value::Object({{"index", session.index},
                                          {"gear", static_cast<int>(session.config.gear)},
                                          {"time", session.time},
                                          {"delta", session.delta},
                                          {"scene_generation", session.generation},
                                          {"overrun", session.previousOverrun}}));
            Protect(lua);
            lua_setfield(lua, backing, "tick");
            lua_rawgeti(lua, LUA_REGISTRYINDEX, session.main);
            lua_rawgeti(lua, LUA_REGISTRYINDEX, session.publicContext);
            const auto before = runtime.draft;
            runtime.current = &session;
            session.overran = false;
            session.started = Clock::now();
            const int called = lua_pcall(lua, 1, 1, 0);
            session.lastUs = std::chrono::duration<double, std::micro>(Clock::now() - session.started).count();
            runtime.luaTiming.Record(session.lastUs);
            session.maxUs = (std::max)(session.maxUs, session.lastUs);
            session.overran = session.overran || session.lastUs >= session.config.budgetMs * 1000;
            runtime.current = nullptr;
            bool done = false;
            if (called == LUA_OK) {
                if (lua_type(lua, -1) == LUA_TSTRING)
                    done = std::string(lua_tostring(lua, -1)) == "done";
                else if (lua_istable(lua, -1)) {
                    lua_getfield(lua, -1, "done");
                    done = lua_toboolean(lua, -1) != 0;
                    lua_pop(lua, 1);
                }
            } else if (!session.overran) {
                const auto* message = lua_tostring(lua, -1);
                session.error = message != nullptr ? message : "Lua runtime error";
                runtime.draft = before;
                endings.push_back({&session, "cancelled", "script_error"});
            }
            if (session.overran) {
                ++session.overruns;
                if (!session.config.skipOverrun) {
                    if (!session.config.abortCommit) runtime.draft = before;
                    session.error = "tick execution budget exceeded";
                    endings.push_back({&session, "cancelled", "tick_overrun"});
                }
            } else if (done && called == LUA_OK)
                endings.push_back({&session, "completed", "script_returned"});
            session.previousOverrun = session.overran;
            lua_settop(lua, 0);
            if (!session.logs.empty() && !runtime.adapter.Logs(session.id, session.logs))
                endings.push_back({&session, "cancelled", "script_log_write_failed"});
            session.logs.clear();
            session.logBytes = 0;
            if (session.config.gear != TickGear::Native) {
                // Preserve the absolute phase; discard missed intervals, including
                // time spent inside this main, rather than bursting to catch up.
                const auto after = runtime.now();
                session.nextDue += session.period * ((after - session.nextDue) / session.period + 1);
            }
        }
    }
    runtime.Commit();
    runtime.DrainCancellations();
    for (const auto& ending : endings) runtime.Finish(*ending.session, ending.status, ending.reason);
    runtime.Poll();
}

void TickRuntime::Cancel(const std::string& scriptId, const std::string& reason) {
    impl->cancellations.emplace_back(scriptId, reason);
    if (!impl->updating) {
        Impl::UpdateScope scope(*impl);
    }
}

void TickRuntime::CancelAll(const std::string& reason) {
    for (const auto& session : impl->sessions)
        if (session->status == "running") impl->cancellations.emplace_back(session->id, reason);
    if (!impl->updating) {
        Impl::UpdateScope scope(*impl);
    }
}

bool TickRuntime::Running() const {
    return std::any_of(impl->sessions.begin(), impl->sessions.end(),
                       [](const auto& session) { return session->status == "running"; });
}

Value TickRuntime::CurrentStatus(const std::string& scriptId) const {
    for (const auto& session : impl->sessions)
        if (session->id == scriptId) return impl->StatusValue(*session);
    return {};
}

Value TickRuntime::Statuses() const {
    auto values = Value::Array();
    for (const auto& session : impl->sessions) values.Add(impl->StatusValue(*session));
    return values;
}

Value TickRuntime::Profile() const {
    return impl->ProfileValue();
}

}
