// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <cstdint>

namespace BeiDouBridge {

// One ordinary consume-inventory request. The caller owns slot selection and
// native context validation; this slot never waits inside a Lua resume.
class NativeItemUse {
public:
    struct Item {
        std::uint32_t character = 0;
        std::uint64_t scene = 0;
        std::uint32_t context = 0;
        int slot = 0;
        std::uint32_t itemId = 0;
    };

    enum class Consumption { None, ContextChanged, Dispatched };

    void Request(const Item& item) {
        requested = item;
        pending = true;
        dispatched = false;
    }

    void Cancel() { pending = false; }
    bool Pending() const { return pending; }
    bool Dispatched() const { return dispatched; }

    template <typename Invoke>
    Consumption Consume(std::uint32_t character, std::uint64_t scene, std::uint32_t context, const Invoke& invoke) {
        if (!pending) return Consumption::None;
        const auto item = requested;
        pending = false;
        if (item.character != character || item.scene != scene || item.context != context)
            return Consumption::ContextChanged;
        dispatched = true;
        invoke(item);
        // The native consumer can pump another update and accept a new request.
        // No old request state is written after that callback returns.
        return Consumption::Dispatched;
    }

private:
    Item requested;
    bool pending = false;
    bool dispatched = false;
};

}
