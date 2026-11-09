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

#include "../MapleStory.h"

#ifdef USE_ASIO
#include "NetConstants.h"

namespace ms
{
	// The name is retained for the existing client API; the headless backend uses POSIX TCP.
	class SocketAsio
	{
	public:
		SocketAsio();
		~SocketAsio();
		SocketAsio(const SocketAsio&) = delete;
		SocketAsio& operator=(const SocketAsio&) = delete;

		bool open(const char* address, const char* port);
		bool close();
		size_t receive(bool* connected);
		const int8_t* get_buffer() const;
		bool dispatch(const int8_t* bytes, size_t length);

	private:
		int descriptor = -1;
		int8_t buffer[MAX_PACKET_LENGTH];
	};
}
#endif
