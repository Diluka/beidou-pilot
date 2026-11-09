#pragma once

#include <string>

namespace ms
{
	std::string decode_network_string(const std::string& value);
	std::string encode_network_string(const std::string& value);
}
