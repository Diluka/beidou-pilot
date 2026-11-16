// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "V17NormalMotion.h"
#include "V17PhysicsParameters.h"

#include <cstdint>

namespace ms
{
// The attached rope/ladder geometry consumed by the original climb branch.
// top/bottom are the ladder object's +0x10/+0x14 fields (map y1/y2); exitsAtTop is
// the +0x08 flag. The map field mapping is the #250 inference documented in
// docs/V17_EXTENDED_MOTION_RULES.md §2: the GUI-recorded top exit on a rope with
// "l"=0 excludes l; page is never zero; "uf" is the only candidate field with
// zeros, so Ladder::exits_at_top() currently reads "uf". A direct GUI probe on a
// uf=0 top is still open and the branch must not be described as verified.
struct V17ClimbGeometry
{
	double x = 0.0;
	int16_t top = 0;
	int16_t bottom = 0;
	bool exitsAtTop = true;
};

struct V17ClimbStep
{
	double x = 0.0;
	double y = 0.0;
	bool attached = true;
	bool jumped = false;
	bool jumpDropped = false;
	bool exitedTop = false;
	bool exitedBottom = false;
	bool clampedAtTop = false;
	double vx = 0.0;
	double vy = 0.0;
};

// The original attached-climb branch (BeiDou.exe 0x9CC627): no mass, gravity,
// acceleration or trapezoid integration; one 30ms step moves y by inputY * 3.0
// and a pending jump with a horizontal input detaches with the 0x9B1D3D branch
// velocities. Only the ordinary (non-special) profile is implemented; the
// special 0.3 vertical factor and the fly/G4 gates are #254/#256 evidence.
class V17ClimbMotion
{
public:
	static constexpr double StepPixels = 3.0;

	static V17ClimbStep Step(const V17ClimbGeometry& geometry, double x, double y, int vertical, int horizontal,
							 bool jumpRequested, const V17PhysicsParameters& parameters,
							 const V17MotionMultipliers& multipliers);
};
}
