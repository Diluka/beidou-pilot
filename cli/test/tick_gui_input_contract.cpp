// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeKeyUnion.h"
#include "NativeTickInput.h"
#include "TickRuntime.h"

#include <cstdlib>
#include <functional>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace {
using BeiDouBridge::NativeKeyInput;
using BeiDouBridge::NativeKeyUnion;
using BeiDouBridge::NativeTickInput;
constexpr unsigned Left = 37, Right = 39, Attack = 17;
constexpr std::uint32_t User = 7;

void Check(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

NativeKeyInput::Mask Keys(std::initializer_list<unsigned> keys) {
    NativeKeyInput::Mask mask{};
    for (auto key : keys) mask[key] = true;
    return mask;
}

struct Boundary {
    NativeKeyInput old;
    NativeTickInput tick;
    NativeKeyUnion keys{&old, &tick.movement, &tick.action};
    std::uint64_t updates = 0;
    std::vector<std::pair<unsigned, bool>> events;
    std::function<bool(unsigned, bool)> onSend;

    NativeKeyInput::FlushResult Flush(NativeKeyInput& input) {
        return input.Flush(
            [&](unsigned key, bool down, std::uint64_t epoch) {
                return keys.Deliver(input, key, down, epoch, [&](unsigned physicalKey, bool physicalDown) {
                    events.emplace_back(physicalKey, physicalDown);
                    return !onSend || onSend(physicalKey, physicalDown);
                });
            },
            [&] { return updates; });
    }

    void Movement(std::initializer_list<unsigned> held) {
        tick.movement.Request(Keys(held), 0, User, 0);
        tick.MovementChanged(User);
    }

    void FlushTick() {
        Flush(tick.movement);
        Flush(tick.action);
        tick.MovementFlushed(User, updates, false);
        if (tick.DispatchPending() && tick.action.Dispatched()) tick.TakeDispatch(updates);
        tick.ActionFlushed(User, updates, false);
    }

    void Update(bool characterStep = true) {
        if (characterStep) ++updates;
        old.ConfirmRelease(User, updates, false);
        tick.Observe(User, User, updates, false);
    }
};

void SingleProducer() {
    Boundary native;
    native.old.Request(Keys({Left}), 60, User, 0);
    native.Flush(native.old);
    Check(native.old.Dispatched() && native.keys.Held(Left), "legacy keydown not dispatched");
    native.old.Request(Keys({Left}), 60, User, 1);
    native.Flush(native.old);
    Check(native.events.size() == 1, "unchanged legacy target flickered");
    native.old.Release();
    native.Flush(native.old);
    Check(native.events == std::vector<std::pair<unsigned, bool>>{{Left, true}, {Left, false}},
          "legacy key event sequence changed");
    native.Update(false);
    Check(!native.old.Released(), "render frame incorrectly acknowledged legacy key release");
    native.Update();
    Check(native.old.Released(), "actual character step did not acknowledge legacy release");
}

void IndependentProducers() {
    for (bool releaseOldFirst : {false, true}) {
        Boundary native;
        native.old.Request(Keys({Left, Attack}), 60, User, 0);
        native.Flush(native.old);
        native.Movement({Left});
        native.tick.action.Request(Keys({Attack}), 60, User, 0);
        native.FlushTick();
        Check(native.events.size() == 2, "shared key produced duplicate physical keydown");
        if (releaseOldFirst) {
            native.old.Release();
            native.Flush(native.old);
        } else {
            native.tick.Release(User);
            native.FlushTick();
        }
        Check(native.keys.Held(Left) && native.keys.Held(Attack), "one producer released another producer's key");
        Check(native.events.size() == 2, "logical release emitted physical keyup while another engine held it");
        native.Update(false);
        Check(releaseOldFirst ? !native.old.Released() : !native.tick.Released(),
              "logical release skipped native consumption acknowledgement");
        native.Update();
        if (releaseOldFirst)
            Check(native.old.Released() && native.tick.movement.Held()[Left],
                  "legacy cancellation disturbed tick input");
        else {
            native.Update(); // full tick Release also fences the replacement-safe movement producer
            Check(native.tick.Released() && native.old.Held()[Left], "tick cancellation disturbed legacy input");
        }
        if (releaseOldFirst) {
            native.tick.Release(User);
            native.FlushTick();
        } else {
            native.old.Release();
            native.Flush(native.old);
        }
        Check(!native.keys.Held(Left) && !native.keys.Held(Attack), "last producer did not release all native keys");
        Check(native.events.size() == 4, "final producer failed to emit exactly one physical keyup per key");
    }
}

void ReentrantDown() {
    Boundary native;
    bool reentered = false;
    native.onSend = [&](unsigned key, bool down) {
        if (!reentered && key == Left && down) {
            reentered = true;
            native.Movement({Left});
            native.FlushTick();
            native.old.Release();
            native.Flush(native.old);
        }
        return true;
    };
    native.old.Request(Keys({Left, Right}), 60, User, 0);
    native.Flush(native.old);
    Check(reentered && native.events == std::vector<std::pair<unsigned, bool>>{{Left, true}},
          "reentrant keydown resumed stale keys or released the new owner");
    native.Update();
    Check(native.old.Released() && native.tick.movement.Held()[Left], "reentrant logical release was not isolated");
}

void ReentrantUpAndFailure() {
    Boundary native;
    native.old.Request(Keys({Left}), 60, User, 0);
    native.Flush(native.old);
    bool reentered = false;
    native.onSend = [&](unsigned key, bool down) {
        if (!reentered && key == Left && !down) {
            reentered = true;
            native.Movement({Left});
            native.FlushTick();
            // The failed old callback must not roll back the newer native down.
            return false;
        }
        return true;
    };
    native.old.Release();
    Check(native.Flush(native.old).failed, "failed native keyup was not reported");
    native.onSend = {};
    native.Flush(native.old);
    Check(native.events == std::vector<std::pair<unsigned, bool>>{{Left, true}, {Left, false}, {Left, true}},
          "old failed keyup released the reentrant producer or restored stale physical state");
    native.Update();
    Check(native.old.Released() && native.tick.movement.Held()[Left],
          "failed keyup retry did not converge independently");
    native.tick.Release(User);
    native.FlushTick();
    Check(native.events.back() == std::make_pair(Left, false), "last reentrant producer lost physical release");
}

void TickReleaseFence() {
    Boundary native;
    native.Movement({Left});
    Check(!native.tick.HeldKeysSettled(), "movement was acknowledged before native delivery");
    native.FlushTick();
    native.Update(false);
    Check(!native.tick.HeldKeysSettled(), "render-only frame acknowledged movement");
    native.Update();
    Check(native.tick.HeldKeysSettled() && native.tick.Released(), "held movement incorrectly occupies action slot");
    MapleControl::Action attack;
    attack.kind = MapleControl::ActionKind::Attack;
    native.tick.SetIntent(attack, User);
    native.tick.action.Request(Keys({Attack}), 0, User, 0);
    native.FlushTick();
    Check(!native.tick.Released(), "active action was reported released");
    native.tick.Release(User);
    native.Movement({Right}); // another tick session restores its own intent
    native.FlushTick();
    native.Update(false);
    Check(!native.tick.Released() && !native.tick.HeldKeysSettled(), "replacement intent bypassed release fence");
    native.Update();
    native.Update();
    Check(native.tick.Released() && native.tick.HeldKeysSettled() && native.tick.movement.Held()[Right],
          "asynchronous Release cleared replacement movement or never acknowledged cleanup");
    Check(native.tick.Result().effect == "unknown" && native.tick.Result().settled == MapleControl::Fact::Unknown,
          "input release fabricated game effects or animation completion");

    native.Movement({});
    bool failUp = true;
    native.onSend = [&](unsigned key, bool down) { return key != Right || down || !failUp; };
    native.FlushTick();
    native.Update();
    Check(!native.tick.HeldKeysSettled(), "failed direction release was acknowledged");
    failUp = false;
    native.FlushTick();
    native.Update();
    Check(native.tick.HeldKeysSettled(), "successful direction release retry did not reach its character-step fence");
}

void ItemAndSkillSlots() {
    Boundary native;
    BeiDouBridge::NativeItemUse oldItem;
    BeiDouBridge::NativeSkillUse oldSkill;
    const BeiDouBridge::NativeItemUse::Item item{User, 1, 0x1234, 2, 2000000};
    oldItem.Request(item);
    native.tick.item.Request(item);
    BeiDouBridge::NativeSkillUse::Skill skill;
    skill.character = User;
    skill.user = User;
    skill.sceneGeneration = 1;
    skill.skillId = 1001004;
    oldSkill.Request(skill);
    native.tick.skill.Request(skill);
    native.tick.result.skillRequested = true;
    native.tick.action.Release(); // a native skill has no ordinary action key
    Check(!native.tick.ReleasePending(), "pulse keyup falsely suppressed full adapter cancellation");
    native.tick.Release(User);
    Check(oldItem.Pending() && oldSkill.Pending(), "tick release changed coroutine item/skill lifecycle");
    Check(!native.tick.item.Pending() && !native.tick.skill.Pending(), "tick release retained its native request");
    native.tick.item.Request(item);
    oldItem.Cancel();
    oldSkill.Cancel("old_cancelled");
    Check(native.tick.item.Pending(), "coroutine cancellation changed the tick item slot");
    bool invoked = false;
    native.tick.item.Consume(User, 1, 0x1234, [&](const BeiDouBridge::NativeItemUse::Item& consumed) {
        Check(consumed.itemId == 2000000 && consumed.slot == 2, "ordinary recovery request lost its real slot");
        invoked = true;
        native.tick.item.Request(item);
    });
    Check(invoked && native.tick.item.Pending(), "reentrant ordinary recovery entry lost its newer request");
}

const MapleControl::Value& Field(const MapleControl::Value& object, const std::string& name) {
    for (const auto& member : object.Members())
        if (member.first == name) return member.second;
    static const MapleControl::Value unknown;
    return unknown;
}

// The shared runtime is real. Only the Windows memory/ABI boundary is replaced.
// Like AgentBridge, SetActionIntent replaces the current input; consumption
// happens strictly after Runtime.Tick, never on the Lua stack. Terminal cleanup
// may withdraw the final intent before the native boundary consumes it.
class DeferredNativeAdapter final : public MapleControl::TickAdapter {
public:
    DeferredNativeAdapter() {
        state.instanceId = "gui-tick-deferred";
        state.inGame = state.ready = state.characterKnown = state.positionKnown = state.mapKnown = true;
        state.character.id = User;
        state.character.values[6] = 100;
        state.character.known.fill(true);
        state.sceneGeneration = 1;
        state.actionIdle = MapleControl::Fact::True;
    }

    const char* Backend() const override { return "gui-tick-contract"; }

    const MapleControl::State& Observe() const override { return state; }

    bool Supports(MapleControl::ActionKind kind) const override {
        return kind == MapleControl::ActionKind::Jump || kind == MapleControl::ActionKind::Attack
               || kind == MapleControl::ActionKind::Pickup || kind == MapleControl::ActionKind::UseItem;
    }

    bool SupportsSkill() const override { return true; }

    bool Begin(const MapleControl::Action& request, std::string& error) override {
        return SetActionIntent(request, error);
    }

    bool SetActionIntent(const MapleControl::Action& request, std::string& error) override {
        if (request.kind == MapleControl::ActionKind::Attack && BeiDouBridge::IsNativeKeyDownSkill(request.skillId)) {
            input.ReleaseAction();
            error = "unsupported: native_keydown_skill_release";
            return false;
        }
        if (!input.SetIntent(request, User)) return true;
        const bool key = request.kind == MapleControl::ActionKind::Jump
                         || request.kind == MapleControl::ActionKind::Pickup
                         || (request.kind == MapleControl::ActionKind::Attack && request.skillId == 0);
        input.action.Request(Keys(key ? std::initializer_list<unsigned>{Attack} : std::initializer_list<unsigned>{}), 0,
                             User, frame);
        return true;
    }

    const MapleControl::Action* ActiveAction() const override { return input.ActiveAction(); }

    bool ActionIntentSettled() const override { return input.ActionIntentSettled(); }

    bool SetHeldKeys(const std::vector<std::string>& names, std::string&) override {
        NativeKeyInput::Mask held{};
        for (const auto& name : names) held[name == "left" ? Left : Right] = true;
        input.movement.Request(held, 0, User, frame);
        input.MovementChanged(User);
        return true;
    }

    bool HeldKeysSettled() const override { return input.HeldKeysSettled(); }

    MapleControl::ActionResult Result() const override { return input.Result(); }

    void Release() override { input.Release(User); }

    void ReleaseAction() override { input.ReleaseAction(); }

    bool Released() const override { return input.Released(); }

    bool ReleasePending() const override { return input.ReleasePending(); }

    bool Logs(const std::string&, const std::vector<std::string>&) override { return true; }

    void Advance(MapleControl::TickRuntime& runtime) {
        ++frame;
        ++state.sequence;
        input.Observe(User, User, frame, false);
        input.ObserveAction(nativeAction);
        state.actionIdle = nativeAction.idle;
        runtime.Tick();
        const auto beforeKeys = nativeAction;
        for (auto* source : {&input.movement, &input.action})
            source->Flush(
                [&](unsigned key, bool down, std::uint64_t epoch) {
                    return keys.Deliver(*source, key, down, epoch, [&](unsigned physicalKey, bool physicalDown) {
                        edges.emplace_back(physicalKey, physicalDown);
                        if (physicalDown) {
                            ++keyDowns;
                            if (source == &input.action && input.Intent().kind == MapleControl::ActionKind::Attack
                                && input.Intent().skillId == 0 && ordinaryAttackAllowed)
                                nativeAction = {MapleControl::Fact::False, 17};
                        }
                        return true;
                    });
                },
                [&] { return frame; });
        input.MovementFlushed(User, frame, false);
        const auto& intent = input.Intent();
        input.RepeatDue(frame, repeatSettings);
        if (input.DispatchPending()) {
            if (intent.kind == MapleControl::ActionKind::UseItem) {
                if (input.ItemDispatchAllowed(frame)) {
                    const auto request = input.TakeDispatch(frame);
                    input.item.Request({User, 1, 0x1234, 2, request.itemId});
                }
            } else if (intent.kind == MapleControl::ActionKind::Attack && intent.skillId != 0 && input.action.Released()
                       && input.HeldKeysSettled()
                       && (!input.Dispatched() || nativeAction.idle == MapleControl::Fact::True)) {
                const auto request = input.TakeDispatch(frame);
                BeiDouBridge::NativeSkillUse::Skill skill;
                skill.skillId = request.skillId;
                skill.character = skill.user = User;
                skill.sceneGeneration = 1;
                skill.inputEpoch = input.action.Epoch();
                skill.deadline = 10000;
                input.skill.Request(skill);
                input.result.skillRequested = true;
                input.result.skill = input.skill.Result();
            } else if (input.action.Dispatched()
                       && (!input.Dispatched() || intent.kind != MapleControl::ActionKind::Attack
                           || nativeAction.idle == MapleControl::Fact::True)) {
                const bool initial = !input.Dispatched();
                const auto before = initial ? beforeKeys : nativeAction;
                const auto request = input.TakeDispatch(frame);
                if (!initial) {
                    edges.emplace_back(Attack, true);
                    ++keyDowns;
                    if (ordinaryAttackAllowed) nativeAction = {MapleControl::Fact::False, 17};
                }
                input.NativeStarted(request, input.IntentRevision(), before, nativeAction, true);
            }
        }
        input.ConsumeItem(User, 1, 0x1234, frame, [&](const BeiDouBridge::NativeItemUse::Item& item) {
            ++itemCalls;
            itemEntries.emplace_back(item.itemId, frame);
        });
        if (input.skill.Pending()) {
            BeiDouBridge::NativeSkillUse::Context context;
            context.character = context.user = User;
            context.sceneGeneration = 1;
            context.inputEpoch = input.action.Epoch();
            context.now = frame;
            const auto request = intent;
            const auto before = nativeAction;
            input.skill.Consume(context, [&](std::uint32_t id, int& nativeResult, std::string&) {
                ++skillCalls;
                skillEntries.emplace_back(id, frame);
                nativeResult = skillAllowed ? 1 : 0;
                if (nativeResult != 0 && skillStartsAction) nativeAction = {MapleControl::Fact::False, 17};
                return true;
            });
            input.result.skill = input.skill.Result();
            input.NativeStarted(request, input.IntentRevision(), before, nativeAction,
                                input.result.skill.nativeResultKnown && input.result.skill.nativeResult != 0,
                                input.result.skill.nativeResultKnown);
        }
        input.ActionFlushed(User, frame, false);
    }

    NativeTickInput input;
    NativeKeyUnion keys{&input.movement, &input.action};
    MapleControl::State state;
    std::uint64_t frame = 0;
    BeiDouBridge::NativeActionState nativeAction{MapleControl::Fact::True, -1};
    BeiDouBridge::NativeRepeatSettings repeatSettings;
    bool skillAllowed = true, skillStartsAction = false, ordinaryAttackAllowed = false;
    unsigned itemCalls = 0, skillCalls = 0, keyDowns = 0;
    std::vector<std::pair<unsigned, bool>> edges;
    std::vector<std::pair<std::uint32_t, std::uint64_t>> itemEntries;
    std::vector<std::pair<std::uint32_t, std::uint64_t>> skillEntries;
};

void ActionOwnerCancellation() {
    DeferredNativeAdapter native;
    MapleControl::TickRuntime runtime(native);
    std::string error;
    Check(runtime.Start("attacker",
                        "-- @mode tick\n-- @tick.gear 4\nfunction main(c) if not c.state.sent then "
                        "c.game.player.attack(); c.state.sent=true end end",
                        1000, error),
          error.c_str());
    Check(runtime.Start("mover", "-- @mode tick\n-- @tick.gear 4\nfunction main(c) c.game.player.move('right') end",
                        1000, error),
          error.c_str());
    native.Advance(runtime);
    Check(native.input.action.Held()[Attack] && native.input.movement.Held()[Right],
          "fixtures did not own action and movement");
    const auto edgeCount = native.edges.size();
    runtime.Cancel("attacker", "cancelled");
    for (unsigned frame = 0; frame < 5; ++frame) native.Advance(runtime);
    Check(native.edges.size() == edgeCount + 1 && native.edges.back() == std::make_pair(Attack, false),
          "cancelling action owner emitted another session's movement keyup/down");
    Check(native.input.movement.Held()[Right] && Field(runtime.CurrentStatus("mover"), "status").Text() == "running",
          "action cancellation stopped another session's movement");
    Check(Field(runtime.CurrentStatus("attacker"), "control_released").Boolean(),
          "cancelled action did not acknowledge its own release");
    runtime.CancelAll("cleanup");
    for (unsigned frame = 0; frame < 5; ++frame) native.Advance(runtime);
}

void HeldIntentUpdates() {
    DeferredNativeAdapter native;
    MapleControl::TickRuntime runtime(native);
    std::string error;
    Check(runtime.Start("held", "-- @mode tick\n-- @tick.gear 4\nfunction main(c) c.game.player.skill(1001004) end",
                        1000, error),
          error.c_str());
    for (unsigned frame = 0; frame < 10; ++frame) native.Advance(runtime);
    Check(native.skillCalls == 1 && native.input.HasIntent() && native.input.ActionIntentSettled(),
          "same held skill was replayed or failed to settle after native consumption");
    runtime.CancelAll("cleanup");
    for (unsigned frame = 0; frame < 5; ++frame) native.Advance(runtime);
    Check(!native.input.HasIntent() && native.input.Released() && native.skillCalls == 1,
          "cancel retained a historical held skill");

    DeferredNativeAdapter replaced;
    MapleControl::TickRuntime replacementRuntime(replaced);
    Check(replacementRuntime.Start("replace", R"lua(-- @mode tick
-- @tick.gear 4
function main(c)
    c.state.step = (c.state.step or 0) + 1
    if c.state.step == 1 then c.game.player.attack()
    elseif c.state.step == 2 then c.game.player.skill(2001002)
    elseif c.state.step == 3 then c.game.player.skill(nil) end
end
)lua",
                                   1000, error),
          error.c_str());
    for (unsigned frame = 0; frame < 10; ++frame) replaced.Advance(replacementRuntime);
    Check(replaced.skillCalls == 0 && replaced.keyDowns == 1 && !replaced.input.HasIntent(),
          "withdrawn B was replayed after the old ordinary action key release");
    Check(replaced.edges == std::vector<std::pair<unsigned, bool>>{{Attack, true}, {Attack, false}},
          "replacement/clear manufactured stale action down edges");
    replacementRuntime.CancelAll("cleanup");
    for (unsigned frame = 0; frame < 5; ++frame) replaced.Advance(replacementRuntime);
}

