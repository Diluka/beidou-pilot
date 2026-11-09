//////////////////////////////////////////////////////////////////////////////////
//	This file is part of the continued Journey MMORPG client					//
//	Copyright (C) 2015-2019  Daniel Allendorf, Ryan Payton						//
//																				//
//	This program is free software: you can redistribute it and/or modify		//
//	it under the terms of the GNU Affero General Public License as published by	//
//	the Free Software Foundation, either version 3 of the License, or			//
//	(at your option) any later version.											//
//																				//
//	This program is distributed in the hope that it will be useful,				//
//	but WITHOUT ANY WARRANTY; without even the implied warranty of				//
//	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the				//
//	GNU Affero General Public License for more details.							//
//																				//
//	You should have received a copy of the GNU Affero General Public License	//
//	along with this program.  If not, see <https://www.gnu.org/licenses/>.		//
//////////////////////////////////////////////////////////////////////////////////
#include "SocketAsio.h"

#ifdef USE_ASIO
#include <cerrno>
#include <cstring>
#include <iostream>
#include <netdb.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

namespace ms
{
	SocketAsio::SocketAsio() = default;

	SocketAsio::~SocketAsio()
	{
		close();
	}

	bool SocketAsio::open(const char* address, const char* port)
	{
		close();
		addrinfo hints{};
		hints.ai_family = AF_INET;
		hints.ai_socktype = SOCK_STREAM;
		addrinfo* endpoints = nullptr;
		const auto resolution = getaddrinfo(address, port, &hints, &endpoints);
		if (resolution != 0)
		{
			std::cerr << "TCP address resolution failed: " << gai_strerror(resolution) << '\n';
			return false;
		}

		for (auto endpoint = endpoints; endpoint; endpoint = endpoint->ai_next)
		{
			descriptor = ::socket(endpoint->ai_family, endpoint->ai_socktype | SOCK_CLOEXEC, endpoint->ai_protocol);
			if (descriptor < 0)
				continue;
			const timeval timeout{5, 0};
			if (setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0
				|| setsockopt(descriptor, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) != 0)
			{
				close();
				continue;
			}
			if (::connect(descriptor, endpoint->ai_addr, endpoint->ai_addrlen) == 0)
				break;
			close();
		}
		freeaddrinfo(endpoints);
		if (descriptor < 0)
		{
			std::cerr << "TCP connection failed: " << std::strerror(errno) << '\n';
			return false;
		}

		size_t received = 0;
		size_t expected = 2;
		while (received < expected)
		{
			const auto count = ::recv(descriptor, buffer + received, expected - received, 0);
			if (count < 0 && errno == EINTR)
				continue;
			if (count <= 0)
			{
				std::cerr << "Incomplete Maple handshake\n";
				close();
				return false;
			}
			received += static_cast<size_t>(count);
			if (received == 2)
			{
				const auto body_length = static_cast<uint8_t>(buffer[0])
					| (static_cast<uint8_t>(buffer[1]) << 8);
				if (body_length != 14)
				{
					std::cerr << "Unsupported Maple handshake length: " << body_length << '\n';
					close();
					return false;
				}
				expected += body_length;
			}
		}

		if (static_cast<uint8_t>(buffer[2]) != 83 || buffer[3] != 0
			|| buffer[4] != 1 || buffer[5] != 0 || buffer[6] != '1'
			|| buffer[15] != 8)
		{
			std::cerr << "Unsupported Maple version, patch or locale in handshake\n";
			close();
			return false;
		}
		return true;
	}

	bool SocketAsio::close()
	{
		if (descriptor < 0)
			return true;
		const auto fd = descriptor;
		descriptor = -1;
		::shutdown(fd, SHUT_RDWR);
		return ::close(fd) == 0;
	}

	size_t SocketAsio::receive(bool* connected)
	{
		ssize_t count;
		do
		{
			count = ::recv(descriptor, buffer, sizeof(buffer), MSG_DONTWAIT);
		} while (count < 0 && errno == EINTR);
		if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
			return 0;
		if (count <= 0)
		{
			*connected = false;
			return 0;
		}
		return static_cast<size_t>(count);
	}

	const int8_t* SocketAsio::get_buffer() const
	{
		return buffer;
	}

	bool SocketAsio::dispatch(const int8_t* bytes, size_t length)
	{
		size_t sent = 0;
		while (sent < length)
		{
			const auto count = ::send(descriptor, bytes + sent, length - sent, MSG_NOSIGNAL);
			if (count < 0 && errno == EINTR)
				continue;
			if (count <= 0)
				return false;
			sent += static_cast<size_t>(count);
		}
		return true;
	}
}
#endif
