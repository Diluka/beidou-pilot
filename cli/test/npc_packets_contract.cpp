// SPDX-License-Identifier: AGPL-3.0-or-later
#include "HeadlessState.h"
#include "IO/UI.h"
#include "Net/Handlers/NpcInteractionHandlers.h"
#include "Net/Packets/NpcInteractionPackets.h"
#include "Net/Session.h"

#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::vector<int8_t> sent;

void Check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void ReadPage(int8_t type, const std::string& text, bool previous = false, bool next = false) {
    // NPC_TALK body from the verified V17 PacketCreator, not a rendered UI fixture.
    std::vector<int8_t> bytes{
        4, 69, 47, 0, 0, type, 0, static_cast<int8_t>(text.size()), static_cast<int8_t>(text.size() >> 8)};
    bytes.insert(bytes.end(), text.begin(), text.end());
    if (type == 0) {
        bytes.push_back(previous);
        bytes.push_back(next);
    }
    ms::InPacket packet(bytes.data(), bytes.size());
    ms::NpcDialogueHandler handler;
    const ms::PacketHandler& receiver = handler;
    receiver.handle(packet);
}
}

// Replace transport and the unused UI singleton initializer. No UI operation or game effect is simulated.
namespace ms {
UI::UI() : enabled(true), quitted(false), caps_lock_enabled(false) {}

Cryptography::Cryptography() = default;
Cryptography::~Cryptography() = default;
PacketSwitch::PacketSwitch() = default;
SocketAsio::SocketAsio() = default;
SocketAsio::~SocketAsio() = default;
Session::Session() = default;
Session::~Session() = default;

void Session::write(int8_t* bytes, size_t length) {
    sent.assign(bytes, bytes + length);
}

bool Session::is_connected() const {
    return true;
}
}

int main() {
    auto& host = ms::headless_state();
    host.map_generation = 9;
    host.dialogue.requested_npc_id = 12101;
    host.dialogue.object_id = 42;
    ReadPage(0, "\xD2\xBB", false, true);
    Check(host.dialogue.open && host.dialogue.npc_id == 12101 && host.dialogue.object_id == 42
              && host.dialogue.scene_generation == 9 && !host.dialogue.previous && host.dialogue.next
              && host.dialogue.text == "一",
          "native_text_page_or_network_encoding_lost");
    const auto first = host.dialogue.revision;
    host.dialogue.response_pending = true;
    ReadPage(4, "#L7#Pick#l#L12#Keep#l");
    Check(host.dialogue.revision > first && !host.dialogue.response_pending && host.dialogue.choices_complete
              && host.dialogue.choices.size() == 2 && host.dialogue.choices[0].id == 7
              && host.dialogue.choices[0].text == "Pick" && host.dialogue.choices[1].id == 12,
          "native_menu_choices_or_page_revision_lost");

    ms::TalkToNPCPacket(42).dispatch();
    Check(sent == std::vector<int8_t>({58, 0, 42, 0, 0, 0}), "npc_request_did_not_use_object_id");
    ms::NpcTalkMorePacket(0, -1).dispatch();
    Check(sent == std::vector<int8_t>({60, 0, 0, -1}), "npc_cancel_response_changed");
    ms::NpcTalkMorePacket(7).dispatch();
    Check(sent == std::vector<int8_t>({60, 0, 4, 1, 7, 0, 0, 0}), "npc_menu_selection_encoding_changed");
    ms::QuestActionPacket(false, 1040, 12000, 10, -20, std::nullopt).dispatch();
    Check(sent == std::vector<int8_t>({107, 0, 1, 16, 4, -32, 46, 0, 0, 10, 0, -20, -1}),
          "normal_quest_start_layout_changed");
    ms::QuestActionPacket(true, 1041, 12100, 10, -20, 0).dispatch();
    Check(sent == std::vector<int8_t>({107, 0, 2, 17, 4, 68, 47, 0, 0, 10, 0, -20, -1, 0, 0}),
          "normal_quest_complete_explicit_reward_layout_changed");
}
