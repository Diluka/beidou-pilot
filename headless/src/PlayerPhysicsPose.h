// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"
#include "Gameplay/Physics/PhysicsObject.h"

#include <cstdint>

namespace ms {
// The local player's current physical end state for one host step. SharedLuaAdapter
// captures it after every world update; the offline motion contract compiles this
// same helper against the real PhysicsObject, so the unknown-velocity conditions
// are not reimplemented in a test fixture.
//
// x/y are the unrounded foot point. The legacy integrator stores per-step
// displacement, so a same-step instantaneous world speed exists only while no
// other code corrects the same coordinate: on slopes update_fh writes y directly,
// and climbing/underwater states own their own motion. Those cases keep velocity
// unknown instead of converting a per-step number into a fabricated px/s value.
//
// updateId is the current host tick, not a character motion-commit number; the
// 30ms local motion step and its real update identity arrive with the follow-up
// motion task. stepMs is the simulated integration time of this sample (8ms).
inline MapleControl::PhysicsPose PlayerPhysicsPose(const PhysicsObject& phobj, bool climbing, bool underwater,
                                                   std::uint64_t updateId, std::uint32_t stepMs) {
    MapleControl::PhysicsPose pose;
    pose.known = true;
    pose.updateIdKnown = true;
    pose.updateId = updateId;
    pose.stepMsKnown = true;
    pose.stepMs = stepMs;
    pose.positionKnown = true;
    pose.x = phobj.crnt_x();
    pose.y = phobj.crnt_y();
    pose.onGround = phobj.onground ? MapleControl::Fact::True : MapleControl::Fact::False;
    if (stepMs != 0 && phobj.type == PhysicsObject::Type::NORMAL && phobj.fhslope == 0.0 && !climbing && !underwater) {
        const double perSecond = 1000.0 / stepMs;
        pose.velocityKnown = true;
        pose.velocityX = phobj.hspeed * perSecond;
        pose.velocityY = phobj.vspeed * perSecond;
    }
    return pose;
}
}
