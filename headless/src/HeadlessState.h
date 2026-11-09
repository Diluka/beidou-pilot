#pragma once

#include "Net/Login.h"

#include <cstdint>
#include <optional>

namespace ms
{
	struct HeadlessState
	{
		std::optional<CharEntry> selected_character;
		bool in_game = false;
		uint64_t map_generation = 0;
	};

	HeadlessState& headless_state();
}
