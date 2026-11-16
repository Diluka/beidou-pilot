// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Gameplay/Physics/FootholdTree.h"
#include "Gameplay/Physics/V17NormalMotion.h"
#include "Gameplay/Physics/V17PhysicsParameters.h"

#include <cstddef>
#include <cstdint>
#include <string>

namespace MapleControl {

// Explicit ordinary-motion state consumed and produced by the predictor. All
// fields are map pixels, pixels/second or static terrain values; the predictor
// never reads or writes the live character, game world or input slots.
struct MotionPredictionState
{
    double x = 0.0;
    double y = 0.0;
    double vx = 0.0;
    double vy = 0.0;
    bool onGround = false;
    std::uint16_t footholdId = 0;
    double footholdSlope = 0.0;
    std::int8_t footholdLayer = 0;
};

// One committed 30ms input sample. Jump and down-jump are edges for exactly one
// step; held direction is the ordinary direction key of the same step.
struct MotionPredictionInput
{
    int direction = 0; // -1 left, 0 none, +1 right
    bool jump = false;
    bool jumpDown = false;
    bool jumpDownAllowed = false;
};

struct MotionPredictionStep
{
    bool progressed = false;
    MotionPredictionState before;
    MotionPredictionState after;
    std::uint32_t stepMs = 0;
    bool jumped = false;
    bool jumpedDown = false;
    bool landed = false;
    bool leftGround = false;
    bool hitWall = false;
    bool stoppedAtEdge = false;
};

// A bounded advance over one fixed input. maxSteps is a hard limit; stop_* ask
// the caller's event of interest instead of making the first step the only API.
struct MotionPredictionLimits
{
    std::size_t maxSteps = 1;
    bool stopOnLanded = false;
    bool stopOnLeftGround = false;
    bool stopOnHitWall = false;
    bool stopOnStoppedAtEdge = false;
};

struct MotionPredictionAdvance
{
    std::size_t steps = 0;
    bool stoppedByCondition = false;
    bool stoppedByLimit = false;
    bool progressed = false;
    MotionPredictionStep last;
};

// Pure 30ms ordinary-motion prediction on explicit terrain. It reuses the same
// production V17 rule implementation as the headless local character and keeps
// no hidden global state beyond the caller-supplied parameters and multipliers.
class MotionPredictor
{
public:
    static constexpr double StepSeconds = 0.030;

    MotionPredictor(const ms::FootholdTree& terrain, const ms::V17PhysicsParameters& parameters,
                    const ms::V17MotionMultipliers& multipliers);

    // Adopts an explicit physical state. A ground state needs a valid foothold
    // id; slope/layer are taken from the static terrain, never guessed. Air
    // states may keep a stale foothold id but slope/layer are left unused.
    bool Reset(const MotionPredictionState& state, std::string& error);

    bool Ready() const { return ready; }
    const MotionPredictionState& State() const { return current; }

    // One 30ms step. A non-finite direction, an unsupported down-jump request or
    // a predictor that was not Reset returns progressed=false and changes no state.
    MotionPredictionStep Step(const MotionPredictionInput& input);

    // Steps the same input until a caller condition or maxSteps. Physical time
    // only advances on progressed steps; no step is replayed by a later resume.
    MotionPredictionAdvance Advance(const MotionPredictionInput& input, const MotionPredictionLimits& limits);

private:
    bool SupportedCapabilities(std::string& error) const;

    const ms::FootholdTree* terrain;
    const ms::V17PhysicsParameters* parameters;
    ms::V17MotionMultipliers multipliers;
    ms::V17NormalMotion motion;
    MotionPredictionState current;
    bool ready = false;
};

} // namespace MapleControl
