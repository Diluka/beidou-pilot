#include "Encoding.h"
#include "PacketError.h"

#include <iconv.h>
#include <stdexcept>

namespace ms
{
	std::string decode_network_string(const std::string& value)
	{
		if (value.empty())
			return {};
		auto descriptor = iconv_open("UTF-8", "GBK");
		if (descriptor == reinterpret_cast<iconv_t>(-1))
			throw std::runtime_error("GBK decoder is unavailable");
		std::string result(value.size() * 4, '\0');
		auto input = const_cast<char*>(value.data());
		auto output = result.data();
		auto remaining_input = value.size();
		auto remaining_output = result.size();
		auto converted = iconv(descriptor, &input, &remaining_input, &output, &remaining_output);
		iconv_close(descriptor);
		if (converted == static_cast<size_t>(-1))
			throw PacketError("Invalid GBK string in server packet");
		result.resize(result.size() - remaining_output);
		return result;
	}

	std::string encode_network_string(const std::string& value)
	{
		if (value.empty())
			return {};
		auto descriptor = iconv_open("GBK", "UTF-8");
		if (descriptor == reinterpret_cast<iconv_t>(-1))
			throw std::runtime_error("GBK encoder is unavailable");
		std::string result(value.size() * 2, '\0');
		auto input = const_cast<char*>(value.data());
		auto output = result.data();
		auto remaining_input = value.size();
		auto remaining_output = result.size();
		auto converted = iconv(descriptor, &input, &remaining_input, &output, &remaining_output);
		iconv_close(descriptor);
		if (converted == static_cast<size_t>(-1))
			throw std::invalid_argument("Text cannot be encoded as GBK");
		result.resize(result.size() - remaining_output);
		return result;
	}
}
