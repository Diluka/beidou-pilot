// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "NativeKeyInput.h"

#include <initializer_list>
#include <vector>

namespace BeiDouBridge {

// Each producer owns its logical transitions and release acknowledgements. Only
// the OR of those producers reaches the native keyboard consumer. Commit before
// invoking that consumer: it can pump another application frame synchronously.
class NativeKeyUnion {
public:
    NativeKeyUnion(std::initializer_list<NativeKeyInput*> producers) : inputs(producers) {}

    bool Held(unsigned int key) const {
        for (const auto* input : inputs)
            if (input->Held()[key]) return true;
        return false;
    }

    bool Owned(unsigned int key) const {
        for (const auto* input : inputs)
            if (input->Owned()[key]) return true;
        return false;
    }

    template <typename Send>
    bool Deliver(NativeKeyInput& source, unsigned int key, bool down, std::uint64_t epoch, const Send& send) {
        if (down && source.Epoch() != epoch) return true;
        const bool target = Held(key);
        // Another producer still owns this key, or has already delivered its
        // keydown. A logical release must never release that producer's input.
        if (target == physical[key]) {
            if (down) source.MarkDispatched(epoch);
            return true;
        }
        const auto revision = ++revisions[key];
        const bool previous = physical[key];
        physical[key] = target;
        if (down) source.MarkDispatched(epoch);
        const bool sent = send(key, target);
        // Do not roll back a newer transition delivered by a reentrant frame.
        if (!sent && revisions[key] == revision) physical[key] = previous;
        return sent;
    }

private:
    std::vector<NativeKeyInput*> inputs;
    NativeKeyInput::Mask physical{};
    std::array<std::uint64_t, 256> revisions{};
};

}
