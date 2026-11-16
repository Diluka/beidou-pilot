// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Movement.h"
#include "Template/Point.h"

#include <cstdint>
#include <vector>

namespace ms
{
// Plays back an inbound V17 movement path with the original duration semantics
// (docs/V17_EXTENDED_MOTION_RULES.md §10): each command carries a duration and an
// endpoint position/velocity; unfinished segments use cubic Hermite interpolation
// with the endpoint position/velocity constraints. Random AI decisions are not
// reproduced; this only consumes the path the controller sent.
class MovementReplay
{
public:
	struct Sample
	{
		double x = 0.0;
		double y = 0.0;
		int16_t vx = 0;
		int16_t vy = 0;
		uint16_t fh = 0;
		uint8_t state = 0;
		bool finished = false;
	};

	void Reset(Point<int16_t> start, std::vector<Movement>&& fragments);
	bool Empty() const { return index >= segments.size(); }
	// Remaining buffered path time in milliseconds.
	int32_t RemainingMs() const;
	// Original catch-up selection: a buffered path advances 33ms per step while the
	// buffer is above (1000*1.1)ms, otherwise 30ms. The mode-dependent 500ms variant
	// is not reproduced because the mode producer is still unknown.
	uint16_t StepMs() const;
	// Buffers above threshold+5000ms are dropped to the current endpoint snapshot.
	bool NeedsSnapshot() const;
	Sample Advance(uint16_t stepMs);
	const Sample& LastSample() const { return last; }

private:
	struct Segment
	{
		Point<int16_t> from;
		Point<int16_t> to;
		int16_t fromVx = 0;
		int16_t fromVy = 0;
		int16_t toVx = 0;
		int16_t toVy = 0;
		uint16_t fh = 0;
		uint8_t state = 0;
		uint16_t durationMs = 0;
	};

	Sample SampleAt(const Segment& segment, double elapsedMs) const;
	void FinishSegment();

	std::vector<Segment> segments;
	size_t index = 0;
	double consumedMs = 0.0;
	Sample last;
};
}
