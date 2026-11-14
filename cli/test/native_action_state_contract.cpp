// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeActionState.h"
#include "NativeTickInput.h"

#include <cstdlib>
#include <iostream>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace {
using BeiDouBridge::NativeActionState;
using BeiDouBridge::NativeTickInput;
using MapleControl::Action;
using MapleControl::ActionKind;
using MapleControl::Fact;
constexpr std::uint32_t User = 0x100000, Input = 0x200000;
std::map<std::uintptr_t, std::uint32_t> memory;

void Check(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

bool Read(std::uintptr_t address, std::uint32_t& value) {
    const auto found = memory.find(address);
    if (found == memory.end()) return false;
    value = found->second;
    return true;
}

void Fixture() {
    memory = {{User, 0x00B3D20C},       {User + 4, 0x00B3D1E8}, {User + 0x574, 0xFFFFFFFF}, {0x0059B307, 0x0930968B},
              {0x0059B30F, 0x0934968B}, {Input + 0x930, 750},   {Input + 0x934, 112}};
}

Action Skill(std::uint32_t id) {
    Action action;
    action.kind = ActionKind::Attack;
    action.skillId = id;
    return action;
}

void StateFacts() {
    Fixture();
    auto state = BeiDouBridge::ReadNativeActionState(User, Read);
    Check(state.idle == Fact::True && state.index == -1, "native -1 one-time action is not idle");
    // These are raw one-time indices, including indices remapped by 0x451B6A.
    // The sign is the native admission fact, not a list of attack animations.
    for (std::uint32_t index : {0u, 9u, 0x51u, 0xA1u}) {
        memory[User + 0x574] = index;
        state = BeiDouBridge::ReadNativeActionState(User, Read);
        Check(state.idle == Fact::False && state.index == static_cast<int>(index),
              "valid native action index was mistaken for idle");
    }
    memory[User + 0x574] = 0xFFFFFFFF;
    Check(BeiDouBridge::ReadNativeActionState(User, Read).idle == Fact::True,
          "native frame-end clear did not become idle");
    for (const auto address : {std::uintptr_t(User), std::uintptr_t(User + 4), std::uintptr_t(User + 0x574)}) {
        Fixture();
        memory.erase(address);
        Check(BeiDouBridge::ReadNativeActionState(User, Read).idle == Fact::Unknown,
              "unreadable native action was fabricated as idle");
    }
    Fixture();
    memory[User] = 0x00B3D898; // Remote user is not the local-user layout.
    Check(BeiDouBridge::ReadNativeActionState(User, Read).idle == Fact::Unknown,
          "wrong native object type was read as local action");
    Check(BeiDouBridge::ReadNativeActionState(0, Read).idle == Fact::Unknown,
          "absent native user was fabricated as idle");
    // Independent values from 0x4FB08F's leaf comparisons, not a hotkey table.
    for (const auto skill : {1121001u, 1221001u, 1321001u, 2121001u, 2221001u, 2321001u, 3121004u, 3221001u, 5101004u,
                             5201002u, 5221004u, 13111002u, 14111006u, 15101003u, 22121000u, 22151001u})
        Check(BeiDouBridge::IsNativeKeyDownSkill(skill), "native key-down skill escaped explicit unsupported boundary");
    for (const auto skill : {0u, 1001004u, 2001002u, 1121000u, 1121002u})
        Check(!BeiDouBridge::IsNativeKeyDownSkill(skill),
              "ordinary skill was confused with scan-dependent key-down skill");
}

void NativeRepeatFacts() {
    Fixture();
    auto settings = BeiDouBridge::ReadNativeRepeatSettings(Input, Read);
    Check(settings.known && settings.firstDelayMs == 750 && settings.intervalMs == 112,
          "repeat did not read the current native settings");
    for (const auto address : {std::uintptr_t(0x0059B307), std::uintptr_t(0x0059B30F), std::uintptr_t(Input + 0x930),
                               std::uintptr_t(Input + 0x934)}) {
        Fixture();
        memory.erase(address);
        Check(!BeiDouBridge::ReadNativeRepeatSettings(Input, Read).known,
              "missing repeat evidence manufactured a default delay");
    }
    for (const auto delay : {0u, 249u, 1001u}) {
        Fixture();
        memory[Input + 0x930] = delay;
        Check(!BeiDouBridge::ReadNativeRepeatSettings(Input, Read).known, "invalid first repeat delay accepted");
    }
    for (const auto interval : {0u, 32u, 401u}) {
        Fixture();
        memory[Input + 0x934] = interval;
        Check(!BeiDouBridge::ReadNativeRepeatSettings(Input, Read).known, "invalid repeat interval accepted");
    }
    Fixture();
    memory[0x0059B307] = 0x0930968A;
    Check(!BeiDouBridge::ReadNativeRepeatSettings(Input, Read).known, "wrong native code layout accepted");
}

void CurrentIntentAndActualAction() {
    NativeTickInput input;
    auto a = Skill(1001004), b = Skill(2001002);
    a.sessionId = "old-owner";
    b.sessionId = "other-owner";
    Check(input.SetIntent(a, User), "initial intent not accepted");
    const auto aRevision = input.IntentRevision();
    input.TakeDispatch(1);
    input.NativeStarted(a, aRevision, {Fact::True, -1}, {Fact::False, 17}, true);
    Check(input.ActiveAction() && input.ActiveAction()->skillId == a.skillId, "admitted A was not recorded");
    auto same = a;
    same.sessionId = "new-owner";
    Check(!input.SetIntent(same, User) && input.IntentRevision() == aRevision && !input.DispatchPending(),
          "same-input owner transfer restarted physical input or repeat clock");
    Check(input.Intent().sessionId == "new-owner" && input.Result().sessionId == "new-owner"
              && input.ActiveAction()->sessionId == "old-owner",
          "same-input handoff lost current owner or relabelled already-started A");
    input.ObserveAction({Fact::True, -1});
    Check(input.DispatchPending(), "handoff lost the native next-action boundary");
    const auto repeat = input.TakeDispatch(2);
    input.NativeStarted(repeat, input.IntentRevision(), {Fact::True, -1}, {Fact::False, 17}, true);
    Check(input.ActiveAction() && input.ActiveAction()->sessionId == "new-owner",
          "new native repeat kept the previous input owner's identity");
    Check(input.SetIntent(b, User), "B did not replace current input");
    Check(input.ActiveAction() && input.ActiveAction()->skillId == a.skillId && input.Intent().skillId == b.skillId,
          "input B overwrote actual native action A");
    const auto bRevision = input.IntentRevision();
    input.TakeDispatch(2);
    input.NativeStarted(b, bRevision, {Fact::False, 17}, {Fact::False, 17}, false);
    Check(input.ActiveAction()->skillId == a.skillId && !input.DispatchPending(),
          "native rejection cleared A or queued a historical B");
    input.ObserveAction({Fact::True, -1});
    Check(!input.ActiveAction() && input.DispatchPending() && input.Intent().skillId == b.skillId,
          "real idle edge did not resample the still-current B input");
    input.ReleaseAction();
    Check(!input.HasIntent() && !input.DispatchPending(), "clear retained an unconsumed B");
    input.NativeStarted(b, bRevision, {Fact::True, -1}, {Fact::False, 20}, true);
    Check(!input.ActiveAction() && !input.HasIntent(), "stale native callback revived cancelled B");

    input.SetIntent(a, User);
    input.TakeDispatch(3);
    input.NativeStarted(a, input.IntentRevision(), {Fact::True, -1}, {Fact::False, 17}, true);
    input.ReleaseAction();
    Check(input.ActiveAction() && input.ActiveAction()->skillId == a.skillId,
          "clear claimed it interrupted an already-started native animation");
    input.ObserveAction({Fact::True, -1});
    Check(!input.ActiveAction() && !input.DispatchPending(), "cleared input repeated at A's completion");

    input.SetIntent(a, User);
    input.TakeDispatch(4);
    input.NativeStarted(a, input.IntentRevision(), {Fact::True, -1}, {Fact::False, 17}, true);
    input.SetIntent(b, User);
    input.TakeDispatch(5);
    input.NativeStarted(b, input.IntentRevision(), {Fact::False, 17}, {Fact::False, 17}, true);
    Check(input.ActiveAction() && input.ActiveAction()->skillId == a.skillId,
          "successful no-new-lock B relabelled the unchanged native A animation");
    input.ObserveAction({Fact::True, -1});
    Check(!input.DispatchPending(), "successful no-new-lock B repeated on A's completion");

    input.SetIntent(a, User);
    input.TakeDispatch(6);
    input.NativeStarted(a, input.IntentRevision(), {Fact::True, -1}, {Fact::False, 17}, true);
    input.SetIntent(b, User);
    input.TakeDispatch(7);
    input.NativeStarted(b, input.IntentRevision(), {}, {Fact::False, 17}, true);
    Check(input.ActiveAction() && input.ActiveAction()->skillId == a.skillId,
          "Unknown before snapshot used its default index to relabel old A as successful B");
    input.ObserveAction({Fact::True, -1});
    input.RepeatDue(10000, {true, 250, 33});
    Check(!input.DispatchPending() && !input.ActiveAction(),
          "Unknown attribution manufactured B's animation or a later no-lock B retry");
}

void NoLockAndUnknown() {
    NativeTickInput input;
    const auto skill = Skill(1001004);
    input.SetIntent(skill, User);
    input.TakeDispatch(10);
    input.NativeStarted(skill, input.IntentRevision(), {Fact::True, -1}, {Fact::True, -1}, true);
    const auto revision = input.IntentRevision();
    for (unsigned frame = 0; frame < 100; ++frame) {
        Check(!input.SetIntent(skill, User), "same skill value was not idempotent");
        input.ObserveAction({Fact::True, -1});
        input.RepeatDue(10000 + frame, {true, 250, 33});
        Check(!input.DispatchPending() && !input.ActiveAction() && input.IntentRevision() == revision,
              "no-lock skill was replayed by Lua frequency or native repeat clock");
    }
    input.ObserveAction({Fact::False, 17});
    input.ObserveAction({Fact::True, -1});
    Check(!input.DispatchPending(), "successful no-lock skill repeated on somebody else's animation");
    const auto rejected = Skill(2001002);
    input.SetIntent(rejected, User);
    input.TakeDispatch(100);
    input.NativeStarted(rejected, input.IntentRevision(), {Fact::False, 17}, {Fact::False, 17}, false);
    input.ObserveAction({});
    input.ObserveAction({Fact::True, -1});
    Check(!input.DispatchPending(), "unknown observation manufactured a native completion edge");
    input.ObserveAction({Fact::False, 17});
    input.ObserveAction({Fact::True, -1});
    Check(input.DispatchPending(), "known busy-idle edge failed to drive held attack");
    input.ObserveAction({}, true);
    Check(!input.ActiveAction(), "departed character retained an actual action");
}

void RepeatAndPotion() {
    NativeTickInput input;
    Action pickup;
    pickup.kind = ActionKind::Pickup;
    input.SetIntent(pickup, User);
    input.TakeDispatch(100);
    for (const auto now : {200u, 500u, 849u}) {
        input.SetIntent(pickup, User);
        input.RepeatDue(now, {true, 750, 112});
        Check(!input.DispatchPending(), "same-value Lua writes shortened native initial repeat delay");
    }
    input.RepeatDue(850, {true, 750, 112});
    Check(input.DispatchPending(), "native initial repeat was not due at its real setting");
    input.TakeDispatch(850);
    input.RepeatDue(961, {true, 750, 112});
    Check(!input.DispatchPending(), "native subsequent repeat ignored current interval");
    input.RepeatDue(962, {true, 750, 112});
    Check(input.DispatchPending(), "native subsequent repeat did not arrive");
    input.TakeDispatch(5000); // A long host delay emits one event, not catch-up.
    input.RepeatDue(5000, {true, 750, 112});
    Check(!input.DispatchPending(), "repeat caught up stale events after host delay");
    input.RepeatDue(10000, {});
    Check(!input.DispatchPending(), "unknown native repeat settings used a guessed frequency");
    input.ReleaseAction();
    input.RepeatDue(100000, {true, 250, 33});
    Check(!input.DispatchPending(), "released pickup repeated");

    Action jump;
    jump.kind = ActionKind::Jump;
    input.SetIntent(jump, User);
    input.TakeDispatch(1);
    input.ObserveAction({Fact::False, 17});
    input.ObserveAction({Fact::True, -1});
    input.RepeatDue(100000, {true, 250, 33});
    Check(!input.DispatchPending(), "jump synthesized an extra keydown");

    Action potion;
    potion.kind = ActionKind::UseItem;
    potion.itemId = 2000000;
    input.SetIntent(potion, User);
    input.TakeDispatch(100);
    input.item.Request({User, 1, 0x1234, 2, potion.itemId});
    input.ConsumeItem(User, 1, 0x1234, 100, [](const BeiDouBridge::NativeItemUse::Item&) {});
    input.SetIntent(potion, User);
    input.RepeatDue(199, {});
    Check(!input.DispatchPending(), "potion bypassed its exclusive consumption guard");
    input.RepeatDue(200, {});
    Check(input.DispatchPending(), "potion incorrectly waited for animation idle or keyboard repeat");
    input.ReleaseAction();
    input.RepeatDue(100000, {});
    Check(!input.DispatchPending(), "cancelled potion retained a pending consumption");
}

void UnstartedAttackRetry() {
    Fixture();
    const auto settings = BeiDouBridge::ReadNativeRepeatSettings(Input, Read);
    const auto skill = Skill(1001004);
    std::vector<std::uint64_t> calls;
    const auto consumeSkill = [&](NativeTickInput& input, NativeActionState& native, std::uint64_t now,
                                  bool mpAvailable, bool startsAction) {
        input.ObserveAction(native);
        input.RepeatDue(now, settings);
        if (!input.DispatchPending()) return;
        const auto request = input.TakeDispatch(now);
        const auto before = native;
        BeiDouBridge::NativeSkillUse::Skill pending;
        pending.character = pending.user = User;
        pending.skillId = request.skillId;
        pending.sceneGeneration = 1;
        pending.inputEpoch = input.action.Epoch();
        pending.deadline = 1000000;
        input.skill.Request(pending);
        BeiDouBridge::NativeSkillUse::Context context;
        context.character = context.user = User;
        context.sceneGeneration = 1;
        context.inputEpoch = input.action.Epoch();
        context.now = now;
        input.skill.Consume(context, [&](std::uint32_t id, int& result, std::string&) {
            Check(id == skill.skillId, "retry did not call the current skill_id native entry");
            calls.push_back(now);
            result = mpAvailable ? 1 : 0;
            if (result != 0 && startsAction) native = {Fact::False, 17};
            return true;
        });
        const auto result = input.skill.Result();
        input.NativeStarted(request, input.IntentRevision(), before, native,
                            result.nativeResultKnown && result.nativeResult != 0, result.nativeResultKnown);
    };
    NativeTickInput input;
    NativeActionState native{Fact::True, -1};
    input.SetIntent(skill, User); // One Lua-style write only, no periodic refresh.
    const auto revision = input.IntentRevision();
    consumeSkill(input, native, 0, false, true);
    consumeSkill(input, native, 749, false, true);
    Check(calls == std::vector<std::uint64_t>{0}, "failed skill ignored native first-repeat delay");
    consumeSkill(input, native, 750, false, true);
    consumeSkill(input, native, 800, true, true);
    consumeSkill(input, native, 861, true, true);
    Check(calls == std::vector<std::uint64_t>{0, 750}, "recovered MP bypassed native subsequent-repeat interval");
    consumeSkill(input, native, 862, true, true);
    Check(calls == std::vector<std::uint64_t>{0, 750, 862} && input.IntentRevision() == revision && input.ActiveAction()
              && input.ActiveAction()->skillId == skill.skillId,
          "still-held rejected skill failed to recover when MP returned without another Lua write");
    consumeSkill(input, native, 10000, true, true);
    Check(calls.size() == 3, "busy native skill was retried by a repeat timer");

    NativeTickInput noLock;
    NativeActionState idle{Fact::True, -1};
    calls.clear();
    noLock.SetIntent(skill, User);
    consumeSkill(noLock, idle, 0, true, false);
    consumeSkill(noLock, idle, 750, true, false);
    consumeSkill(noLock, idle, 20000, true, false);
    Check(calls == std::vector<std::uint64_t>{0}, "successful no-lock skill acquired failed-skill retry semantics");

    NativeTickInput unknown;
    calls.clear();
    unknown.SetIntent(skill, User);
    consumeSkill(unknown, idle, 0, false, true);
    NativeActionState unreadable;
    consumeSkill(unknown, unreadable, 750, true, true);
    Check(calls.size() == 1, "Unknown native idle manufactured retry permission");
    unknown.ObserveAction(idle);
    unknown.RepeatDue(751, settings);
    Check(unknown.DispatchPending(), "known idle did not recover the current retry after an unreadable sample");
    unknown.ReleaseAction();
    consumeSkill(unknown, idle, 20000, true, true);
    Check(calls.size() == 1 && !unknown.HasIntent(), "cleared B retained a historical native retry");

    NativeTickInput ordinary;
    Action attack;
    attack.kind = ActionKind::Attack;
    ordinary.SetIntent(attack, User);
    BeiDouBridge::NativeKeyInput::Mask keys{};
    keys[17] = true;
    ordinary.action.Request(keys, 0, User, 0);
    NativeActionState attackState{Fact::True, -1};
    std::vector<std::uint64_t> downs;
    ordinary.action.Flush(
        [&](unsigned, bool down, std::uint64_t) {
            Check(down, "initial ordinary attack unexpectedly pulsed keyup");
            downs.push_back(0);
            return true;
        },
        [] { return 1; });
    ordinary.TakeDispatch(0);
    ordinary.NativeStarted(attack, ordinary.IntentRevision(), attackState, attackState, true);
    const auto repeatAttack = [&](std::uint64_t now, bool nativeAllowsAttack) {
        ordinary.ObserveAction(attackState);
        ordinary.RepeatDue(now, settings);
        if (!ordinary.DispatchPending()) return;
        const auto before = attackState;
        const auto request = ordinary.TakeDispatch(now);
        downs.push_back(now); // The external native keydown consumer, no up/down pulse.
        if (nativeAllowsAttack) attackState = {Fact::False, 17};
        ordinary.NativeStarted(request, ordinary.IntentRevision(), before, attackState, true);
    };
    repeatAttack(749, false);
    repeatAttack(750, false);
    repeatAttack(861, true);
    repeatAttack(862, true);
    Check(downs == std::vector<std::uint64_t>{0, 750, 862} && ordinary.action.Held()[17] && ordinary.ActiveAction()
              && ordinary.ActiveAction()->kind == ActionKind::Attack,
          "blocked ordinary attack did not recover on native repeat without releasing the held key");
}

void PotionConsumptionBoundary() {
    NativeTickInput input;
    Action a, b;
    a.kind = b.kind = ActionKind::UseItem;
    a.itemId = 2000000;
    b.itemId = 2000001;
    std::vector<std::pair<std::uint32_t, std::uint64_t>> calls;
    const auto consume = [&](std::uint64_t now) {
        return input.ConsumeItem(User, 1, 0x1234, now, [&](const BeiDouBridge::NativeItemUse::Item& item) {
            calls.emplace_back(item.itemId, now);
            Check(!input.ItemDispatchAllowed(now), "native callback entered before potion guard was committed");
        });
    };
    const auto pump = [&](std::uint64_t now) {
        input.RepeatDue(now, {});
        if (input.DispatchPending() && input.Intent().kind == ActionKind::UseItem && input.ItemDispatchAllowed(now)) {
            const auto request = input.TakeDispatch(now);
            input.item.Request({User, 1, 0x1234, 2, request.itemId});
        }
        consume(now);
    };
    input.SetIntent(a, User);
    pump(0); // Zero is a valid first actual dispatch timestamp, not an unset sentinel.
    input.SetIntent(b, User);
    pump(1);
    pump(99);
    Check(calls.size() == 1 && input.Intent().itemId == b.itemId, "changing potion bypassed native protection");
    pump(100);
    input.ReleaseAction();
    input.SetIntent(a, User);
    pump(101);
    pump(199);
    Check(calls.size() == 2, "clear then reapply reset actual potion protection");
    pump(200);
    Action attack;
    attack.kind = ActionKind::Attack;
    input.SetIntent(attack, User);
    input.TakeDispatch(230);
    input.SetIntent(b, User);
    pump(250);
    pump(299);
    Check(calls.size() == 3, "intervening ordinary action reset potion protection");
    pump(300);
    input.SetIntent(a, User);
    pump(301);
    input.ReleaseAction();
    pump(399);
    Check(!input.HasIntent() && !input.item.Pending() && !input.DispatchPending() && calls.size() == 4,
          "protection wait delayed cancellation or retained a historical potion");
    input.SetIntent(a, User);
    pump(400);

    // Failed context validation must not count as a native use at 500.
    input.SetIntent(b, User);
    input.TakeDispatch(500);
    input.item.Request({User, 1, 0x9999, 2, b.itemId});
    Check(consume(500) == BeiDouBridge::NativeItemUse::Consumption::ContextChanged,
          "context-mismatched request unexpectedly reached native use");
    Check(input.ItemDispatchAllowed(501), "unconsumed request falsely advanced actual potion timestamp");
    input.RepeatDue(501, {});
    Check(input.DispatchPending(), "unconsumed request imposed a fake per-intent potion deadline");
    input.SetIntent(a, User);
    pump(501);

    input.SetIntent(b, User);
    input.TakeDispatch(601);
    input.item.Request({User, 1, 0x1234, 2, b.itemId});
    input.ReleaseAction(); // The accepted request is cancelled before its native phase.
    consume(601);
    Check(input.ItemDispatchAllowed(602), "cancelled unconsumed request falsely consumed potion protection");
    input.SetIntent(b, User);
    pump(602);

    // A native callback may accept the next current intent reentrantly, but it
    // cannot consume it before the first native call's guard has elapsed.
    input.SetIntent(a, User);
    input.TakeDispatch(702);
    input.item.Request({User, 1, 0x1234, 2, a.itemId});
    input.ConsumeItem(User, 1, 0x1234, 702, [&](const BeiDouBridge::NativeItemUse::Item& item) {
        calls.emplace_back(item.itemId, 702);
        input.SetIntent(b, User);
        input.TakeDispatch(702);
        input.item.Request({User, 1, 0x1234, 2, b.itemId});
        Check(consume(702) == BeiDouBridge::NativeItemUse::Consumption::None && input.item.Pending(),
              "reentrant replacement bypassed actual native potion guard");
    });
    consume(801);
    consume(802);
    Check(calls
              == std::vector<std::pair<std::uint32_t, std::uint64_t>>{{a.itemId, 0},
                                                                      {b.itemId, 100},
                                                                      {a.itemId, 200},
                                                                      {b.itemId, 300},
                                                                      {a.itemId, 400},
                                                                      {a.itemId, 501},
                                                                      {b.itemId, 602},
                                                                      {a.itemId, 702},
                                                                      {b.itemId, 802}},
          "native potion callback timestamps changed across replacements, clear, other actions or cancellation");
    for (std::size_t index = 1; index < calls.size(); ++index)
        Check(calls[index].second - calls[index - 1].second >= 100, "actual native potion calls violated 100ms guard");

    NativeTickInput cancelled;
    cancelled.SetIntent(a, User);
    cancelled.TakeDispatch(0);
    cancelled.item.Request({User, 1, 0x1234, 2, a.itemId});
    cancelled.ConsumeItem(User, 1, 0x1234, 0, [](const BeiDouBridge::NativeItemUse::Item&) {});
    cancelled.SetIntent(b, User);
    Check(!cancelled.ItemDispatchAllowed(1), "fixture did not establish protected pending B");
    cancelled.ReleaseAction();
    cancelled.action.Flush([](unsigned, bool, std::uint64_t) { return true; }, [] { return 1; });
    cancelled.ActionFlushed(User, 1, false);
    cancelled.Observe(User, User, 2, false);
    Check(cancelled.Released() && !cancelled.ItemDispatchAllowed(2),
          "actual potion protection became a cancellation or input-release deadline");
}

void InputFences() {
    NativeTickInput input;
    auto a = Skill(1001004);
    input.SetIntent(a, User);
    input.TakeDispatch(0);
    input.ActionFlushed(User, 1, false);
    Check(!input.ActionIntentSettled(), "action intent was acknowledged before native character consumption");
    input.Observe(User, User, 2, false);
    Check(input.ActionIntentSettled() && input.HasIntent() && !input.Released(),
          "held input could not settle independently from release");
    input.ReleaseAction();
    input.action.Flush([](unsigned, bool, std::uint64_t) { return true; }, [] { return 2; });
    input.Observe(User, User, 2, false);
    Check(!input.Released(), "clear skipped native release confirmation");
    input.Observe(User, User, 3, false);
    Check(input.Released(), "cleared action did not converge after native character consumption");

    NativeTickInput keyed;
    Action attack;
    attack.kind = ActionKind::Attack;
    keyed.SetIntent(attack, User);
    BeiDouBridge::NativeKeyInput::Mask keys{};
    keys[17] = true;
    keyed.action.Request(keys, 0, User, 0);
    std::uint64_t updates = 1;
    bool failUp = false;
    unsigned downs = 0, ups = 0;
    const auto flush = [&] {
        return keyed.action.Flush(
            [&](unsigned, bool down, std::uint64_t) {
                if (!down && failUp) return false;
                if (down)
                    ++downs;
                else
                    ++ups;
                return true;
            },
            [&] { return updates; });
    };
    flush();
    keyed.TakeDispatch(0);
    keyed.ActionFlushed(User, updates, false);
    keyed.Observe(User, User, ++updates, false);
    Action pickup;
    pickup.kind = ActionKind::Pickup;
    keyed.SetIntent(pickup, User);
    keys[17] = false;
    keys[32] = true;
    keyed.action.Request(keys, 0, User, 1);
    failUp = true;
    Check(flush().failed && downs == 1 && !keyed.ActionIntentSettled(),
          "failed old keyup allowed replacement B down or settled input");
    failUp = false;
    flush();
    keyed.TakeDispatch(1);
    keyed.ActionFlushed(User, updates, false);
    Check(!keyed.ActionIntentSettled() && downs == 2 && ups == 1, "replacement skipped old release or native fence");
    keyed.Observe(User, User, ++updates, false);
    Check(keyed.ActionIntentSettled() && keyed.action.Held()[32] && !keyed.Released(),
          "new held B prevented acknowledgement of the old A release");
    keyed.ReleaseAction();
    flush();
    keyed.ActionFlushed(User, updates, false);
    keyed.Observe(User, User, ++updates, false);
    Check(keyed.Released() && downs == 2 && ups == 2, "clear did not release the actual last held B key");
}
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string scenario = argv[1];
    if (scenario == "state")
        StateFacts();
    else if (scenario == "native-repeat")
        NativeRepeatFacts();
    else if (scenario == "intent")
        CurrentIntentAndActualAction();
    else if (scenario == "no-lock")
        NoLockAndUnknown();
    else if (scenario == "repeat")
        RepeatAndPotion();
    else if (scenario == "fences")
        InputFences();
    else if (scenario == "potion-native")
        PotionConsumptionBoundary();
    else if (scenario == "attack-retry")
        UnstartedAttackRetry();
    else
        return 2;
    std::cout << scenario << ": passed\n";
}
