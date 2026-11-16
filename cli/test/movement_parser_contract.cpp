// SPDX-License-Identifier: AGPL-3.0-or-later
// Inbound V17 path command layout contract (docs/V17_EXTENDED_MOTION_RULES.md §10):
// each documented command consumes its original width and keeps position/velocity
// facts in the matching fields instead of shifting the payload.
#include "Net/InPacket.h"
#include "Net/Handlers/Helpers/MovementParser.h"

#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

void Near(int actual, int expected, const std::string& message) {
    if (actual != expected) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}

void PutShort(std::vector<int8_t>& bytes, int value) {
    bytes.push_back(static_cast<int8_t>(value & 0xFF));
    bytes.push_back(static_cast<int8_t>((value >> 8) & 0xFF));
}
}

int main() {
    std::vector<int8_t> bytes;
    bytes.push_back(7); // fragment count

    // command 0: x,y,vx,vy,fh,state,duration
    bytes.push_back(0);
    PutShort(bytes, 100);
    PutShort(bytes, 200);
    PutShort(bytes, -125);
    PutShort(bytes, 0);
    PutShort(bytes, 7);
    bytes.push_back(5);
    PutShort(bytes, 300);

    // command 15: x,y,vx,vy,fh,u,state,duration
    bytes.push_back(15);
    PutShort(bytes, 10);
    PutShort(bytes, 20);
    PutShort(bytes, 1);
    PutShort(bytes, -2);
    PutShort(bytes, 3);
    PutShort(bytes, 0x1234);
    bytes.push_back(7);
    PutShort(bytes, 400);

    // command 1: vx,vy,state,duration
    bytes.push_back(1);
    PutShort(bytes, 125);
    PutShort(bytes, -555);
    bytes.push_back(2);
    PutShort(bytes, 510);

    // command 3: x,y,fh,state,duration
    bytes.push_back(3);
    PutShort(bytes, 5);
    PutShort(bytes, 6);
    PutShort(bytes, 9);
    bytes.push_back(1);
    PutShort(bytes, 120);

    // command 14: vx,vy,u,state,duration
    bytes.push_back(14);
    PutShort(bytes, -1);
    PutShort(bytes, 2);
    PutShort(bytes, 0x55AA);
    bytes.push_back(3);
    PutShort(bytes, 30);

    // command 10: one payload byte
    bytes.push_back(10);
    bytes.push_back(0x7F);

    // command 21: state,duration
    bytes.push_back(21);
    bytes.push_back(4);
    PutShort(bytes, 90);

    ms::InPacket packet(bytes.data(), bytes.size());
    const auto movements = ms::MovementParser::parse_movements(packet);
    Check(movements.size() == 7, "fragment_count");
    Check(packet.length() == 0, "every_documented_command_consumed");
    Check(packet.available() == false, "packet_fully_consumed");

    Near(movements[0].xpos, 100, "abs_x");
    Near(movements[0].ypos, 200, "abs_y");
    Near(movements[0].vx, -125, "abs_vx");
    Near(movements[0].vy, 0, "abs_vy");
    Near(movements[0].fh, 7, "abs_fh");
    Near(movements[0].newstate, 5, "abs_state");
    Near(movements[0].duration, 300, "abs_duration");

    Near(movements[1].xpos, 10, "jumpdown_x");
    Near(movements[1].vx, 1, "jumpdown_vx");
    Near(movements[1].vy, -2, "jumpdown_vy");
    Near(movements[1].fh, 3, "jumpdown_fh");
    Near(static_cast<int>(movements[1].extra), 0x1234, "jumpdown_extra_word");
    Near(movements[1].newstate, 7, "jumpdown_state");
    Near(movements[1].duration, 400, "jumpdown_duration");

    Near(movements[2].vx, 125, "relative_vx");
    Near(movements[2].vy, -555, "relative_vy");
    Near(movements[2].newstate, 2, "relative_state");
    Near(movements[2].duration, 510, "relative_duration");
    Near(movements[2].xpos, 125, "legacy_relative_xpos_kept");

    Near(movements[3].xpos, 5, "chair_x");
    Near(movements[3].fh, 9, "chair_fh");
    Near(movements[3].newstate, 1, "chair_state");
    Near(movements[3].duration, 120, "chair_duration");

    Near(movements[4].vx, -1, "cmd14_vx");
    Near(movements[4].vy, 2, "cmd14_vy");
    Near(static_cast<int>(movements[4].extra), 0x55AA, "cmd14_extra_word");
    Near(movements[4].newstate, 3, "cmd14_state");
    Near(movements[4].duration, 30, "cmd14_duration");

    Check(movements[5].command == 10 && movements[5].type == ms::Movement::NONE, "cmd10_consumed_one_byte");
    Near(movements[6].newstate, 4, "cmd21_state");
    Near(movements[6].duration, 90, "cmd21_duration");

    // An empty path is valid and consumes only the count byte.
    std::vector<int8_t> empty{0};
    ms::InPacket empty_packet(empty.data(), empty.size());
    Check(ms::MovementParser::parse_movements(empty_packet).empty(), "empty_path");
    Check(empty_packet.length() == 0, "empty_path_consumed");

    std::cout << "ok\n";
    return 0;
}
