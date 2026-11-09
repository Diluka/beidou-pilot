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
#include "Session.h"

#include "../Configuration.h"

namespace ms
{
	Session::Session() = default;

	Session::~Session()
	{
		close();
	}

	bool Session::init(const char* host, const char* port)
	{
		close();
		connected = socket.open(host, port);
		if (connected)
			cryptography = { socket.get_buffer() };
		return connected;
	}

	Error Session::init()
	{
		const auto host = Setting<ServerIP>::get().load();
		const auto port = Setting<ServerPort>::get().load();
		return init(host.c_str(), port.c_str()) ? Error::NONE : Error::CONNECTION;
	}

	void Session::close()
	{
		++generation;
		connected = false;
		pending.clear();
		socket.close();
	}

	void Session::reconnect(const char* address, const char* port)
	{
		init(address, port);
	}

	void Session::process(const int8_t* bytes, size_t available)
	{
		pending.insert(pending.end(), bytes, bytes + available);
		while (pending.size() >= HEADER_LENGTH)
		{
			const auto length = static_cast<uint16_t>(cryptography.check_length(pending.data()));
			if (length < OPCODE_LENGTH || length > MAX_PACKET_LENGTH)
				throw PacketError("Invalid incoming Maple packet length");
			const auto frame_length = HEADER_LENGTH + length;
			if (pending.size() < frame_length)
				return;

			std::vector<int8_t> packet(pending.begin() + HEADER_LENGTH, pending.begin() + frame_length);
			pending.erase(pending.begin(), pending.begin() + frame_length);
			cryptography.decrypt(packet.data(), packet.size());
			const auto packet_generation = generation;
			packetswitch.forward(packet.data(), packet.size());
			// Login/channel handlers can reconnect and install a new IV while handling this packet.
			if (generation != packet_generation || !connected)
				return;
		}
	}

	void Session::write(int8_t* bytes, size_t length)
	{
		if (!connected)
			return;
		int8_t header[HEADER_LENGTH];
		cryptography.create_header(header, length);
		cryptography.encrypt(bytes, length);
		if (!socket.dispatch(header, HEADER_LENGTH) || !socket.dispatch(bytes, length))
			close();
	}

	void Session::read()
	{
		if (!connected)
			return;
		const auto available = socket.receive(&connected);
		if (!connected)
		{
			close();
			return;
		}
		if (available)
			process(socket.get_buffer(), available);
	}

	void Session::reconnect()
	{
		const auto host = Setting<ServerIP>::get().load();
		const auto port = Setting<ServerPort>::get().load();
		reconnect(host.c_str(), port.c_str());
	}

	bool Session::is_connected() const
	{
		return connected;
	}
}
