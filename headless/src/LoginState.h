#pragma once

#include "Net/Login.h"

#include <cstdint>
#include <string>
#include <optional>
#include <vector>

namespace ms
{
	struct CharacterCreation
	{
		std::string name;
		int32_t job, face, hair, hair_color, skin, top, bottom, shoes, weapon;
		bool female;
	};

	struct LoginState
	{
		int32_t desired_cid = 0;
		bool accept_tos = false;
		bool tos_sent = false;
		std::optional<bool> account_female;
		bool gender_sent = false;
		uint8_t world = 0;
		uint8_t channel = 0;
		bool account_authenticated = false;
		std::string run_id;
		std::string phase = "disconnected";
		std::string error;
		std::vector<CharEntry> characters;
		bool characters_known = false;
		std::string pending_request_id;
		std::optional<CharacterCreation> creation;
		std::string creation_status;
		std::string creation_error;
		int32_t created_cid = 0;
		uint64_t rx_packets = 0;
		uint64_t tx_packets = 0;
		uint16_t last_opcode = 0;
		uint64_t packet_parse_errors = 0;
		uint64_t player_packet_parse_errors = 0;
		std::string last_packet_error;
		uint8_t hp_alert = 0;
		uint8_t mp_alert = 0;
	};

	LoginState& login_state();
	void configure_login(int32_t cid, uint8_t world, uint8_t channel);
	void stop_pending_creation(const std::string& reason);
}