void RejectedAttackRecovery() {
    for (const bool useSkill : {false, true}) {
        DeferredNativeAdapter native;
        native.repeatSettings = {true, 250, 33};
        native.skillAllowed = false;
        native.skillStartsAction = true;
        MapleControl::TickRuntime runtime(native);
        std::string error;
        const auto source = std::string("-- @mode tick\n-- @tick.gear 4\nfunction main(c) if not c.state.sent then ")
                            + (useSkill ? "c.game.player.skill(1001004)" : "c.game.player.attack()")
                            + "; c.state.sent=true end end";
        Check(runtime.Start("recover", source, 1000, error), error.c_str());
        for (unsigned frame = 0; frame < 100; ++frame) native.Advance(runtime);
        Check((useSkill ? native.skillCalls : native.keyDowns) == 1,
              "unstarted native attack was replayed before real repeat delay");
        const auto first = useSkill ? native.skillEntries.front().second : 1;
        native.skillAllowed = native.ordinaryAttackAllowed =
            true; // Native MP/admission recovers; Lua does not rewrite.
        while (native.frame < first + 249) native.Advance(runtime);
        Check((useSkill ? native.skillCalls : native.keyDowns) == 1,
              "condition recovery bypassed native first-repeat setting");
        native.Advance(runtime);
        Check((useSkill ? native.skillCalls : native.keyDowns) == 2 && native.input.ActiveAction(),
              "persistent rejected input never recovered after native admission became legal");
        if (useSkill)
            Check(native.skillEntries.back().second == first + 250,
                  "skill retry did not enter the native boundary at its real first-repeat time");
        runtime.CancelAll("cleanup");
        for (unsigned frame = 0; frame < 5; ++frame) native.Advance(runtime);
    }

    DeferredNativeAdapter noLock;
    noLock.repeatSettings = {true, 250, 33};
    MapleControl::TickRuntime noLockRuntime(noLock);
    std::string error;
    Check(noLockRuntime.Start("no-lock",
                              "-- @mode tick\n-- @tick.gear 4\nfunction main(c) if not c.state.sent then "
                              "c.game.player.skill(1001004); c.state.sent=true end end",
                              1000, error),
          error.c_str());
    for (unsigned frame = 0; frame < 600; ++frame) noLock.Advance(noLockRuntime);
    Check(noLock.skillCalls == 1, "successful no-lock hold was retried like a rejected skill");
    noLockRuntime.CancelAll("cleanup");
    for (unsigned frame = 0; frame < 5; ++frame) noLock.Advance(noLockRuntime);

    DeferredNativeAdapter cleared;
    cleared.repeatSettings = {true, 250, 33};
    cleared.skillAllowed = false;
    MapleControl::TickRuntime clearedRuntime(cleared);
    Check(clearedRuntime.Start("clear-retry",
                               "-- @mode tick\n-- @tick.gear 4\nfunction main(c) "
                               "c.state.n=(c.state.n or 0)+1; if c.state.n==1 then c.game.player.skill(1001004) "
                               "elseif c.state.n==3 then c.game.player.skill(nil) end end",
                               1000, error),
          error.c_str());
    for (unsigned frame = 0; frame < 10; ++frame) cleared.Advance(clearedRuntime);
    cleared.skillAllowed = true;
    for (unsigned frame = 0; frame < 600; ++frame) cleared.Advance(clearedRuntime);
    Check(cleared.skillCalls == 1 && !cleared.input.HasIntent(),
          "withdrawn B retried after its native condition recovered");
    clearedRuntime.CancelAll("cleanup");
    for (unsigned frame = 0; frame < 5; ++frame) cleared.Advance(clearedRuntime);
}

