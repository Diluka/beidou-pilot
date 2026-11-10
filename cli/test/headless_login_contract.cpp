#include "Configuration.h"
#include "Net/Handlers/Helpers/LoginParser.h"
#include "Net/Session.h"

#include <array>
#include <stdexcept>
#include <string>

namespace {
std::string connectedAddress;
std::string connectedPort;
}

// Replace the connection boundary; keep the real packet parser and target setting.
namespace ms {
Cryptography::Cryptography() = default;
Cryptography::~Cryptography() = default;
PacketSwitch::PacketSwitch() = default;
SocketAsio::SocketAsio() = default;
SocketAsio::~SocketAsio() = default;
Session::Session() = default;
Session::~Session() = default;
void Session::reconnect(const char* address, const char* port) {
    connectedAddress = address;
    connectedPort = port;
}
}

int main() {
    ms::Setting<ms::ServerIP>::get().save("10.24.0.7");
    for (const auto address : {std::array<uint8_t, 4>{127, 0, 0, 1}, {127, 5, 4, 3}, {10, 24, 0, 9}}) {
        const std::array<int8_t, 7> bytes = {0, static_cast<int8_t>(address[0]), static_cast<int8_t>(address[1]),
                                            static_cast<int8_t>(address[2]), static_cast<int8_t>(address[3]),
                                            static_cast<int8_t>(7576 & 0xff), static_cast<int8_t>(7576 >> 8)};
        ms::InPacket packet(bytes.data(), bytes.size());
        ms::LoginParser::parse_login(packet);
        const auto expected = address[0] == 127 ? "10.24.0.7" : "10.24.0.9";
        if (connectedAddress != expected || connectedPort != "7576")
            throw std::runtime_error("channel announcement did not retain its target and port");
    }
}
