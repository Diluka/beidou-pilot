// SPDX-License-Identifier: AGPL-3.0-or-later
#include "stdafx.h"
#include "NativeObservation.h"
#include "EventTransport.h"
#include "Contract.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <map>
#include <sstream>

namespace NativeObservation {
namespace {
using Address = std::uint32_t;

template <class T> T At(const std::vector<unsigned char>& bytes, std::size_t offset) {
    T value{};
    std::memcpy(&value, bytes.data() + offset, sizeof(value));
    return value;
}

std::string Hex(Address value) {
    std::ostringstream out;
    out << "0x" << std::hex << value;
    return out.str();
}
}

Value Notifications() {
    struct Metadata {
        const char* name = nullptr;
        std::size_t textOffset = 0;
        std::size_t identityOffset = 0;
    };

    // These labels follow the V17 Draw dispatch and its actual StringPool text.
    // Unknown kinds still use the same native window, buttons and lifetime.
    const std::array<Metadata, 14> kinds{{{nullptr, 0xC8, 0xCC},
                                          {"friend", 0xD8, 0xD0},
                                          {"trade", 0xC8, 0xCC},
                                          {nullptr, 0xC8, 0xCC},
                                          {nullptr, 0, 0},
                                          {"party", 0xC8, 0xDC},
                                          {"guild_alliance", 0xC8, 0xDC},
                                          {"quest", 0, 0xE8},
                                          {"guild", 0xC8, 0xDC},
                                          {"friend_status", 0xF0, 0},
                                          {"delivery", 0xF4, 0},
                                          {"quest", 0, 0xE8},
                                          {"academy", 0xC8, 0xDC},
                                          {"new_year_card", 0xF4, 0xCC}}};
    auto notifications = Value::Array();
    const auto clockOwner = Read<Address>(0x00BE7B38);
    if (clockOwner == 0) throw ReadError("Native notification clock is unavailable");
    const auto nativeNow = Read<Address>(clockOwner + 0x18);
    const auto observedAt =
        std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch())
            .count();
    const auto registry = Read<std::array<Address, 3>>(0x00BF1650);
    if (registry[0] > 256) throw ReadError("Active CWnd count exceeds the supported range");
    Address node = registry[1];
    for (Address index = 0; index < registry[0]; ++index) {
        if (node == 0) throw ReadError("Active CWnd list ended before its recorded count");
        const auto address = Read<Address>(node);
        if (Read<std::array<Address, 3>>(address) == std::array<Address, 3>{{0x00AF3BF0, 0x00AF3BA4, 0x00AF3BA0}}) {
            // All constructors use 0x520276; OnButtonClicked is 0x522585.
            const auto header = Bytes(address, 0x118);
            const auto nativeKind = At<Address>(header, 0xC4);
            const auto metadata = nativeKind < kinds.size() ? kinds[nativeKind] : Metadata{};
            const bool quest = nativeKind == 7 || nativeKind == 11;
            const auto nativeId = metadata.identityOffset == 0 ? 0
                                  : quest                      ? At<std::uint16_t>(header, metadata.identityOffset)
                                                               : At<Address>(header, metadata.identityOffset);
            const auto duration = At<Address>(header, 0x8C);
            const auto deadline = At<Address>(header, 0xB4);
            const auto remaining = static_cast<std::int32_t>(deadline - nativeNow);
            const bool pending =
                At<Address>(header, 0x114) == 0 && At<Address>(header, 0xB8) == 0 && (duration == 0 || remaining > 0);
            Value sourceText;
            if (metadata.textOffset != 0) sourceText = ZxString(address + metadata.textOffset);
            auto window = Window(address);
            auto buttons = Value::Array();
            for (auto button : window["buttons"].Elements()) {
                const auto control = static_cast<unsigned int>(button["control_id"].Number());
                button["action"] = control == 2000 ? Value("primary") : control == 2001 ? Value("dismiss") : Value();
                buttons.Add(std::move(button));
            }
            const bool available =
                pending && window["game_rect"].Type() != Value::Kind::Null && !buttons.Elements().empty();
            notifications.Add(Value::Object(
                {{"id", Hex(address) + ":" + Hex(duration == 0 ? 0 : deadline) + ":" + std::to_string(nativeKind) + ":"
                            + std::to_string(nativeId) + ":" + sourceText.Text()},
                 {"native_kind", nativeKind},
                 {"kind", metadata.name == nullptr ? Value() : Value(metadata.name)},
                 {"source_text", std::move(sourceText)},
                 {"text", Value()},
                 {"sender_id", nativeKind == 1 ? Value(nativeId) : Value()},
                 {"party_id", nativeKind == 5 ? Value(nativeId) : Value()},
                 {"interaction_id", nativeKind == 2 || nativeKind == 3 ? Value(nativeId) : Value()},
                 {"quest_id", quest ? Value(nativeId) : Value()},
                 {"expires_at_ms", duration == 0 ? Value() : Value(observedAt + remaining)},
                 {"remaining_ms", duration == 0 ? Value() : Value((std::max)(0, remaining))},
                 {"pending", pending},
                 {"available", available},
                 {"window", std::move(window)},
                 {"buttons", std::move(buttons)}}));
        }
        const auto next = Read<Address>(node - 12);
        node = next == 0 ? 0 : next + 16;
    }
    if (Read<std::array<Address, 3>>(0x00BF1650) != registry)
        throw ReadError("Active CWnd list changed while observing notifications");
    return Value::Object({{"source", "client-native-ui"},
                          {"readonly", true},
                          {"notifications", std::move(notifications)},
                          {"unavailable", Value::Array()},
                          {"not_covered", Value::Array({"rendered_body_text"})}});
}

void PollNotifications(MapleControl::EventTransport& events, const MapleControl::State& state) {
    static std::map<std::string, Value> previous;
    static std::string lastError;
    static std::uint32_t previousCharacter = 0;
    if (!state.inGame) {
        for (const auto& entry : previous) {
            auto data = entry.second;
            data["reason"] = "left_game";
            data["pending"] = false;
            data["available"] = false;
            events.Emit(state, "notification.closed", "client-native-ui", data);
        }
        previous.clear();
        previousCharacter = 0;
        lastError.clear();
        return;
    }
    if (!state.ready) return;
    if (previousCharacter != 0 && previousCharacter != state.character.id) previous.clear();
    previousCharacter = state.character.id;
    auto observation = Collect("notifications");
    if (observation.status != "ok") {
        if (observation.error != lastError) {
            events.Emit(state, "notification.observation_unavailable", "client-native-ui",
                        Value::Object({{"error", observation.error}}));
            lastError = observation.error;
        }
        return;
    }
    lastError.clear();
    std::map<std::string, Value> current;
    for (auto notification : observation.data["notifications"].Elements()) {
        if (!notification["pending"].Boolean()) continue;
        const auto id = notification["id"].Text();
        if (previous.find(id) == previous.end())
            events.Emit(state, "notification.opened", "client-native-ui", notification,
                        static_cast<std::uint64_t>(notification["expires_at_ms"].Number()));
        current.emplace(id, std::move(notification));
    }
    for (const auto& entry : previous) {
        if (current.find(entry.first) != current.end()) continue;
        auto data = entry.second;
        data["reason"] = "no_longer_pending";
        data["pending"] = false;
        data["available"] = false;
        events.Emit(state, "notification.closed", "client-native-ui", data);
    }
    previous = std::move(current);
}
}