void PotionIntentChurn() {
    DeferredNativeAdapter native;
    MapleControl::TickRuntime runtime(native);
    std::string error;
    Check(runtime.Start("potions", R"lua(-- @mode tick
-- @tick.gear 4
function main(c)
    c.state.step = (c.state.step or 0) + 1
    local step = c.state.step
    if step == 1 or step == 103 or step == 105 then c.game.player.use_item(2000000)
    elseif step == 2 or step == 5 or step == 202 then c.game.player.use_item(2000001)
    elseif step == 3 or step == 102 then c.game.player.skill(nil)
    elseif step == 4 or step == 104 then c.game.player.attack() end
end
)lua",
                        1000, error),
          error.c_str());
    for (unsigned frame = 0; frame < 202; ++frame) native.Advance(runtime);
    Check(native.itemEntries
              == std::vector<std::pair<std::uint32_t, std::uint64_t>>{{2000000, 1}, {2000001, 101}, {2000000, 201}},
          "Lua potion replacement/clear/ordinary action churn reset the actual native-use guard");
    Check(native.input.Intent().itemId == 2000001 && native.input.DispatchPending(),
          "protected replacement potion was not retained as the current replaceable input");
    runtime.Cancel("potions", "cancel_during_potion_protection");
    for (unsigned frame = 0; frame < 5; ++frame) native.Advance(runtime);
    Check(!runtime.Running() && native.input.Released() && native.itemCalls == 3
              && Field(runtime.CurrentStatus("potions"), "control_released").Boolean(),
          "potion protection delayed cancellation/release or replayed cancelled medicine");
    for (unsigned frame = 0; frame < 110; ++frame) native.Advance(runtime);
    Check(native.itemCalls == 3, "cancelled potion was delivered after protection elapsed");
}

