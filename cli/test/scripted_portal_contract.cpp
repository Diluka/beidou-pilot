// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Gameplay/MapleMap/Portal.h"
#include "Gameplay/Movement.h"
#include "Net/Packets/GameplayPackets.h"
#include "Net/Session.h"

#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::vector<int8_t> sent;

void Check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
}

// Replace the transport boundary only; retain the real portal metadata and packet serializer.
namespace ms {
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
    ms::Portal scripted(nullptr, ms::Portal::SCRIPTED, "in00", false, {74, 154}, 999999999, "");
    const auto warp = scripted.getwarpinfo();
    Check(warp.valid && warp.scripted && !warp.intramap && warp.mapid == 999999999 && warp.name == "in00",
          "scripted_portal_lost_requestability_or_invented_a_destination");
    Check(scripted.bounds().contains({74, 154}) && !scripted.bounds().contains({1000, 1000}),
          "scripted_portal_did_not_keep_its_local_selection_bounds");
    ms::ChangeMapSpecialPacket(warp.name).dispatch();
    Check(sent == std::vector<int8_t>({100, 0, 0, 4, 0, 'i', 'n', '0', '0', 0, 0}),
          "special_portal_request_layout_changed");

    ms::Portal regular(nullptr, ms::Portal::REGULAR, "west00", false, {0, 0}, 100000000, "east00");
    const auto normal = regular.getwarpinfo();
    Check(normal.valid && !normal.scripted && !normal.intramap && normal.mapid == 100000000,
          "ordinary_portal_routing_facts_changed");
    ms::ChangeMapPacket(false, -1, normal.name, false).dispatch();
    Check(sent == std::vector<int8_t>({38, 0, 0, -1, -1, -1, -1, 6, 0, 'w', 'e', 's', 't', '0', '0', 0, 0, 0}),
          "ordinary_portal_request_layout_changed");

    ms::Portal local(nullptr, ms::Portal::REGULAR, "local", true, {0, 0}, 1010000, "spawn");
    const auto intramap = local.getwarpinfo();
    Check(intramap.valid && intramap.intramap && !intramap.scripted && intramap.toname == "spawn",
          "intramap_portal_routing_facts_changed");
    ms::Portal localScript(nullptr, ms::Portal::SCRIPTED, "script", true, {0, 0}, 1010000, "spawn");
    Check(localScript.getwarpinfo().scripted, "intramap_target_hid_the_scripted_portal_kind");
    ms::Portal unsupported(nullptr, ms::Portal::SCRIPTED_INVISIBLE, "other", false, {0, 0}, 999999999, "");
    Check(!unsupported.getwarpinfo().valid && !unsupported.getwarpinfo().scripted,
          "special_portal_support_expanded_beyond_type_seven");
    Check(!ms::Portal::WarpInfo().valid, "missing_portal_became_requestable");
}
