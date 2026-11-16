// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Character/Player.h"
#include "Contract.h"

namespace ms {
// The local player's physical end state for one real character motion commit.
// SharedLuaAdapter captures it after every world update; the offline contracts
// compile this same helper against the real Player, so the unknown-velocity and
// step-time conditions are not reimplemented in a test fixture.
//
// x/y are the unrounded physical foot point and velocity is the same-step world
// instantaneous speed. Once the ordinary 30ms motion owns the state, both come
// from the canonical V17 state; legacy climb/swim/fly steps keep the per-8ms
// displacement engine and report no instantaneous velocity. A sit/dead state has
// no motion sample at all until motion resumes, so the whole record stays unknown.
inline MapleControl::PhysicsPose PlayerPhysicsPose(const Player& player) {
    MapleControl::PhysicsPose pose;
    pose.updateIdKnown = true;
    pose.updateId = player.get_motion_commit_id();
    pose.stepMsKnown = player.get_last_motion_step_ms() != 0;
    pose.stepMs = player.get_last_motion_step_ms();
    if (!pose.stepMsKnown) {
        // No motion sample has been committed since the last discontinuous boundary:
        // fill no physical facts instead of reusing a stale sample.
        return pose;
    }

    pose.known = true;
    pose.positionKnown = true;
    const auto& projection = player.get_phobj();
    pose.x = projection.crnt_x();
    pose.y = projection.crnt_y();
    pose.onGround = projection.onground ? MapleControl::Fact::True : MapleControl::Fact::False;

    const V17NormalMotion& motion = player.get_motion_state();
    if (motion.OwnsNormalState()) {
        const V17MotionStep& step = motion.LastStep();
        pose.x = step.x;
        pose.y = step.y;
        pose.onGround = step.onGround ? MapleControl::Fact::True : MapleControl::Fact::False;
        pose.velocityKnown = motion.HasSample();
        pose.velocityX = step.vx;
        pose.velocityY = step.vy;
    }
    return pose;
}
}
