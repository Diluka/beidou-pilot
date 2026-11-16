// SPDX-License-Identifier: AGPL-3.0-or-later
#include "V17ClimbMotion.h"

#include <algorithm>

namespace ms
{
	V17ClimbStep V17ClimbMotion::Step(const V17ClimbGeometry& geometry, double x, double y, int vertical,
									  int horizontal, bool jumpRequested, const V17PhysicsParameters& parameters,
									  const V17MotionMultipliers& multipliers)
	{
		V17ClimbStep step;
		step.x = x;
		step.y = y;

		// 0x9CC634-0x9CC6C6: a pending jump is handled before the climb movement.
		// 0x9B1D3D returns without detaching when there is no horizontal input.
		if (jumpRequested)
		{
			if (horizontal == 0)
			{
				step.jumpDropped = true;
			}
			else
			{
				step.jumped = true;
				step.attached = false;
				step.vx = horizontal * multipliers.speedRatio * parameters.walkSpeed() * 1.3;
				step.vy = -(parameters.jumpSpeed() * multipliers.jumpRatio / multipliers.fieldGravity) * 0.5;
				return step;
			}
		}

		// 0x9CC6CC-0x9CC70E: y += inputY * K, K = double[0xAF3728] = 3.0, followed by
		// the asymmetric top/bottom exits at 0x9CC727-0x9CC7D5.
		if (vertical < 0)
		{
			y -= StepPixels;

			if (y < static_cast<double>(geometry.top))
			{
				if (geometry.exitsAtTop)
				{
					y = static_cast<double>(geometry.top) - 5.0;
					step.attached = false;
					step.exitedTop = true;
				}
				else
				{
					y = static_cast<double>(geometry.top);
					step.clampedAtTop = true;
				}
			}
		}
		else if (vertical > 0)
		{
			y += StepPixels;

			if (y > static_cast<double>(geometry.bottom))
			{
				y = static_cast<double>(geometry.bottom) + 1.0;
				step.attached = false;
				step.exitedBottom = true;
			}
		}

		step.x = x;
		step.y = y;
		return step;
	}
}
