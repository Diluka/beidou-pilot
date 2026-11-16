// SPDX-License-Identifier: AGPL-3.0-or-later
#include "MotionPredictor.h"

#include <cmath>
#include <limits>

namespace MapleControl {
namespace {

bool Finite(double value) {
    return std::isfinite(value);
}

MotionPredictionState ToState(const ms::V17MotionStep& step) {
    return {step.x, step.y, step.vx, step.vy, step.onGround, step.footholdId, step.footholdSlope,
            step.footholdLayer};
}

} // namespace

MotionPredictor::MotionPredictor(const ms::FootholdTree& terrain, const ms::V17PhysicsParameters& parameters,
                                 const ms::V17MotionMultipliers& multipliers)
    : terrain(&terrain), parameters(&parameters), multipliers(multipliers) {}

bool MotionPredictor::SupportedCapabilities(std::string& error) const {
    if (!ms::V17PhysicsParameters::Available()) {
        error = "motion_parameters_unavailable";
        return false;
    }
    if (!Finite(multipliers.mass) || multipliers.mass <= 0.0 || !Finite(multipliers.speedRatio)
        || multipliers.speedRatio < 0.0 || !Finite(multipliers.jumpRatio) || multipliers.jumpRatio < 0.0
        || !Finite(multipliers.frictionRatio) || !Finite(multipliers.walkForceRatio)
        || !Finite(multipliers.fieldForce) || !Finite(multipliers.fieldDrag) || !Finite(multipliers.fieldGravity)
        || !Finite(multipliers.footholdSpeed) || !Finite(multipliers.footholdFriction)
        || !Finite(multipliers.footholdSpecial)) {
        error = "motion_capabilities_unsupported";
        return false;
    }
    if (multipliers.footholdSpecial != 0.0) {
        error = "motion_capabilities_unsupported_foothold_special";
        return false;
    }
    return true;
}

bool MotionPredictor::Reset(const MotionPredictionState& state, std::string& error) {
    error.clear();
    ready = false;
    if (!SupportedCapabilities(error)) return false;
    if (!Finite(state.x) || !Finite(state.y) || !Finite(state.vx) || !Finite(state.vy)) {
        error = "motion_state_invalid";
        return false;
    }

    ms::V17MotionStep value;
    value.x = state.x;
    value.y = state.y;
    value.vx = state.vx;
    value.vy = state.vy;
    value.onGround = state.onGround;
    value.footholdId = state.footholdId;
    value.footholdSlope = state.footholdSlope;
    value.footholdLayer = state.footholdLayer;
    if (state.onGround) {
        const auto foothold = terrain->GetFoothold(state.footholdId);
        if (!foothold.valid) {
            error = "motion_state_foothold_unknown";
            return false;
        }
        // Static terrain owns the contact geometry; an explicit state only
        // selects the foothold. This avoids accepting a stale or fabricated slope.
        value.footholdSlope = foothold.slope;
        value.footholdLayer = foothold.layer;
    } else {
        value.footholdSlope = 0.0;
        value.footholdLayer = 0;
    }
    motion.ResetState(value);
    current = ToState(value);
    ready = true;
    return true;
}

MotionPredictionStep MotionPredictor::Step(const MotionPredictionInput& input) {
    MotionPredictionStep result;
    result.before = current;
    result.after = current;
    if (!ready || input.direction < -1 || input.direction > 1) return result;
    // A down-jump without the environment granting it is a different action,
    // not a normal jump; report it as unsupported instead of silently consuming
    // the edge or turning it into a normal jump.
    if (input.jumpDown && !input.jumpDownAllowed) return result;

    motion.ClearJumpRequests();
    if (input.jump) motion.RequestJump();
    if (input.jumpDown) motion.RequestJumpDown();
    ms::V17MotionInput nativeInput;
    nativeInput.direction = input.direction;
    const auto step = motion.Step(*terrain, *parameters, multipliers, nativeInput, input.jumpDownAllowed,
                                  StepSeconds);
    result.progressed = true;
    result.after = ToState(step);
    result.stepMs = step.stepMs;
    result.jumped = step.jumped;
    result.jumpedDown = step.jumpedDown;
    result.landed = step.landed;
    result.leftGround = step.leftGround;
    result.hitWall = step.hitWall;
    result.stoppedAtEdge = step.stoppedAtEdge;
    current = result.after;
    return result;
}

MotionPredictionAdvance MotionPredictor::Advance(const MotionPredictionInput& input,
                                                  const MotionPredictionLimits& limits) {
    MotionPredictionAdvance result;
    if (!ready) return result;
    if (limits.maxSteps == 0) {
        result.stoppedByLimit = true;
        return result;
    }
    for (std::size_t index = 0; index < limits.maxSteps; ++index) {
        const auto step = Step(input);
        if (!step.progressed) break;
        result.steps += 1;
        result.progressed = true;
        result.last = step;
        if ((limits.stopOnLanded && step.landed) || (limits.stopOnLeftGround && step.leftGround)
            || (limits.stopOnHitWall && step.hitWall) || (limits.stopOnStoppedAtEdge && step.stoppedAtEdge)) {
            result.stoppedByCondition = true;
            break;
        }
    }
    result.stoppedByLimit = !result.stoppedByCondition && result.steps >= limits.maxSteps;
    return result;
}

} // namespace MapleControl
