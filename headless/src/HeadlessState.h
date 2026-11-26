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
		bool actions_enabled_after_page = false;
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

		void observe_actions_enabled() {
			if (response_pending) {
				response_pending = false;
				closed_by = "enable_actions_after_request";
				++revision;
			} else if (open && type == 0 && !previous && !next) {
				actions_enabled_after_page = true;
			}
		}

		void begin_response() {
			open = false;
			response_pending = !actions_enabled_after_page;
			closed_by = actions_enabled_after_page ? "enable_actions_after_page" : "local_response";
			actions_enabled_after_page = false;
			++revision;
		}
	};

	struct HeadlessState
	{
		std::optional<CharEntry> selected_character;
		bool in_game = false;
		uint64_t map_generation = 0;
		uint64_t player_parse_errors_at_map_entry = 0;
		NpcDialogue dialogue;
	};

	HeadlessState& headless_state();
}
