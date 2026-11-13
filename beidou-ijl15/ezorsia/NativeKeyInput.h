// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <algorithm>
#include <array>
#include <cstdint>

namespace BeiDouBridge {

// The bridge keeps one current target set. Native delivery can pump another
// application update, so every key transition commits its state before calling
// the native consumer and old target sets never resume after a replacement.
class NativeKeyInput {
public:
    using Mask = std::array<bool, 256>;

    struct FlushResult {
        bool failed = false;
        std::uint64_t epoch = 0;
    };

    void Request(const Mask& keys, std::uint32_t durationMs, std::uint32_t character, std::uint64_t now) {
        if (!Any(keys)) {
            dispatched = false;
            Release();
            return;
        }
        ++epoch;
        desired = keys;
        active = true;
        releasing = false;
        releaseReady = false;
        dispatched = false;
        controlledCharacter = character;
        deadline = now + durationMs;
    }

    void Release() {
        ++epoch;
        desired.fill(false);
        active = false;
        releasing = true;
        releaseReady = false;
        releaseCharacter = controlledCharacter;
        releaseNeedsCharacterUpdate = Any(owned);
        for (unsigned int key = 0; key < held.size(); ++key)
            if (held[key]) requiredUp[key] = true;
    }

    bool ConfirmRelease(std::uint32_t updatedCharacter, std::uint64_t characterUpdates, bool oldCharacterExited) {
        if (!releasing || !releaseReady || Any(requiredUp) || Any(upInFlight)) return false;
        if (releaseNeedsCharacterUpdate && !oldCharacterExited
            && (updatedCharacter != releaseCharacter || characterUpdates <= releaseAtCharacterUpdate))
            return false;
        releasing = false;
        owned.fill(false);
        controlledCharacter = 0;
        return true;
    }

    // Called by the native boundary immediately before entering its real
    // consumer. Acceptance alone must not turn into a dispatched action.
    void MarkDispatched(std::uint64_t targetEpoch) {
        if (targetEpoch == epoch) dispatched = true;
    }

    template <typename SendKey, typename CharacterUpdates>
    FlushResult Flush(const SendKey& send, const CharacterUpdates& readCharacterUpdates) {
        const auto batchEpoch = epoch;
        FlushResult result;
        // Explicit releases and failed keyups must finish. Ordinary target
        // differences stay replaceable until their native delivery begins.
        for (unsigned int key = 0; key < held.size(); ++key)
            if ((requiredUp[key] || (held[key] && !desired[key])) && !upInFlight[key]) {
                requiredUp[key] = false;
                held[key] = false;
                upInFlight[key] = true;
                const auto releaseEpoch = epoch;
                const bool sent = send(key, false, releaseEpoch);
                upInFlight[key] = false;
                if (!sent) {
                    requiredUp[key] = true;
                    result = {true, releaseEpoch};
                }
            }
        if (releasing && !releaseReady && !Any(requiredUp) && !Any(upInFlight)) {
            releaseAtCharacterUpdate = readCharacterUpdates();
            releaseReady = true;
        }
        if (batchEpoch != epoch || !active || Any(requiredUp) || Any(upInFlight)) return result;
        for (unsigned int key = 0; key < desired.size(); ++key)
            if (desired[key] && !held[key]) {
                owned[key] = true;
                held[key] = true;
                const bool sent = send(key, true, batchEpoch);
                if (batchEpoch != epoch) return result;
                if (!sent) {
                    held[key] = false;
                    return {true, batchEpoch};
                }
            }
        return result;
    }

    const Mask& Held() const { return held; }

    const Mask& Owned() const { return owned; }

    bool Active() const { return active; }

    bool Released() const { return !active && !releasing; }

    bool ReleasePending() const { return releasing; }

    // Used by the independent tick release fence, including when a new movement
    // request supersedes a release before its native keyups have completed.
    bool TransitionsPending() const { return Any(requiredUp) || Any(upInFlight) || held != desired; }

    std::uint64_t Deadline() const { return deadline; }

    std::uint32_t ReleaseCharacter() const { return releaseCharacter; }

    std::uint64_t Epoch() const { return epoch; }

    bool Dispatched() const { return dispatched; }

private:
    static bool Any(const Mask& keys) {
        return std::any_of(keys.begin(), keys.end(), [](bool value) { return value; });
    }

    Mask desired{};
    Mask held{};
    Mask owned{};
    Mask requiredUp{};
    Mask upInFlight{};
    std::uint64_t epoch = 0;
    std::uint64_t deadline = 0;
    std::uint64_t releaseAtCharacterUpdate = 0;
    std::uint32_t controlledCharacter = 0;
    std::uint32_t releaseCharacter = 0;
    bool active = false;
    bool releasing = false;
    bool releaseReady = false;
    bool releaseNeedsCharacterUpdate = false;
    bool dispatched = false;
};

}
