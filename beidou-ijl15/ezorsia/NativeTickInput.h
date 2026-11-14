// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "NativeActionState.h"
#include "NativeKeyInput.h"
#include "NativeItemUse.h"
#include "NativeSkillUse.h"

namespace BeiDouBridge {

// Tick-only current input ownership. The latest held intent is not an animation
// queue. A native action already started is stored independently until the real
// Avatar one-time action becomes idle (or its character leaves).
struct NativeTickInput {
    NativeKeyInput movement;
    NativeKeyInput action;
    NativeItemUse item;
    NativeSkillUse skill;
    MapleControl::ActionResult result;
    bool itemResult = false;

    static bool SameIntent(const MapleControl::Action& left, const MapleControl::Action& right) {
        return left.kind == right.kind && left.skillId == right.skillId && left.itemId == right.itemId;
    }

    const MapleControl::Action& Intent() const { return intent; }

    std::uint64_t IntentRevision() const { return intentRevision; }

    bool HasIntent() const { return intent.kind != MapleControl::ActionKind::Stop; }

    bool DispatchPending() const { return dispatchPending; }

    bool Dispatched() const { return dispatched; }

    const MapleControl::Action* ActiveAction() const { return nativeActionActive ? &nativeAction : nullptr; }

    // Potion protection belongs to actual native consumption, not to an intent
    // value or key-repeat clock. Replacement, clear and other actions cannot
    // reset it; a request that never reaches the native entry cannot advance it.
    bool ItemDispatchAllowed(std::uint64_t now) const { return !haveItemDispatch || now - lastItemDispatch >= 100; }

    template <class Invoke>
    NativeItemUse::Consumption ConsumeItem(std::uint32_t character, std::uint64_t scene, std::uint32_t context,
                                           std::uint64_t now, const Invoke& invoke) {
        if (!ItemDispatchAllowed(now)) return NativeItemUse::Consumption::None;
        return item.Consume(character, scene, context, [&](const NativeItemUse::Item& consumed) {
            // Commit before the reentrant native entry. NativeItemUse has
            // already validated the current character/scene/context here.
            lastItemDispatch = now;
            haveItemDispatch = true;
            invoke(consumed);
        });
    }

    // Call only after admission validation. Same-value writes preserve both the
    // native keydown and all repeat/consumption clocks.
    bool SetIntent(const MapleControl::Action& request, std::uint32_t user) {
        if (SameIntent(intent, request)) {
            // Same physical input can transfer between sessions. Only the
            // current intent/result owner changes; the copied actual A and
            // native repeat/consumption clocks keep their original identity.
            intent.sessionId = request.sessionId;
            result.sessionId = request.sessionId;
            return false;
        }
        skill.Cancel("native_skill_replaced");
        item.Cancel();
        action.Release();
        intent = request;
        ++intentRevision;
        dispatchPending = HasIntent();
        dispatched = false;
        repeatOnIdle = true;
        retryUnstartedAttack = false;
        repeated = false;
        itemResult = request.kind == MapleControl::ActionKind::UseItem;
        result = {};
        result.sessionId = request.sessionId;
        result.reason = HasIntent() ? "native_input_held" : "native_input_cleared";
        ActionChanged(user);
        return true;
    }

    void ObserveAction(const NativeActionState& state, bool characterExited = false) {
        if (characterExited) {
            nativeActionActive = false;
            observedAction = {};
            return;
        }
        // Only an observed busy -> idle boundary can repeat an attack/skill.
        // A successful skill with no one-time action is conservatively one use
        // per hold. Unknown reads never manufacture an idle boundary.
        if (state.idle == MapleControl::Fact::True) {
            nativeActionActive = false;
            if (observedAction.idle == MapleControl::Fact::False && dispatched && repeatOnIdle
                && intent.kind == MapleControl::ActionKind::Attack)
                dispatchPending = true;
        }
        observedAction = state;
    }

    void RepeatDue(std::uint64_t now, const NativeRepeatSettings& settings) {
        if (!dispatched || dispatchPending) return;
        if (intent.kind == MapleControl::ActionKind::UseItem) {
            if (ItemDispatchAllowed(now)) dispatchPending = true;
        } else if (settings.known
                   && (intent.kind == MapleControl::ActionKind::Pickup
                       || (intent.kind == MapleControl::ActionKind::Attack && retryUnstartedAttack
                           && observedAction.idle == MapleControl::Fact::True))) {
            // Narrow CInputSystem::GenerateRepeatEvent 0x59B2D2 port: initial
            // delay, then interval; at most one current event, no catch-up.
            // An attack that never started can recover without another Lua
            // write, but only when a fresh native observation really is idle.
            const auto delay = repeated ? settings.intervalMs : settings.firstDelayMs;
            if (now - lastDispatch >= delay) {
                dispatchPending = true;
                repeated = true;
            }
        }
    }

    // Consume before entering a reentrant native call. A replacement/cancel
    // invalidates this revision; it must not revive or relabel the old request.
    MapleControl::Action TakeDispatch(std::uint64_t now) {
        dispatchPending = false;
        if (dispatched) repeated = true;
        dispatched = true;
        lastDispatch = now;
        return intent;
    }

