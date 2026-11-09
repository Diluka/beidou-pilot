#pragma once

#include <cstdint>

namespace AgentBridge {
    bool Install();
    void CharacterUpdated(std::uintptr_t player);
}
