// SPDX-License-Identifier: AGPL-3.0-or-later
#include "MovementReplay.h"

#include <algorithm>
#include <cmath>

namespace ms {
namespace {
bool IsAbsoluteCommand(uint8_t command) {
    switch (command) {
    case 0:
    case 5:
    case 17:
    case 15:
    case 3:
    case 4:
    case 7:
    case 8:
    case 9:
    case 11:
        return true;
    default:
        return false;
    }
}
}

void MovementReplay::Reset(Point<int16_t> start, std::vector<Movement>&& fragments) {
    segments.clear();
    index = 0;
    consumedMs = 0.0;
    last = Sample{};
    last.x = start.x();
    last.y = start.y();
    last.finished = fragments.empty();

    Point<int16_t> current = start;
    int16_t fromVx = 0;
    int16_t fromVy = 0;
    uint16_t currentFh = 0;
    uint8_t currentState = 0;

    for (const auto& fragment : fragments) {
        Segment segment;
        segment.from = current;
        segment.fromVx = fromVx;
        segment.fromVy = fromVy;
        segment.durationMs = fragment.duration > 0 ? static_cast<uint16_t>(fragment.duration) : 0;
        segment.state = fragment.newstate != 0 ? fragment.newstate : currentState;
        segment.fh = fragment.fh != 0 ? fragment.fh : currentFh;

        if (IsAbsoluteCommand(fragment.command)) {
            // 0/5/17/15 carry the endpoint position and current endpoint velocity; the
            // position-only commands (3/4/7/8/9/11) carry no velocity (0 in vx/vy).
            segment.to = Point<int16_t>(fragment.xpos, fragment.ypos);
            segment.toVx = fragment.vx;
            segment.toVy = fragment.vy;
        } else {
            // Relative/velocity commands inherit the previous endpoint position and
            // only update the endpoint velocity (decoder 0x68A403-0x68A42A).
            segment.to = current;
            segment.toVx = fragment.vx;
            segment.toVy = fragment.vy;
        }

        current = segment.to;
        fromVx = segment.toVx;
        fromVy = segment.toVy;
        currentFh = segment.fh;
        currentState = segment.state;
        segments.push_back(segment);
    }

    // Zero-duration command 10/21 entries still produce a segment; advance handles it.
    if (!segments.empty()) {
        const auto& first = segments.front();
        last.state = first.state;
        last.fh = first.fh;
    }
}

int32_t MovementReplay::RemainingMs() const {
    int32_t remaining = 0;
    for (size_t i = index; i < segments.size(); ++i) remaining += segments[i].durationMs;
    remaining -= static_cast<int32_t>(consumedMs);
    return std::max(remaining, 0);
}

uint16_t MovementReplay::StepMs() const {
    return RemainingMs() > 1100 ? 33 : 30;
}

bool MovementReplay::NeedsSnapshot() const {
    return RemainingMs() > 6100;
}

MovementReplay::Sample MovementReplay::SampleAt(const Segment& segment, double elapsedMs) const {
    Sample sample;
    sample.fh = segment.fh;
    sample.state = segment.state;
    sample.vx = segment.toVx;
    sample.vy = segment.toVy;

    if (segment.durationMs == 0) {
        sample.x = segment.to.x();
        sample.y = segment.to.y();
        return sample;
    }

    const double u = std::clamp(elapsedMs / static_cast<double>(segment.durationMs), 0.0, 1.0);
    const double t = static_cast<double>(segment.durationMs) / 1000.0;
    const double u2 = u * u;
    const double u3 = u2 * u;
    const double h00 = 2.0 * u3 - 3.0 * u2 + 1.0;
    const double h10 = u3 - 2.0 * u2 + u;
    const double h01 = -2.0 * u3 + 3.0 * u2;
    const double h11 = u3 - u2;

    sample.x = h00 * segment.from.x() + h10 * (segment.fromVx * t) + h01 * segment.to.x()
               + h11 * (segment.toVx * t);
    sample.y = h00 * segment.from.y() + h10 * (segment.fromVy * t) + h01 * segment.to.y()
               + h11 * (segment.toVy * t);
    return sample;
}

void MovementReplay::FinishSegment() {
    const Segment& segment = segments[index];
    last.x = segment.to.x();
    last.y = segment.to.y();
    last.vx = segment.toVx;
    last.vy = segment.toVy;
    last.fh = segment.fh;
    last.state = segment.state;
    ++index;
    consumedMs = 0.0;
    if (index >= segments.size()) last.finished = true;
}

MovementReplay::Sample MovementReplay::Advance(uint16_t stepMs) {
    double remainingStep = stepMs;
    while (index < segments.size() && remainingStep > 0.0) {
        const Segment& segment = segments[index];
        const double left = static_cast<double>(segment.durationMs) - consumedMs;

        if (left <= 0.0) {
            FinishSegment();
            continue;
        }

        const double take = std::min(remainingStep, left);
        consumedMs += take;
        remainingStep -= take;

        if (consumedMs >= static_cast<double>(segment.durationMs)) {
            FinishSegment();
        } else {
            last = SampleAt(segment, consumedMs);
            last.finished = false;
            return last;
        }
    }

    if (index >= segments.size()) {
        last.finished = true;
    }
    return last;
}
}
