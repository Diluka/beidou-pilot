// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Character/QuestLog.h"
#include "Net/Handlers/Helpers/CharacterParser.h"

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

// Packet layout is taken from the supported server's addQuestInfo/updateQuest/completeQuest.
struct Packet {
    std::vector<int8_t> bytes;

    void Byte(uint8_t value) { bytes.push_back(static_cast<int8_t>(value)); }

    void Short(uint16_t value) {
        Byte(value & 0xff);
        Byte(value >> 8);
    }

    void Long(uint64_t value) {
        for (unsigned int shift = 0; shift < 64; shift += 8) Byte(value >> shift);
    }

    void String(const std::string& value) {
        Short(value.size());
        bytes.insert(bytes.end(), value.begin(), value.end());
    }
};

void Update(ms::QuestLog& quests, uint16_t id, uint8_t status, const std::string& progress = "") {
    Packet packet;
    packet.Short(id);
    packet.Byte(status);
    if (status == 1) {
        packet.String(progress);
        packet.bytes.resize(packet.bytes.size() + 5);
    } else if (status == 2) {
        packet.Long(123456789);
    }
    ms::InPacket input(packet.bytes.data(), packet.bytes.size());
    ms::CharacterParser::parse_quest_update(input, quests);
}
}

int main() {
    ms::QuestLog quests;
    quests.add_started(1000, "old actor state");
    quests.add_completed(1001, 1);

    Packet snapshot;
    snapshot.Short(2);
    snapshot.Short(1041);
    snapshot.String("000");
    snapshot.Short(1041);
    snapshot.String("001");
    snapshot.Short(1);
    snapshot.Short(1038);
    snapshot.Long(123456700);
    ms::InPacket input(snapshot.bytes.data(), snapshot.bytes.size());
    ms::CharacterParser::parse_questlog(input, quests);
    Check(quests.get_started().size() == 1 && quests.get_started().at(1041) == "001"
              && quests.get_completed().size() == 1 && quests.get_completed().at(1038) == 123456700,
          "full quest snapshot did not replace old records or preserve the last raw progress");

    Update(quests, 1041, 1, "005");
    Check(quests.get_started().at(1041) == "005", "live quest progress was not updated");
    Update(quests, 1041, 2);
    Check(quests.get_started().count(1041) == 0 && quests.get_completed().at(1041) == 123456789,
          "completed quest kept its started record");
    Update(quests, 1041, 1, "000");
    Check(quests.get_started().at(1041) == "000" && quests.get_completed().count(1041) == 0,
          "new started record retained an old completion");
    Update(quests, 1041, 0);
    Check(quests.get_started().count(1041) == 0 && quests.get_completed().count(1041) == 0,
          "forfeited quest remained in current records");

    Packet removed;
    removed.Short(1038);
    removed.Byte(0);
    removed.String("");
    removed.bytes.resize(removed.bytes.size() + 5);
    ms::InPacket removedInput(removed.bytes.data(), removed.bytes.size());
    ms::CharacterParser::parse_quest_update(removedInput, quests);
    Check(quests.get_completed().empty(), "status-zero update with a trailer kept an old completion");
}