    void NativeStarted(const MapleControl::Action& request, std::uint64_t revision, const NativeActionState& before,
                       const NativeActionState& after, bool admitted, bool nativeResultKnown = true) {
        if (revision != intentRevision) return;
        const bool started = admitted && before.idle != MapleControl::Fact::Unknown
                             && after.idle == MapleControl::Fact::False
                             && (before.idle == MapleControl::Fact::True || before.index != after.index);
        if (started) {
            nativeAction = request;
            nativeActionActive = true;
        }
        // Native success alone does not prove B replaced the still-visible A.
        // A successful no-new-lock skill is one use per hold, including when an
        // older A remains busy. Unknown attribution also stays conservative.
        if (request.skillId != 0 && admitted) repeatOnIdle = started;
        if (request.kind == MapleControl::ActionKind::Attack)
            retryUnstartedAttack = !started && (request.skillId == 0 || (nativeResultKnown && !admitted));
        ObserveAction(after);
    }

    void MovementChanged(std::uint32_t user) {
        movementUser = user;
        movementPending = true;
        movementReady = false;
        movementNeedsUpdate = movement.Active() || Any(movement.Owned());
    }

    bool HeldKeysSettled() const { return !movementPending && !movement.TransitionsPending(); }

    bool ActionIntentSettled() const {
        return !actionPending && !action.TransitionsPending() && !skill.Pending() && !item.Pending();
    }

    void MovementFlushed(std::uint32_t updatedCharacter, std::uint64_t characterUpdates, bool oldCharacterExited) {
        if (!movementPending || movement.TransitionsPending()) return;
        if (!movementReady) {
            movementAtUpdate = characterUpdates;
            movementReady = true;
        }
        if (!movementNeedsUpdate || oldCharacterExited
            || (updatedCharacter == movementUser && characterUpdates > movementAtUpdate))
            movementPending = false;
    }

    void ActionFlushed(std::uint32_t updatedCharacter, std::uint64_t characterUpdates, bool oldCharacterExited) {
        if (!actionPending || action.TransitionsPending() || dispatchPending || skill.Pending() || item.Pending())
            return;
        if (!actionReady) {
            actionAtUpdate = characterUpdates;
            actionReady = true;
        }
        if (oldCharacterExited || (updatedCharacter == actionUser && characterUpdates > actionAtUpdate))
            actionPending = false;
    }

    void ReleaseAction() {
        MapleControl::Action clear;
        if (!SetIntent(clear, actionUser)) {
            skill.Cancel("native_skill_cancelled");
            item.Cancel();
            if (action.Active()) action.Release();
        }
    }

    void Release(std::uint32_t user) {
        releaseNeedsUpdate = Any(movement.Owned()) || Any(action.Owned());
        ReleaseAction();
        releaseUser = user;
        releasePending = true;
        releaseReady = false;
        movement.Release();
        MovementChanged(user);
    }

    void Observe(std::uint32_t user, std::uint32_t updatedCharacter, std::uint64_t characterUpdates,
                 bool oldCharacterExited) {
        movement.ConfirmRelease(updatedCharacter, characterUpdates,
                                oldCharacterExited || user != movement.ReleaseCharacter());
        action.ConfirmRelease(updatedCharacter, characterUpdates,
                              oldCharacterExited || user != action.ReleaseCharacter());
        MovementFlushed(updatedCharacter, characterUpdates, oldCharacterExited || user != movementUser);
        ActionFlushed(updatedCharacter, characterUpdates, oldCharacterExited || user != actionUser);
        oldCharacterExited = oldCharacterExited || user != releaseUser;
        if (!releasePending || movement.TransitionsPending() || action.TransitionsPending()) return;
        if (!releaseReady) {
            releaseAtUpdate = characterUpdates;
            releaseReady = true;
        }
        if ((!releaseNeedsUpdate || oldCharacterExited
             || (user == releaseUser && updatedCharacter == releaseUser && characterUpdates > releaseAtUpdate))
            && action.Released() && ActionIntentSettled())
            releasePending = false;
    }

    // Held movement is a different producer. A started animation does not hold
    // this release fence: only actual input/pending native consumption does.
    bool Released() const {
        return !HasIntent() && action.Released() && !item.Pending() && !skill.Pending() && ActionIntentSettled()
               && !releasePending;
    }

    // Pending skill/item delivery is not itself cancellation. Only an explicit
    // clear/release may suppress the runtime's release request.
    bool ReleasePending() const { return releasePending || (!HasIntent() && actionPending); }

    MapleControl::ActionResult Result() const {
        auto value = result;
        value.dispatched = itemResult ? item.Dispatched()
                                      : action.Dispatched() || (value.skillRequested && value.skill.nativeResultKnown);
        value.controlReleased = Released();
        return value;
    }

private:
    static bool Any(const NativeKeyInput::Mask& mask) {
        return std::any_of(mask.begin(), mask.end(), [](bool held) { return held; });
    }

    void ActionChanged(std::uint32_t user) {
        actionUser = user;
        actionPending = true;
        actionReady = false;
    }

    MapleControl::Action intent;
    MapleControl::Action nativeAction;
    NativeActionState observedAction;
    std::uint64_t intentRevision = 0;
    std::uint64_t lastDispatch = 0;
    std::uint64_t lastItemDispatch = 0;
    bool haveItemDispatch = false;
    bool dispatchPending = false;
    bool dispatched = false;
    bool repeatOnIdle = true;
    bool retryUnstartedAttack = false;
    bool repeated = false;
    bool nativeActionActive = false;
    bool actionPending = false;
    bool actionReady = false;
    std::uint32_t actionUser = 0;
    std::uint64_t actionAtUpdate = 0;
    bool movementPending = false;
    bool movementReady = false;
    bool movementNeedsUpdate = false;
    std::uint32_t movementUser = 0;
    std::uint64_t movementAtUpdate = 0;
    bool releasePending = false;
    bool releaseReady = false;
    bool releaseNeedsUpdate = false;
    std::uint32_t releaseUser = 0;
    std::uint64_t releaseAtUpdate = 0;
};

}
