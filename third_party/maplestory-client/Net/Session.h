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
#pragma once

#include "Cryptography.h"
#include "PacketSwitch.h"
#include "../Error.h"
#include "../MapleStory.h"
#include "../Template/Singleton.h"
#include <vector>

#ifdef USE_ASIO
#include "SocketAsio.h"
#else
#include "SocketWinsock.h"
#endif

namespace ms
{
	class Session : public Singleton<Session>
	{
	public:
		Session();
		~Session();
		Error init();
		bool init(const char* host, const char* port);
		void close();
		void write(int8_t* bytes, size_t length);
		void read();
		void reconnect();
		void reconnect(const char* address, const char* port);
		bool is_connected() const;

	private:
		void process(const int8_t* bytes, size_t available);
		Cryptography cryptography;
		PacketSwitch packetswitch;
		std::vector<int8_t> pending;
		uint64_t generation = 0;
		bool connected = false;
#ifdef USE_ASIO
		SocketAsio socket;
#else
		SocketWinsock socket;
#endif
	};
}
