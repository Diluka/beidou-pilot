// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "NativeKeyInput.h"
#include "NativeItemUse.h"
#include "NativeSkillUse.h"

namespace BeiDouBridge {

// Tick-only I/O lifecycle. It contains no coroutine adapter state or scheduler.
// Movement and the one-shot action are independent producers of native input.
struct NativeTickInput {
    NativeKeyInput movement;
    NativeKeyInput action;
    NativeItemUse item;
    NativeSkillUse skill;
    MapleControl::ActionResult result;
    bool itemResult = false;
    bool actionWindow = false;
    std::uint64_t actionUntil = 0;

    void ExpireAction(std::uint64_t now) {
        if (!actionWindow || now < actionUntil) return;
        actionWindow = false;
        skill.Cancel("native_skill_expired");
        if (result.skillRequested) result.skill = skill.Result();
        action.Release();
    }

    void MovementChanged(std::uint32_t user) {
        movementUser = user;
        movementPending = true;
        movementReady = false;
        movementNeedsUpdate = movement.Active() || Any(movement.Owned());
    }

    bool HeldKeysSettled() const { return !movementPending && !movement.TransitionsPending(); }

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

    void ReleaseAction() {
        actionWindow = false;
        skill.Cancel("native_skill_cancelled");
        if (result.skillRequested) result.skill = skill.Result();
        item.Cancel();
        actionReleasePending = true;
        action.Release();
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
        if (action.Released()) actionReleasePending = false;
        MovementFlushed(updatedCharacter, characterUpdates, oldCharacterExited || user != movementUser);
        oldCharacterExited = oldCharacterExited || user != releaseUser;
        if (!releasePending || movement.TransitionsPending() || action.TransitionsPending()) return;
        if (!releaseReady) {
            releaseAtUpdate = characterUpdates;
            releaseReady = true;
        }
        if ((!releaseNeedsUpdate || oldCharacterExited
             || (user == releaseUser && updatedCharacter == releaseUser && characterUpdates > releaseAtUpdate))
            && action.Released())
            releasePending = false;
    }

    // Deliberately ignores held movement. A full Release has a separate fence,
    // so restoring another tick session's movement does not lose the release
    // acknowledgement or get cleared when asynchronous cleanup completes.
    bool Released() const {
        return !actionWindow && action.Released() && !item.Pending() && !skill.Pending() && !releasePending;
    }

    // An ordinary action's pulse keyup is not cancellation of the enclosing
    // action (a pending native skill may have no key at all). Only explicit
    // adapter cancellation may suppress another Release requested by runtime.
    bool ReleasePending() const { return releasePending || actionReleasePending; }

    MapleControl::ActionResult Result() const {
        auto value = result;
        value.dispatched = itemResult ? item.Dispatched()
                                      : action.Dispatched() || (value.skillRequested && value.skill.nativeResultKnown);
        value.controlReleased = Released();
        if (value.dispatched && value.reason == "native_action_requested") value.reason = "native_action_dispatched";
        return value;
    }

private:
    static bool Any(const NativeKeyInput::Mask& mask) {
        return std::any_of(mask.begin(), mask.end(), [](bool held) { return held; });
    }

    bool movementPending = false;
    bool movementReady = false;
    bool movementNeedsUpdate = false;
    std::uint32_t movementUser = 0;
    std::uint64_t movementAtUpdate = 0;
    bool actionReleasePending = false;
    bool releasePending = false;
    bool releaseReady = false;
    bool releaseNeedsUpdate = false;
    std::uint32_t releaseUser = 0;
    std::uint64_t releaseAtUpdate = 0;
};

}
