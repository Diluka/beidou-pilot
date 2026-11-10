#pragma once

#include "Net/Login.h"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace ms
{
	struct NpcChoice
	{
		int32_t id;
		std::string text;
	};

	struct NpcDialogue
	{
		uint64_t revision = 0;
		uint64_t scene_generation = 0;
		bool open = false;
		bool response_pending = false;
		int32_t npc_id = 0;
		std::optional<int32_t> object_id;
		int32_t requested_npc_id = 0;
		int8_t type = -1;
		uint8_t speaker = 0;
		bool previous = false;
		bool next = false;
		bool text_known = false;
		std::string text;
		std::vector<NpcChoice> choices;
		bool choices_complete = true;
		std::string closed_by;
	};

	struct HeadlessState
	{
		std::optional<CharEntry> selected_character;
		bool in_game = false;
		uint64_t map_generation = 0;
		NpcDialogue dialogue;
	};

	HeadlessState& headless_state();
}
