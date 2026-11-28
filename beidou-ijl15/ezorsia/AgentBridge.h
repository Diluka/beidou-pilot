#pragma once

#include <cstdint>

namespace AgentBridge {
bool Install();
void CharacterUpdated(std::uintptr_t player);
// Latest observed in-game map id, or zero before the scene is ready. Only reads
// the state the update hook already captured.
std::uint32_t CurrentMapId();
// Latest observed local character id, or zero before the scene is ready.
std::uint32_t CurrentCharacterId();

// Latest observed local character stats captured by the update hook. Only
// reads state the hook already captured.
struct CharacterStats {
    std::uint32_t level = 0;
    std::uint32_t hp = 0;
    std::uint32_t maxHp = 0;
    std::uint32_t mp = 0;
    std::uint32_t maxMp = 0;
    std::uint32_t experience = 0;
    bool known = false;
};

CharacterStats CurrentCharacterStats();
}
