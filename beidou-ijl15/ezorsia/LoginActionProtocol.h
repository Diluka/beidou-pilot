// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Wire format for the native login/creation action lane. Kept free of Windows
// headers so the parsing can be exercised with an offline contract test.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <sstream>
#include <string>

namespace BeiDouBridge {
namespace LoginAction {

struct ProtocolRequest {
    std::string requestId;
    std::string action;
    std::array<std::string, 3> arguments;
};

// Standard Base64; "-" means an absent argument.
inline bool DecodeBase64(const std::string& text, std::string& output) {
    output.clear();
    if (text == "-") return true;
    if (text.empty() || text.size() % 4 != 0) return false;
    const auto decode = [](char character) -> int {
        if (character >= 'A' && character <= 'Z') return character - 'A';
        if (character >= 'a' && character <= 'z') return character - 'a' + 26;
        if (character >= '0' && character <= '9') return character - '0' + 52;
        if (character == '+') return 62;
        if (character == '/') return 63;
        return -1;
    };
    for (std::size_t index = 0; index < text.size(); index += 4) {
        int values[4] = {};
        int padding = 0;
        for (int slot = 0; slot < 4; ++slot) {
            const char character = text[index + static_cast<std::size_t>(slot)];
            if (character == '=') {
                if (index + 4 != text.size() || slot < 2) return false;
                values[slot] = 0;
                ++padding;
            } else {
                if (padding != 0) return false;
                values[slot] = decode(character);
                if (values[slot] < 0) return false;
            }
        }
        const std::uint32_t chunk =
            (static_cast<std::uint32_t>(values[0]) << 18) | (static_cast<std::uint32_t>(values[1]) << 12)
            | (static_cast<std::uint32_t>(values[2]) << 6) | static_cast<std::uint32_t>(values[3]);
        output += static_cast<char>((chunk >> 16) & 0xFF);
        if (padding < 2) output += static_cast<char>((chunk >> 8) & 0xFF);
        if (padding < 1) output += static_cast<char>(chunk & 0xFF);
    }
    return true;
}

inline bool ParseAddress(const std::string& text, std::uint32_t& address) {
    if (text.size() < 3 || text.size() > 10 || text[0] != '0' || (text[1] != 'x' && text[1] != 'X')) return false;
    std::uint32_t value = 0;
    for (std::size_t index = 2; index < text.size(); ++index) {
        const char character = text[index];
        unsigned int digit = 0;
        if (character >= '0' && character <= '9')
            digit = static_cast<unsigned int>(character - '0');
        else if (character >= 'a' && character <= 'f')
            digit = static_cast<unsigned int>(character - 'a' + 10);
        else if (character >= 'A' && character <= 'F')
            digit = static_cast<unsigned int>(character - 'A' + 10);
        else
            return false;
        if (value > 0x0FFFFFFF) return false;
        value = (value << 4) | digit;
    }
    if (value < 0x00010000) return false;
    address = value;
    return true;
}

inline bool ParseInteger(const std::string& text, int maximum, int& value) {
    if (text.empty() || text.size() > 9) return false;
    int parsed = 0;
    for (const char character : text) {
        if (character < '0' || character > '9') return false;
        parsed = parsed * 10 + (character - '0');
        if (parsed > maximum) return false;
    }
    value = parsed;
    return true;
}

inline bool ValidRequestId(const std::string& text) {
    if (text.size() != 32) return false;
    for (const char character : text)
        if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f')
              || (character >= 'A' && character <= 'F')))
            return false;
    return true;
}

// One ASCII line: `1 <instance> <request_id> <action> <arg1> <arg2> <arg3>`.
// Arguments are Base64 or "-"; the caller validates instance/request identity.
inline bool ParseRequestLine(const std::string& line, std::string& instance, ProtocolRequest& request) {
    std::istringstream stream(line);
    unsigned int protocol = 0;
    std::string extra;
    if (!(stream >> protocol >> instance >> request.requestId >> request.action >> request.arguments[0]
          >> request.arguments[1] >> request.arguments[2])
        || protocol != 1 || (stream >> extra))
        return false;
    return true;
}

inline bool AddressArgument(const std::string& encoded, std::uint32_t& address) {
    std::string text;
    return DecodeBase64(encoded, text) && ParseAddress(text, address);
}

inline bool IntegerArgument(const std::string& encoded, int maximum, int& value) {
    std::string text;
    return DecodeBase64(encoded, text) && ParseInteger(text, maximum, value);
}

inline bool TextArgument(const std::string& encoded, std::string& text) {
    return DecodeBase64(encoded, text);
}

}
}
