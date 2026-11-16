// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "../Gameplay/Movement.h"
#include "MovePlayerBounds.h"

#include <cstdint>
#include <vector>

namespace ms
{
// V17 MovePlayer path recorder (docs/V17_EXTENDED_MOTION_RULES.md §10):
// - 0x68AB85 appends the step duration and tries to merge absolute command 0/15/17
//   fragments when command/foothold/state match and both velocity words keep their
//   positive/negative/zero sign category; merged nodes take the newest endpoint and
//   velocity while durations accumulate (0x68AC0F-0x68ACF9).
// - The send gate 0x68A828 uses a 500ms threshold when path+0x40 is non-zero (the
//   captured local-player packets were 510ms), otherwise 1000ms. The local player
//   path mode is not exposed in headless, so this recorder uses the observed 500ms.
class MovePlayerPath
{
public:
	static constexpr uint32_t SendThresholdMs = 500;

	void Reset(Point<int16_t> newStart)
	{
		start = newStart;
		fragments.clear();
		directions.clear();
		durationMs = 0;
	}

	void Append(uint32_t stepMs, const Movement& fragment, uint8_t directionNibble)
	{
		durationMs += stepMs;
		directions.push_back(directionNibble);

		if (!fragments.empty())
		{
			Movement& last = fragments.back();
			if (last.command == fragment.command && last.fh == fragment.fh
				&& last.newstate == fragment.newstate && SameSignCategory(last.lastx, fragment.lastx)
				&& SameSignCategory(last.lasty, fragment.lasty))
			{
				last.xpos = fragment.xpos;
				last.ypos = fragment.ypos;
				last.lastx = fragment.lastx;
				last.lasty = fragment.lasty;
				last.duration = static_cast<int16_t>(last.duration + stepMs);
				return;
			}
		}

		Movement node = fragment;
		node.duration = static_cast<int16_t>(stepMs);
		fragments.push_back(node);
	}

	bool ShouldSend() const { return durationMs >= SendThresholdMs; }

	const Point<int16_t>& StartPoint() const { return start; }
	const std::vector<Movement>& Fragments() const { return fragments; }
	const std::vector<uint8_t>& Directions() const { return directions; }
	uint32_t DurationMs() const { return durationMs; }

	MovePlayerBounds Bounds() const
	{
		MovePlayerBounds bounds;
		if (fragments.empty())
		{
			bounds = MovePlayerPathBounds(start, start);
			return bounds;
		}

		const Movement& first = fragments.front();
		bounds = MovePlayerPathBounds(start, Point<int16_t>(first.xpos, first.ypos));
		for (const Movement& fragment : fragments)
		{
			bounds.minX = std::min(bounds.minX, fragment.xpos);
			bounds.minY = std::min(bounds.minY, fragment.ypos);
			bounds.maxX = std::max(bounds.maxX, fragment.xpos);
			bounds.maxY = std::max(bounds.maxY, fragment.ypos);
		}
		return bounds;
	}

	// After a send the next path starts at the last committed endpoint.
	Point<int16_t> LastEndpoint() const
	{
		if (fragments.empty()) return start;
		const Movement& last = fragments.back();
		return Point<int16_t>(last.xpos, last.ypos);
	}

private:
	static bool SameSignCategory(int16_t a, int16_t b)
	{
		if (a > 0) return b > 0;
		if (a < 0) return b < 0;
		return b == 0;
	}

	Point<int16_t> start;
	std::vector<Movement> fragments;
	std::vector<uint8_t> directions;
	uint32_t durationMs = 0;
};
}
