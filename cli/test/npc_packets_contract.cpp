// SPDX-License-Identifier: AGPL-3.0-or-later
#include "HeadlessState.h"
#include "Interaction.h"
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

    // The real dimensional-mirror type inserts an int before text; only its header is supported.
    const std::vector<int8_t> special{4, 69, 47, 0, 0, 14, 0, 0, 0, 0, 0, 4, 0, 't', 'e', 'x', 't'};
    ms::InPacket unsupported(special.data(), special.size());
    ms::NpcDialogueHandler handler;
    const ms::PacketHandler& receiver = handler;
    receiver.handle(unsupported);
    Check(host.dialogue.open && host.dialogue.npc_id == 12101 && host.dialogue.type == 14 && !host.dialogue.text_known
              && !host.dialogue.choices_complete && host.dialogue.text.empty(),
          "unsupported_native_layout_was_parsed_as_an_empty_text_page");

    Interaction ui;
    const Interaction::Context context{"native-controls", 6, 9};
    ui.ResetContext(context);
    int handled = 0;
    const auto target = ui.RegisterTarget([&](std::string&) {
        ui.BeginPage({"server", "NPC", std::string("first"), std::vector<InteractionControl>{}});
        ui.AddControl("button", "Next", MapleControl::Fact::True,
                      [&, owned = std::string("callback remains alive")](std::string&) {
                          ui.BeginPage({"server", "NPC", std::string("second"), std::vector<InteractionControl>{}});
                          handled += owned.empty() ? 0 : 1;
                          return true;
                      });
        return true;
    });
    std::string error;
    Check(ui.Activate(target, context, error) && ui.CurrentPage() && ui.CurrentPage()->text == "first",
          "native_target_did_not_open_its_client_page");
    const auto next = ui.CurrentPage()->controls->front().ref;
    Check(ui.Activate(next, context, error) && handled == 1 && ui.CurrentPage()->text == "second",
          "control_did_not_finish_when_it_replaced_its_own_page");
    Check(!ui.Activate(next, context, error) && error == "stale_interaction_reference" && handled == 1,
          "old_page_reference_activated_a_new_page");
    for (const auto enabled : {MapleControl::Fact::False, MapleControl::Fact::Unknown}) {
        ui.AddControl("button", "Unavailable", enabled, [&](std::string&) {
            ++handled;
            return true;
        });
        const auto reference = ui.CurrentPage()->controls->back().ref;
        Check(!ui.Activate(reference, context, error) && handled == 1, "disabled_or_unknown_control_was_activated");
    }
    ui.BeginPage({"server", "Unsupported", std::nullopt, std::nullopt});
    Check(!ui.CurrentPage()->text && !ui.CurrentPage()->controls, "unknown_page_content_was_invented");
    ui.ResetContext({"native-controls", 6, 10});
    Check(!ui.CurrentPage() && !ui.Activate(target, {"native-controls", 6, 10}, error)
              && error == "stale_interaction_reference",
          "old_scene_target_survived_context_change");

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
