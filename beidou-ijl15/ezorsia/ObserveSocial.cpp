// SPDX-License-Identifier: AGPL-3.0-or-later
#include "stdafx.h"
#include "NativeObservation.h"
#include "EventTransport.h"
#include "Runtime.h"

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

Value Invitations() {
    auto invitations = Value::Array();
    const auto clockOwner = Read<Address>(0x00BE7B38);
    if (clockOwner == 0) throw ReadError("Native invitation clock is unavailable");
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
            // V17 constructors 0x522D22 and 0x52320D; OnButtonClicked is 0x522585.
            const auto header = Bytes(address, 0x118);
            const auto kind = At<Address>(header, 0xC4);
            if (kind == 1 || kind == 5) {
                const bool friendRequest = kind == 1;
                const auto deadline = At<Address>(header, 0xB4);
                const auto remaining = static_cast<std::int32_t>(deadline - nativeNow);
                const auto sender = ZxString(address + (friendRequest ? 0xD8 : 0xC8));
                const auto nativeId = At<Address>(header, friendRequest ? 0xD0 : 0xDC);
                const bool pending = At<Address>(header, 0x114) == 0 && At<Address>(header, 0xB8) == 0;
                auto window = Window(address);
                auto buttons = Value::Array();
                for (auto button : window["buttons"].Elements()) {
                    const auto control = static_cast<unsigned int>(button["control_id"].Number());
                    if (control == 2000 || control == 2001) {
                        button["action"] = control == 2000 ? "accept" : "reject";
                        buttons.Add(std::move(button));
                    }
                }
                const bool available = pending && remaining > 0 && (friendRequest || At<Address>(header, 0xE0) != 0)
                                       && window["game_rect"].Type() != Value::Kind::Null
                                       && buttons.Elements().size() == 2;
                invitations.Add(Value::Object({{"id", Hex(address) + ":" + Hex(deadline) + ":" + std::to_string(kind)
                                                          + ":" + std::to_string(nativeId)},
                                               {"kind", friendRequest ? "friend" : "party"},
                                               {"sender_id", friendRequest ? Value(nativeId) : Value()},
                                               {"sender_name", sender},
                                               {"party_id", friendRequest ? Value() : Value(nativeId)},
                                               {"expires_at_ms", observedAt + remaining},
                                               {"remaining_ms", (std::max)(0, remaining)},
                                               {"pending", pending && remaining > 0},
                                               {"available", available},
                                               {"window", std::move(window)},
                                               {"buttons", std::move(buttons)}}));
            }
        }
        const auto next = Read<Address>(node - 12);
        node = next == 0 ? 0 : next + 16;
    }
    if (Read<std::array<Address, 3>>(0x00BF1650) != registry)
        throw ReadError("Active CWnd list changed while observing invitations");
    return Value::Object({{"source", "client-native-ui"},
                          {"readonly", true},
                          {"invitations", std::move(invitations)},
                          {"unavailable", Value::Array()}});
}

Value Party() {
    const auto context = Read<Address>(0x00BE7918);
    if (context == 0) throw ReadError("CWvsContext is unavailable");
    // 0xA3EC74/0xA3EB2D receive this block; 0xA3F836 reads each of its six members.
    const auto party = Bytes(context + 0x2ED4, 4 + 0x12A);
    const auto partyId = At<Address>(party, 0);
    const auto leader = partyId == 0 ? 0 : At<Address>(party, 0xB2);
    auto members = Value::Array();
    if (partyId != 0) {
        for (std::size_t index = 0; index < 6; ++index) {
            const auto id = At<Address>(party, 4 + index * 4);
            if (id == 0) continue;
            const auto nameStart = party.begin() + 0x1C + index * 13;
            const auto nameEnd = std::find(nameStart, nameStart + 13, '\0');
            if (nameEnd == nameStart + 13) throw ReadError("Party member name is not terminated");
            const auto channel = At<std::int32_t>(party, 0x9A + index * 4);
            members.Add(Value::Object({{"id", id},
                                       {"name", Utf8(std::string(nameStart, nameEnd))},
                                       {"job", At<std::int32_t>(party, 0x6A + index * 4)},
                                       {"level", At<std::int32_t>(party, 0x82 + index * 4)},
                                       {"channel", channel >= 0 && channel < 20 ? Value(channel + 1) : Value()},
                                       {"channel_index", channel},
                                       {"map_id", At<Address>(party, 0xB6 + index * 4)},
                                       {"leader", id == leader}}));
        }
    }
    return Value::Object({{"source", "client-native-context"},
                          {"readonly", true},
                          {"party_id", partyId},
                          {"leader_id", partyId == 0 ? Value() : Value(leader)},
                          {"members", std::move(members)},
                          {"unavailable", Value::Array()},
                          {"not_covered", Value::Array({"member_online_status"})}});
}

void PollInvitations(MapleControl::EventTransport& events, const MapleControl::State& state) {
    static std::map<std::string, Value> previous;
    static std::string lastError;
    static std::uint32_t previousCharacter = 0;
    if (!state.inGame) {
        for (const auto& entry : previous) {
            auto data = entry.second;
            data["reason"] = "left_game";
            events.Emit(state, "invitation.closed", "client-native-ui", data);
        }
        previous.clear();
        previousCharacter = 0;
        lastError.clear();
        return;
    }
    if (!state.ready) return;
    if (previousCharacter != 0 && previousCharacter != state.character.id) previous.clear();
    previousCharacter = state.character.id;
    auto observation = Collect("invitations");
    if (observation.status != "ok") {
        if (observation.error != lastError) {
            events.Emit(state, "invitation.observation_unavailable", "client-native-ui",
                        Value::Object({{"error", observation.error}}));
            lastError = observation.error;
        }
        return;
    }
    lastError.clear();
    std::map<std::string, Value> current;
    for (auto invitation : observation.data["invitations"].Elements()) {
        if (!invitation["pending"].Boolean()) continue;
        const auto id = invitation["id"].Text();
        if (previous.find(id) == previous.end())
            events.Emit(state, "invitation.opened", "client-native-ui", invitation,
                        static_cast<std::uint64_t>(invitation["expires_at_ms"].Number()));
        current.emplace(id, std::move(invitation));
    }
    for (const auto& entry : previous) {
        if (current.find(entry.first) != current.end()) continue;
        auto data = entry.second;
        data["reason"] = "no_longer_pending";
        events.Emit(state, "invitation.closed", "client-native-ui", data);
    }
    previous = std::move(current);
}
}
