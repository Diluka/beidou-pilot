// SPDX-License-Identifier: AGPL-3.0-or-later
#include "V17NormalMotion.h"

#include <algorithm>
#include <cmath>

namespace ms {
namespace {
constexpr double LEGACY_STEPS_PER_SECOND = 125.0; // 1000.0 / Constants::TIMESTEP
constexpr double DOWN_JUMP_IMPULSE = -0.35355339;

// Original force/velocity helper 0x9B2BCB: v += force/mass*dt, clamped in the
// force's own direction to +/-limit. It does not drag an out-of-range start back.
double Accelerate(double v, double force, double mass, double limit, double dt) {
    if (limit < 0.0 || mass == 0.0) return v;

    if (force > 0.0) {
        if (v >= limit) return v;

        v += force / mass * dt;
        return std::min(v, limit);
    }

    if (v <= -limit) return v;

    v += force / mass * dt;
    return std::max(v, -limit);
}

double DecayToZero(double v, double accel, double dt) {
    if (v > 0.0) return std::max(0.0, v - accel * dt);

    if (v < 0.0) return std::min(0.0, v + accel * dt);

    return 0.0;
}

struct Tangent {
    double cos = 1.0;
    double sin = 0.0;
};

Tangent TangentFor(double slope) {
    const double length = std::sqrt(1.0 + slope * slope);
    return {1.0 / length, slope / length};
}
}

void V17NormalMotion::Reset(double x, double y, bool onGround, uint16_t footholdId) {
    pendingImpulse = false;
    pendingImpulseX = 0.0;
    pendingImpulseY = 0.0;
    state = {};
    state.x = x;
    state.y = y;
    state.onGround = onGround;
    state.footholdId = footholdId;
    owns = true;
    pendingJump = pendingJumpDown = false;
    rushing = false;
    sample = false;
    dropThroughId = 0;
    dropThroughY = 0.0;
}

void V17NormalMotion::ResumeFromProjection(const PhysicsObject& projection) {
    state = {};
    state.x = projection.crnt_x();
    state.y = projection.crnt_y();
    state.vx = projection.hspeed * LEGACY_STEPS_PER_SECOND;
    state.vy = projection.vspeed * LEGACY_STEPS_PER_SECOND;
    state.onGround = projection.onground;
    state.footholdId = projection.fhid;
    state.footholdSlope = projection.fhslope;
    state.footholdLayer = projection.fhlayer;
    owns = true;
    pendingJump = pendingJumpDown = false;
    rushing = false;
    sample = false;
    dropThroughId = 0;
    dropThroughY = 0.0;
}

void V17NormalMotion::Suspend() {
    owns = false;
    pendingJump = pendingJumpDown = false;
    rushing = false;
    sample = false;
    dropThroughId = 0;
}

bool V17NormalMotion::OwnsNormalState() const {
    return owns;
}

void V17NormalMotion::RequestJump() {
    pendingJump = true;
    pendingJumpDown = false;
}

void V17NormalMotion::RequestJumpDown() {
    pendingJumpDown = true;
    pendingJump = false;
}

void V17NormalMotion::ClearJumpRequests() {
    pendingJump = pendingJumpDown = false;
}

bool V17NormalMotion::HasPendingJump() const {
    return pendingJump || pendingJumpDown;
}

bool V17NormalMotion::HasPendingJumpDown() const {
    return pendingJumpDown;
}

void V17NormalMotion::ApplyImpulse(double vx, double vy) {
    state.vx = vx;
    state.vy = vy;
}

double V17NormalMotion::MergeImpulseComponent(double current, double delta) {
    // 0x7A6353/0x9B222A directional limit: an opposite-direction impulse only cancels
    // up to zero and cannot reverse an existing larger same-direction speed.
    if (delta < 0.0 && current > delta) return std::max(delta, current + delta);
    if (delta > 0.0 && current < delta) return std::min(delta, current + delta);
    return current;
}

void V17NormalMotion::QueueImpulse(double vx, double vy) {
    // 0x9591CA only calls 0x7A6353 when the computed impulse is not all zero; an
    // all-zero impulse neither queues nor clears the pending jump latch.
    if (vx == 0.0 && vy == 0.0) return;
    ClearJumpRequests();
    if (!pendingImpulse) {
        pendingImpulseX = 0.0;
        pendingImpulseY = 0.0;
        pendingImpulse = true;
    }
    pendingImpulseX = MergeImpulseComponent(pendingImpulseX, vx);
    pendingImpulseY = MergeImpulseComponent(pendingImpulseY, vy);
}

bool V17NormalMotion::HasPendingImpulse() const {
    return pendingImpulse;
}
void V17NormalMotion::CommitExternalWrite(uint32_t stepMs) {
    state.stepMs = stepMs;
    state.jumped = false;
    state.jumpedDown = false;
    state.landed = false;
    state.hitWall = false;
    state.stoppedAtEdge = false;
    state.leftGround = false;
    sample = true;
}

void V17NormalMotion::BeginRush(double targetX, uint16_t delayMs) {
    rushTargetX = targetX;
    rushDelayMs = delayMs;
    state.vx = delayMs ? 1000.0 * (targetX - state.x) / static_cast<double>(delayMs) : 0.0;
    rushing = true;
}

void V17NormalMotion::EndRush() {
    rushing = false;
}

bool V17NormalMotion::Rushing() const {
    return rushing;
}

double V17NormalMotion::TangentCos() const {
    return TangentFor(state.footholdSlope).cos;
}

double V17NormalMotion::TangentSin() const {
    return TangentFor(state.footholdSlope).sin;
}

V17MotionStep V17NormalMotion::Step(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
                                    const V17MotionMultipliers& multipliers, const V17MotionInput& input,
                                    bool jumpDownAllowed, double dt) {
    const V17MotionStep previous = state;

    // Per-step transient facts never leak into the next commit.
    state.jumped = false;
    state.jumpedDown = false;
    state.landed = false;
    state.hitWall = false;
    state.stoppedAtEdge = false;
    state.leftGround = false;

    // 0x9B222A: a queued impulse is consumed before this commit's integration. It
    // detaches the foothold first, merges into the world velocity with the same
    // directional limit and truncates both components toward zero (0xA62018 RC=11).
    if (pendingImpulse) {
        const double impulseX = pendingImpulseX;
        const double impulseY = pendingImpulseY;
        pendingImpulse = false;
        pendingImpulseX = 0.0;
        pendingImpulseY = 0.0;
        state.onGround = false;
        state.footholdId = 0;
        state.footholdSlope = 0.0;
        state.footholdLayer = 0;
        state.vx = std::trunc(MergeImpulseComponent(state.vx, impulseX));
        state.vy = std::trunc(MergeImpulseComponent(state.vy, impulseY));
    }

    // Attach a freshly respawned/repositioned foot point (onGround with no foothold).
    if (state.onGround && state.footholdId == 0) {
        const GroundHit hit = terrain.QueryGroundBelow(state.x, state.y - 1.0, 2.0);

        if (hit.found) {
            state.y = hit.groundY;
            state.footholdId = hit.footholdId;
            state.footholdSlope = hit.slope;
            state.footholdLayer = hit.layer;
        } else {
            state.onGround = false;
        }
    }

    if (dropThroughId && state.y > dropThroughY + 1.0) dropThroughId = 0;

    const bool jumpRequested = pendingJump;
    const bool jumpDownRequested = pendingJumpDown;
    pendingJump = pendingJumpDown = false;

    V17MotionStep next;

    if (state.onGround && state.footholdId && jumpDownRequested && jumpDownAllowed)
        next = DetachAndJumpDown(terrain, parameters, multipliers, dt);
    else if (state.onGround && state.footholdId && jumpRequested)
        next = DetachAndJump(terrain, parameters, multipliers, input, dt);
    else if (state.onGround)
        next = StepGround(terrain, parameters, multipliers, input, dt);
    else
        next = StepAir(terrain, parameters, multipliers, input, dt);

    // A jump/down-jump request that could not be consumed at this commit is dropped:
    // it is a current intent, never a queued action for a later step.
    next.previousX = previous.x;
    next.previousY = previous.y;
    next.stepMs = static_cast<uint32_t>(std::lround(dt * 1000.0));
    next.landed = !previous.onGround && next.onGround;
    next.leftGround = previous.onGround && !next.onGround;

    state = next;
    sample = true;
    return state;
}

V17MotionStep V17NormalMotion::StepGround(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
                                          const V17MotionMultipliers& multipliers, const V17MotionInput& input,
                                          double dt) {
    V17MotionStep next = state;
    const Tangent tangent = TangentFor(state.footholdSlope);
    const double cosine = tangent.cos;
    const double sine = tangent.sin;
    const double mass = multipliers.mass;
    const double oldTangent = state.vx * cosine + state.vy * sine;
    double tangentSpeed = oldTangent;

    // #237 D.2: force ratio only uses the character attribute on default foothold
    // material; otherwise the temporary 1.0 object is used (special branch not modeled).
    const double forceRatio =
        (multipliers.footholdFriction == 1.0 && multipliers.footholdSpecial == 0.0) ? multipliers.walkForceRatio : 1.0;
    const double walkForce = parameters.walkForce() * multipliers.footholdSpeed * forceRatio * multipliers.fieldForce
                             * multipliers.specialGroundFactor;
    const double frictionBase = multipliers.fieldDrag * multipliers.frictionRatio * multipliers.footholdFriction;
    double friction = std::clamp(frictionBase, parameters.minFriction(), parameters.maxFriction());

    if (friction < 1.0) friction *= 0.5;

    const double brakeForce = friction != 0.0 ? friction * parameters.walkDrag() : parameters.walkDrag() * 0.2;
    const double brake = mass != 0.0 ? brakeForce / mass : 0.0;
    const double maxSpeed =
        parameters.walkSpeed() * multipliers.footholdSpeed * multipliers.speedRatio * multipliers.specialGroundFactor;

    if (rushing)
        tangentSpeed = oldTangent;
    else if (input.direction == 0)
        tangentSpeed = DecayToZero(oldTangent, brake, dt);
    else {
        // Any non-zero input applies the input-direction walk force: a reverse input
        // accelerates through zero by 1400px/s^2, it is not the release brake.
        tangentSpeed = oldTangent + input.direction * walkForce / mass * dt;

        if (input.direction * tangentSpeed > maxSpeed) tangentSpeed = input.direction * maxSpeed;
    }

    next.vx = tangentSpeed * cosine;
    next.vy = tangentSpeed * sine;

    const double dx = (state.vx + next.vx) * 0.5 * dt;
    const double dy = (state.vy + next.vy) * 0.5 * dt;
    LocalSweepInput sweep;
    sweep.x = state.x;
    sweep.y = state.y;
    sweep.dx = dx;
    sweep.dy = dy;
    sweep.vx = next.vx;
    sweep.vy = next.vy;
    sweep.footholdId = state.footholdId;
    sweep.onGround = true;
    sweep.stopAtEdges = rushing;
    const LocalSweepResult result = terrain.SweepLocalMotion(sweep);

    next.x = result.x;
    next.y = result.y;
    next.vx = result.vx;
    next.vy = result.vy;
    next.onGround = result.onGround;
    next.footholdId = result.footholdId;
    next.footholdSlope = result.footholdSlope;
    next.footholdLayer = result.footholdLayer;
    next.hitWall = result.hitWall;
    next.stoppedAtEdge = result.stoppedAtEdge;

    if (rushing) {
        const bool crossed =
            (rushTargetX >= state.x && result.x >= rushTargetX) || (rushTargetX <= state.x && result.x <= rushTargetX);

        if (result.hitWall || !result.onGround || crossed) {
            EndRush();
            next.vx = 0.0;
            next.vy = 0.0;
        }
    }

    return next;
}

V17MotionStep V17NormalMotion::StepAir(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
                                       const V17MotionMultipliers& multipliers, const V17MotionInput& input,
                                       double dt) {
    V17MotionStep next = state;
    const double mass = multipliers.mass;
    const double oldVx = state.vx;
    const double oldVy = state.vy;

    // #237 D.4: the ordinary falling branch. The G3 instant-jump-flag rewrite and
    // the special/flying branches are not modeled; normal profile assumes they miss.
    const double fallLimit = parameters.fallSpeed() * multipliers.fieldGravity;
    double vy = oldVy + parameters.gravityAcc() * multipliers.fieldGravity * dt;

    if (vy > fallLimit) vy = fallLimit;

    const double drag2 = multipliers.fieldDrag * parameters.floatDrag2();
    double vx;

    if (input.direction != 0) {
        const double force = input.direction * 2.0 * drag2;
        const double limit =
            parameters.walkForce() != 0.0 ? parameters.walkSpeed() / parameters.walkForce() * drag2 : 0.0;
        vx = Accelerate(oldVx, force, mass, limit, dt);
    } else {
        const double force = vy < fallLimit ? drag2 * parameters.floatCoefficient() : drag2;
        vx = DecayToZero(oldVx, mass != 0.0 ? force / mass : 0.0, dt);
    }

    next.vx = vx;
    next.vy = vy;

    const double dx = (oldVx + vx) * 0.5 * dt;
    const double dy = (oldVy + vy) * 0.5 * dt;
    LocalSweepInput sweep;
    sweep.x = state.x;
    sweep.y = state.y;
    sweep.dx = dx;
    sweep.dy = dy;
    sweep.vx = vx;
    sweep.vy = vy;
    sweep.footholdId = 0;
    sweep.onGround = false;
    sweep.ignoreFootholdId = dropThroughId;
    const LocalSweepResult result = terrain.SweepLocalMotion(sweep);

    next.x = result.x;
    next.y = result.y;
    next.vx = result.vx;
    next.vy = result.vy;
    next.onGround = result.onGround;
    next.footholdId = result.footholdId;
    next.footholdSlope = result.footholdSlope;
    next.footholdLayer = result.footholdLayer;
    next.landed = result.landed;
    next.hitWall = result.hitWall;

    if (result.landed || result.onGround) dropThroughId = 0;

    return next;
}

V17MotionStep V17NormalMotion::DetachAndJump(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
                                             const V17MotionMultipliers& multipliers, const V17MotionInput& input,
                                             double dt) {
    const FootholdInfo foothold = terrain.GetFoothold(state.footholdId);
    const Tangent tangent = TangentFor(state.footholdSlope);
    // #237 D.5: only the local *position* is clamped to [0, foothold length] before
    // projection; the local *speed* keeps its sign and magnitude. Clamping the
    // tangent speed collapsed a leftward run-up to zero and then the boost produced
    // -0.8*Vmax for a leftward jump (caught in the GUI/headless dual-end comparison).
    const double tangentSpeed = state.vx * tangent.cos + state.vy * tangent.sin;

    V17MotionStep detached = state;
    detached.vx = tangentSpeed * tangent.cos;
    detached.vy = tangentSpeed * tangent.sin;

    if (foothold.valid)
        detached.x = std::clamp(detached.x, static_cast<double>(std::min(foothold.x1, foothold.x2)),
                                static_cast<double>(std::max(foothold.x1, foothold.x2)));

    detached.y = std::floor(detached.y - 1.0); // #237 D.5 step 4: floor(y-1)
    detached.footholdId = 0;
    detached.onGround = false;
    detached.footholdSlope = 0.0;
    detached.footholdLayer = 0;
    detached.vy = -parameters.jumpSpeed() * multipliers.jumpRatio / multipliers.fieldGravity;

    if (input.direction != 0 && foothold.valid) {
        const double directionAdjustment = input.direction * tangent.sin < 0.0 ? -1.0 : 1.0;
        const double maxSpeed = parameters.walkSpeed() * multipliers.footholdSpeed * multipliers.speedRatio
                                * (1.0 + tangent.sin * tangent.sin * directionAdjustment);

        if (input.direction * detached.vx < 0.8 * maxSpeed) detached.vx += input.direction * 0.8 * maxSpeed;

        if (input.direction * detached.vx > maxSpeed) detached.vx = input.direction * maxSpeed;
    }

    state = detached;
    dropThroughId = 0;
    V17MotionStep next = StepAir(terrain, parameters, multipliers, input, dt);
    next.jumped = true;
    return next;
}

V17MotionStep V17NormalMotion::DetachAndJumpDown(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
                                                 const V17MotionMultipliers& multipliers, double dt) {
    const FootholdInfo foothold = terrain.GetFoothold(state.footholdId);
    const double groundY = state.y;

    if (foothold.valid) {
        dropThroughId = foothold.id;
        dropThroughY = terrain.GroundBelow(state.x, foothold);
    } else {
        dropThroughId = 0;
        dropThroughY = groundY;
    }

    V17MotionStep detached = state;

    if (foothold.valid)
        detached.x = std::clamp(detached.x, static_cast<double>(std::min(foothold.x1, foothold.x2)),
                                static_cast<double>(std::max(foothold.x1, foothold.x2)));

    detached.y = std::floor(detached.y - 1.0);
    detached.footholdId = 0;
    detached.onGround = false;
    detached.footholdSlope = 0.0;
    detached.footholdLayer = 0;
    detached.vx = 0.0;
    detached.vy = DOWN_JUMP_IMPULSE * parameters.jumpSpeed() * multipliers.jumpRatio / multipliers.fieldGravity;

    state = detached;
    V17MotionStep next = StepAir(terrain, parameters, multipliers, V17MotionInput{}, dt);
    next.jumpedDown = true;
    return next;
}

void V17NormalMotion::Project(PhysicsObject& projection, const FootholdTree& terrain) const {
    projection.type = PhysicsObject::Type::NORMAL;
    projection.x = state.x;
    projection.y = state.y;
    projection.hspeed = state.vx / LEGACY_STEPS_PER_SECOND;
    projection.vspeed = state.vy / LEGACY_STEPS_PER_SECOND;
    projection.onground = state.onGround;
    projection.fhid = state.footholdId;
    projection.fhslope = state.footholdSlope;
    projection.fhlayer = state.footholdLayer;
    projection.clear_flag(PhysicsObject::Flag::CHECKBELOW);

    double groundbelow = 0.0;

    if (state.onGround && terrain.JumpDownAvailable(state.x, state.y, groundbelow)) {
        projection.enablejd = true;
        projection.groundbelow = groundbelow;
    } else {
        projection.enablejd = false;
        projection.groundbelow = state.y + 1.0;
    }
}

const V17MotionStep& V17NormalMotion::LastStep() const {
    return state;
}

bool V17NormalMotion::HasSample() const {
    return sample;
}

double V17NormalMotion::ReferenceWalkSpeed(const V17PhysicsParameters& parameters,
                                           const V17MotionMultipliers& multipliers) {
    return parameters.walkSpeed() * multipliers.footholdSpeed * multipliers.speedRatio;
}

double V17NormalMotion::ReferenceJumpHeight(const V17PhysicsParameters& parameters,
                                            const V17MotionMultipliers& multipliers) {
    const double gravity = parameters.gravityAcc() * multipliers.fieldGravity;

    if (gravity <= 0.0) return 0.0;

    const double launch = parameters.jumpSpeed() * multipliers.jumpRatio / multipliers.fieldGravity;
    return launch * launch / (2.0 * gravity);
}
}
