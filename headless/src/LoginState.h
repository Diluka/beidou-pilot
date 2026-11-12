#pragma once

#include "Net/Login.h"

#include <cstdint>
#include <string>
#include <vector>

namespace ms
{
	struct LoginState
	{
		int32_t desired_cid = 0;
		uint8_t world = 0;
		uint8_t channel = 0;
		bool account_authenticated = false;
		std::string phase = "disconnected";
		std::string error;
		std::vector<CharEntry> characters;
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
}
