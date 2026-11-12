// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <cstdint>

namespace BeiDouBridge {

// Native consumers can pump another application update. Commit each transition
// before delivery, keep key-up work across cancellation, and never run an old tail.
class NativeMouseInput {
public:
    enum class Event { Position, Down, DoubleDown, Up, Wheel };

    static unsigned Message(Event event) {
        switch (event) {
        case Event::Position:
            return 0x200;
        case Event::Down:
            return 0x201;
        case Event::DoubleDown:
            return 0x203;
        case Event::Up:
            return 0x202;
        case Event::Wheel:
            return 0x20a;
        }
        return 0;
    }

    struct Target {
        int x = 0;
        int y = 0;
        unsigned clicks = 1;
        int wheel = 0;
        std::uint32_t character = 0;
        std::uint64_t scene = 0;
        std::uint32_t window = 0;
        bool point = false;
        bool equipment = false;
    };

    bool Request(const Target& value, std::uint64_t now) {
        if (!Released() || value.clicks > 2 || (value.wheel != 0 && value.clicks != 0)) return false;
        ++epoch;
        target = value;
        active = true;
        cancelled = false;
        positionPending = true;
        clickRemaining = value.clicks;
        wheelPending = value.wheel != 0;
        due = now;
        return true;
    }

    void Release(bool cancel = true) {
        ++epoch;
        cancelled = cancelled || cancel;
        active = false;
        positionPending = wheelPending = false;
        clickRemaining = 0;
        releasing = true;
        releaseReady = false;
        if (held) requiredUp = true;
    }

    void MarkDispatched(std::uint64_t deliveryEpoch) {
        if (deliveryEpoch != epoch) return;
        dispatched = true;
        if (target.point) pointDispatched = true;
        if (target.equipment) equipmentDispatched = true;
    }

    void ResetReport() {
        if (Released()) dispatched = pointDispatched = equipmentDispatched = false;
    }

    bool ConfirmRelease(std::uint32_t character, std::uint64_t updates, bool oldContextExited) {
        if (!releasing || !releaseReady || requiredUp || upInFlight || deliveryInFlight) return false;
        if (owned && !oldContextExited && (character != target.character || updates <= releaseAt)) return false;
        releasing = owned = false;
        return true;
    }

    template <class Send, class Updates> bool Flush(std::uint64_t now, const Send& send, const Updates& updates) {
        if (requiredUp && !upInFlight) {
            requiredUp = held = false;
            upInFlight = true;
            const auto deliveryEpoch = epoch;
            const bool sent = send(Event::Up, target, deliveryEpoch);
            upInFlight = false;
            if (!sent) requiredUp = true;
            if (!sent) return false;
        }
        if (releasing && !releaseReady && !requiredUp && !upInFlight && !deliveryInFlight) {
            releaseAt = updates();
            releaseReady = true;
        }
        if (!active || deliveryInFlight || requiredUp || upInFlight || now < due) return true;
        const auto deliveryEpoch = epoch;
        deliveryInFlight = true;
        bool sent;
        if (positionPending) {
            positionPending = false;
            sent = send(Event::Position, target, deliveryEpoch);
        } else if (wheelPending) {
            wheelPending = false;
            sent = send(Event::Wheel, target, deliveryEpoch);
            if (deliveryEpoch == epoch) Release(false);
        } else if (!held && clickRemaining != 0) {
            owned = held = true;
            sent = send(clickRemaining == target.clicks ? Event::Down : Event::DoubleDown, target, deliveryEpoch);
        } else {
            requiredUp = true;
            if (clickRemaining != 0) --clickRemaining;
            if (clickRemaining == 0)
                Release(false);
            else
                due = now + 100;
            sent = true;
        }
        deliveryInFlight = false;
        if (deliveryEpoch != epoch) return sent;
        if (!sent) Release();
        return sent;
    }

    bool Released() const { return !active && !releasing && !requiredUp && !upInFlight && !deliveryInFlight; }

    bool ReleasePending() const { return releasing; }

    bool Owned() const { return owned; }

    bool Held() const { return held; }

    bool Dispatched() const { return dispatched; }

    bool PointDispatched() const { return pointDispatched; }

    bool EquipmentDispatched() const { return equipmentDispatched; }

    bool Cancelled() const { return cancelled; }

    std::uint64_t Epoch() const { return epoch; }

    std::uint32_t Character() const { return target.character; }

    std::uint64_t Scene() const { return target.scene; }

private:
    Target target;
    std::uint64_t epoch = 0;
    std::uint64_t due = 0;
    std::uint64_t releaseAt = 0;
    unsigned clickRemaining = 0;
    bool active = false;
    bool held = false;
    bool owned = false;
    bool requiredUp = false;
    bool upInFlight = false;
    bool deliveryInFlight = false;
    bool positionPending = false;
    bool wheelPending = false;
    bool releasing = false;
    bool releaseReady = false;
    bool dispatched = false;
    bool pointDispatched = false;
    bool equipmentDispatched = false;
    bool cancelled = false;
};
}
