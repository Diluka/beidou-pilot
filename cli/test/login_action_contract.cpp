// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Offline contract for the native login/creation action wire format. The
// protocol arguments are Base64 on the wire; every action must decode before
// parsing, so a raw address/integer must never be accepted.
#include "LoginActionProtocol.h"

#include <cassert>
#include <cstdint>
#include <string>

namespace {

using BeiDouBridge::LoginAction::AddressArgument;
using BeiDouBridge::LoginAction::DecodeBase64;
using BeiDouBridge::LoginAction::IntegerArgument;
using BeiDouBridge::LoginAction::ParseAddress;
using BeiDouBridge::LoginAction::ParseInteger;
using BeiDouBridge::LoginAction::ParseRequestLine;
using BeiDouBridge::LoginAction::ProtocolRequest;
using BeiDouBridge::LoginAction::TextArgument;

std::string Encode(const std::string& text) {
    static const char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string encoded;
    std::size_t index = 0;
    while (index + 2 < text.size()) {
        const std::uint32_t chunk = (static_cast<unsigned char>(text[index]) << 16)
                                    | (static_cast<unsigned char>(text[index + 1]) << 8)
                                    | static_cast<unsigned char>(text[index + 2]);
        encoded += alphabet[(chunk >> 18) & 0x3F];
        encoded += alphabet[(chunk >> 12) & 0x3F];
        encoded += alphabet[(chunk >> 6) & 0x3F];
        encoded += alphabet[chunk & 0x3F];
        index += 3;
    }
    if (index + 1 == text.size()) {
        const std::uint32_t chunk = static_cast<unsigned char>(text[index]) << 16;
        encoded += alphabet[(chunk >> 18) & 0x3F];
        encoded += alphabet[(chunk >> 12) & 0x3F];
        encoded += "==";
    } else if (index + 2 == text.size()) {
        const std::uint32_t chunk =
            (static_cast<unsigned char>(text[index]) << 16) | (static_cast<unsigned char>(text[index + 1]) << 8);
        encoded += alphabet[(chunk >> 18) & 0x3F];
        encoded += alphabet[(chunk >> 12) & 0x3F];
        encoded += alphabet[(chunk >> 6) & 0x3F];
        encoded += '=';
    }
    return encoded;
}

void DecodeBase64AcceptsPaddedAndPlainValues() {
    std::string output;
    assert(DecodeBase64("-", output) && output.empty());
    assert(DecodeBase64("bmc5OWQxNmQ=", output) && output == "ng99d16d");
    assert(DecodeBase64("MHgxYjI5MGFkYw==", output) && output == "0x1b290adc");
    assert(DecodeBase64("YWJj", output) && output == "abc");
    assert(DecodeBase64("YTI0NGZhMTA4ZjAw", output) && output == "a244fa108f00");
}

void DecodeBase64RejectsMalformedValues() {
    std::string output;
    assert(!DecodeBase64("", output));
    assert(!DecodeBase64("abc", output));
    assert(!DecodeBase64("ab=c", output));
    assert(!DecodeBase64("=abc", output));
    assert(!DecodeBase64("a=bc", output));
    assert(!DecodeBase64("ab!d", output));
    assert(!DecodeBase64("ab==c===", output));
}

void AddressParsingRejectsRawAndEncodedFormsDifferently() {
    std::uint32_t address = 0;
    assert(ParseAddress("0x1b290adc", address) && address == 0x1b290adcU);
    assert(ParseAddress("0X00010000", address) && address == 0x00010000U);
    assert(!ParseAddress("0x1b290adc0", address));
    assert(!ParseAddress("0xffff", address));
    assert(!ParseAddress("1b290adc", address));
    assert(!ParseAddress("0x1b290adg", address));
    // Regression: the wire carries Base64, so a raw argument must not parse.
    assert(!ParseAddress("MHgxYjI5MGFkYw==", address));
    assert(AddressArgument(Encode("0x1b290adc"), address) && address == 0x1b290adcU);
    assert(!AddressArgument("0x1b290adc", address));
}

void IntegerParsingIsBounded() {
    int value = 0;
    assert(ParseInteger("0", 1, value) && value == 0);
    assert(ParseInteger("1019", 2000, value) && value == 1019);
    assert(!ParseInteger("2001", 2000, value));
    assert(!ParseInteger("-1", 2000, value));
    assert(!ParseInteger("", 2000, value));
    assert(!ParseInteger("1a", 2000, value));
    assert(IntegerArgument(Encode("1000"), 2000, value) && value == 1000);
    assert(!IntegerArgument("1000", 2000, value));
}

void TextArgumentDecodesCredentialsAndNames() {
    std::string text;
    assert(TextArgument("-", text) && text.empty());
    assert(TextArgument(Encode("ng99d16d"), text) && text == "ng99d16d");
    assert(TextArgument(Encode("a244fa108f00"), text) && text == "a244fa108f00");
    assert(TextArgument(Encode("NativeXY"), text) && text == "NativeXY");
    assert(!TextArgument("not-base64", text));
}

void RequestLineRequiresProtocolIdentityAndThreeArguments() {
    ProtocolRequest request;
    std::string instance;
    assert(ParseRequestLine("1 392-1dd7383-1e4d14a "
                            "2a06d6274c314252b87a80dc50cd058a submit_login MHgxYjI5MGFkYw== "
                            "bmc5OWQxNmQ= YTI0NGZhMTA4ZjAw",
                            instance, request));
    assert(instance == "392-1dd7383-1e4d14a");
    assert(request.requestId == "2a06d6274c314252b87a80dc50cd058a");
    assert(request.action == "submit_login");
    assert(request.arguments[0] == "MHgxYjI5MGFkYw==");
    assert(request.arguments[1] == "bmc5OWQxNmQ=");
    assert(request.arguments[2] == "YTI0NGZhMTA4ZjAw");

    assert(
        ParseRequestLine("1 i 00000000000000000000000000000000 accept_terms MHgxYjI5MGFkYw== - -", instance, request));
    assert(request.arguments[1] == "-");

    assert(
        !ParseRequestLine("2 i 00000000000000000000000000000000 accept_terms MHgxYjI5MGFkYw== - -", instance, request));
    assert(!ParseRequestLine("1 i 00000000000000000000000000000000", instance, request));
    assert(
        !ParseRequestLine("1 i 00000000000000000000000000000000 accept_terms MHgxYjI5MGFkYw== -", instance, request));
    assert(!ParseRequestLine("1 i 00000000000000000000000000000000 accept_terms MHgxYjI5MGFkYw== - - extra", instance,
                             request));
    assert(!ParseRequestLine("", instance, request));
}

}

int main() {
    DecodeBase64AcceptsPaddedAndPlainValues();
    DecodeBase64RejectsMalformedValues();
    AddressParsingRejectsRawAndEncodedFormsDifferently();
    IntegerParsingIsBounded();
    TextArgumentDecodesCredentialsAndNames();
    RequestLineRequiresProtocolIdentityAndThreeArguments();
    return 0;
}
