// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "FootholdTree.h"
#include "PhysicsObject.h"
#include "V17PhysicsParameters.h"

#include <cstdint>

namespace ms
{
// Runtime multipliers of the original field/character/foothold attribute objects.
// Normal-town defaults come from #237 A.2/B.1 constructor values; the field object
// values are the #237 G1 inference (1.0) pending dynamic read-only confirmation.
struct V17MotionMultipliers
{
	double mass = 100.0;            // C+0x0C (constructor value)
	double walkForceRatio = 1.0;    // C+0x18 (used when FM+0x18==1 and FM+0x24==0)
	double speedRatio = 1.0;        // C+0x24 = effective SPEED / 100
	double frictionRatio = 1.0;     // C+0x30
	double jumpRatio = 1.0;         // C+0x48 = effective JUMP / 100
	double fieldForce = 1.0;        // FA+0x00 (#237 G1 inference)
	double fieldDrag = 1.0;         // FA+0x0C (#237 G1 inference)
	double fieldGravity = 1.0;      // FA+0x24 (#237 G1 inference)
	double footholdSpeed = 1.0;     // FM+0x0C constructor default
	double footholdFriction = 1.0;  // FM+0x18 constructor default
	double footholdSpecial = 0.0;   // FM+0x24 constructor default (0 = ordinary branch)
};

// The held direction read once per motion commit. Jump/down-jump are edge latches
// owned by V17NormalMotion so a withdrawn input can never be consumed later.
struct V17MotionInput
{
	int direction = 0; // -1 left, 0 none, +1 right
};

// One whole 30ms local-character step end state.
struct V17MotionStep
{
	double previousX = 0.0;
	double previousY = 0.0;
	double x = 0.0;
	double y = 0.0;
	double vx = 0.0; // px/s, same-step world instantaneous speed
	double vy = 0.0;
	bool onGround = false;
	uint16_t footholdId = 0;
	double footholdSlope = 0.0;
	int8_t footholdLayer = 0;
	bool jumped = false;
	bool jumpedDown = false;
	bool landed = false;
	bool hitWall = false;
	bool stoppedAtEdge = false;
	bool leftGround = false;
	uint32_t stepMs = 30;
};

// The only owner of the local player's ordinary (STAND/WALK/FALL/PRONE) motion.
// Climbs/swim/fly keep the legacy per-8ms PhysicsObject path; ownership is handed
// over at the commit boundary via Suspend/ResumeFromProjection. PhysicsObject then
// only receives a centralized px/s -> px/8ms compatibility projection.
class V17NormalMotion
{
public:
	// Adopts an explicit physical state (respawn/reposition). Clears edge latches.
	void Reset(double x, double y, bool onGround, uint16_t footholdId);
	// Drains the attached PhysicsObject after a legacy mode hands the ownership back.
	void ResumeFromProjection(const PhysicsObject& projection);
	// Leaves the ordinary mode; the projection keeps the last committed end state.
	void Suspend();
	bool OwnsNormalState() const;

	// One-shot edge inputs recorded from native key-down; consumed or cleared by the
	// next motion commit, never carried across commits.
	void RequestJump();
	void RequestJumpDown();
	void ClearJumpRequests();
	bool HasPendingJump() const;
	bool HasPendingJumpDown() const;

	// Queue an external impulse for the next ordinary commit (original 0x7A6353):
	// clears pending jump, directional-limits both components into the pending
	// accumulator and never changes the current velocity immediately.
	void QueueImpulse(double vx, double vy);
	bool HasPendingImpulse() const;
	// Direct write used by branch-written velocities (ladder jump-off), not a hurt
	// impulse: the written state becomes one committed sample without integration.
	void ApplyImpulse(double vx, double vy);
	// Publishes the written state as one committed sample without integrating it.
	// Original ladder jump-off writes vx/vy and ends that 30ms update; the next
	// update performs the air integration (GUI sample 539 then 540).
	void CommitExternalWrite(uint32_t stepMs);
	void BeginRush(double targetX, uint16_t delayMs);
	void EndRush();
	bool Rushing() const;

	V17MotionStep Step(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
					   const V17MotionMultipliers& multipliers, const V17MotionInput& input,
					   bool jumpDownAllowed, double dt);
	// Centralized unit conversion: px/s -> legacy px/8ms and grounding projection.
	// Never read back from the projection afterwards.
	void Project(PhysicsObject& projection, const FootholdTree& terrain) const;

	const V17MotionStep& LastStep() const;
	bool HasSample() const;

	// Independent continuous reference model (stationary flat ground, normal mode).
	static double ReferenceWalkSpeed(const V17PhysicsParameters& parameters, const V17MotionMultipliers& multipliers);
	static double ReferenceJumpHeight(const V17PhysicsParameters& parameters, const V17MotionMultipliers& multipliers);

private:
	V17MotionStep StepGround(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
							 const V17MotionMultipliers& multipliers, const V17MotionInput& input, double dt);
	V17MotionStep StepAir(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
						  const V17MotionMultipliers& multipliers, const V17MotionInput& input, double dt);
	V17MotionStep DetachAndJump(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
								const V17MotionMultipliers& multipliers, const V17MotionInput& input, double dt);
	V17MotionStep DetachAndJumpDown(const FootholdTree& terrain, const V17PhysicsParameters& parameters,
									const V17MotionMultipliers& multipliers, double dt);
	double TangentCos() const;
	double TangentSin() const;
	static double MergeImpulseComponent(double current, double delta);

	V17MotionStep state;
	bool owns = false;
	bool pendingJump = false;
	bool pendingJumpDown = false;
	bool rushing = false;
	bool sample = false;
	bool pendingImpulse = false;
	double pendingImpulseX = 0.0;
	double pendingImpulseY = 0.0;
	double rushTargetX = 0.0;
	uint16_t rushDelayMs = 0;
	uint16_t dropThroughId = 0;
	double dropThroughY = 0.0;
};
}
