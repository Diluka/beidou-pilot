#pragma once

#include <cstdint>

namespace AgentBridge {
bool Install();
void CharacterUpdated(std::uintptr_t player);
// Latest observed in-game map id, or zero before the scene is ready. Only reads
// the state the update hook already captured.
std::uint32_t CurrentMapId();
}