void DeferredFinish(bool overrun) {
    const std::vector<std::string> actions{"use_item(2000000)", "skill(1001004)", "jump()", "attack()", "pickup()"};
    for (const auto& action : actions) {
        for (bool commit : {true, false}) {
            if (!overrun && !commit) continue;
            DeferredNativeAdapter native;
            MapleControl::TickRuntime runtime(native);
            std::string error;
            const std::string source = "-- @mode tick\n-- @tick.gear 4\n-- @tick.budget_ms 1\n-- @tick.abort_commit "
                                       + std::string(commit ? "true" : "false") + "\nfunction main(c) c.game.player."
                                       + action + (overrun ? "; while true do end end" : "; return 'done' end");
            Check(runtime.Start("deferred", source, 1000, error), error.c_str());
            for (unsigned frame = 0; frame < 20 && runtime.Running(); ++frame) native.Advance(runtime);
            const auto status = runtime.CurrentStatus("deferred");
            Check(!runtime.Running() && Field(status, "control_released").Boolean(),
                  "deferred final action never completed and released its own input");
            Check(Field(status, "status").Text() == (overrun ? "cancelled" : "completed"),
                  "deferred final action changed session outcome");
            if (overrun) Check(Field(status, "reason").Text() == "tick_overrun", "lost tick budget failure reason");
            const auto expected = 0u;
            Check(native.itemCalls + native.skillCalls + native.keyDowns == expected,
                  "terminal held intent was replayed after its owner had already stopped");
            Check(native.input.Result().effect == "unknown", "deferred dispatch fabricated a game effect");
        }
    }
}
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string test = argv[1];
    if (test == "single")
        SingleProducer();
    else if (test == "isolation")
        IndependentProducers();
    else if (test == "reentrant-down")
        ReentrantDown();
    else if (test == "reentrant-up")
        ReentrantUpAndFailure();
    else if (test == "release-fence")
        TickReleaseFence();
    else if (test == "slots")
        ItemAndSkillSlots();
    else if (test == "action-owner-cancel")
        ActionOwnerCancellation();
    else if (test == "held-updates")
        HeldIntentUpdates();
    else if (test == "attack-recovery")
        RejectedAttackRecovery();
    else if (test == "potion-churn")
        PotionIntentChurn();
    else if (test == "deferred-done")
        DeferredFinish(false);
    else if (test == "deferred-overrun")
        DeferredFinish(true);
    else
        return 2;
    std::cout << test << ": passed\n";
}
