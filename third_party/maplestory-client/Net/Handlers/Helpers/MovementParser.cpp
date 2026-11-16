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
#include "MovementParser.h"

namespace ms
{
	std::vector<Movement> MovementParser::parse_movements(InPacket& recv)
	{
		// V17 inbound path layout (docs/V17_EXTENDED_MOTION_RULES.md §10):
		// command widths and field identities are from the original decoder 0x68A33C
		// and encoder 0x68A563. Legacy consumers still read xpos/ypos for the relative
		// commands, so those keep the old velocity-in-position behavior until the path
		// replay consumer lands; the parsed velocity facts are also kept in vx/vy.
		std::vector<Movement> movements;
		uint8_t length = static_cast<uint8_t>(recv.read_byte());

		for (uint8_t i = 0; i < length; ++i)
		{
			Movement fragment;
			fragment.command = static_cast<uint8_t>(recv.read_byte());

			switch (fragment.command)
			{
			case 0:
			case 5:
			case 17:
				fragment.type = Movement::ABSOLUTE;
				fragment.xpos = recv.read_short();
				fragment.ypos = recv.read_short();
				fragment.lastx = recv.read_short(); // current endpoint vx (px/s)
				fragment.lasty = recv.read_short(); // current endpoint vy (px/s)
				fragment.vx = fragment.lastx;
				fragment.vy = fragment.lasty;
				fragment.fh = recv.read_short();
				fragment.newstate = static_cast<uint8_t>(recv.read_byte());
				fragment.duration = recv.read_short();
				break;
			case 15:
				fragment.type = Movement::JUMPDOWN;
				fragment.xpos = recv.read_short();
				fragment.ypos = recv.read_short();
				fragment.lastx = recv.read_short();
				fragment.lasty = recv.read_short();
				fragment.vx = fragment.lastx;
				fragment.vy = fragment.lasty;
				fragment.fh = recv.read_short();
				fragment.extra = static_cast<uint16_t>(recv.read_short());
				fragment.newstate = static_cast<uint8_t>(recv.read_byte());
				fragment.duration = recv.read_short();
				break;
			case 1:
			case 2:
			case 6:
			case 12:
			case 13:
			case 16:
			case 18:
			case 19:
			case 20:
			case 22:
				fragment.type = Movement::RELATIVE;
				fragment.lastx = recv.read_short(); // vx payload
				fragment.lasty = recv.read_short(); // vy payload
				fragment.vx = fragment.lastx;
				fragment.vy = fragment.lasty;
				// Legacy consumer compatibility; replay consumers use vx/vy.
				fragment.xpos = fragment.lastx;
				fragment.ypos = fragment.lasty;
				fragment.newstate = static_cast<uint8_t>(recv.read_byte());
				fragment.duration = recv.read_short();
				break;
			case 3:
			case 4:
			case 7:
			case 8:
			case 9:
			case 11:
				fragment.type = Movement::CHAIR;
				fragment.xpos = recv.read_short();
				fragment.ypos = recv.read_short();
				fragment.fh = recv.read_short();
				fragment.newstate = static_cast<uint8_t>(recv.read_byte());
				fragment.duration = recv.read_short();
				break;
			case 14:
				fragment.type = Movement::RELATIVE;
				fragment.lastx = recv.read_short();
				fragment.lasty = recv.read_short();
				fragment.vx = fragment.lastx;
				fragment.vy = fragment.lasty;
				fragment.xpos = fragment.lastx;
				fragment.ypos = fragment.lasty;
				fragment.extra = static_cast<uint16_t>(recv.read_short());
				fragment.newstate = static_cast<uint8_t>(recv.read_byte());
				fragment.duration = recv.read_short();
				break;
			case 10:
				fragment.type = Movement::NONE;
				recv.read_byte(); // change-equip payload byte
				break;
			case 21:
				fragment.type = Movement::NONE;
				fragment.newstate = static_cast<uint8_t>(recv.read_byte());
				fragment.duration = recv.read_short();
				break;
			default:
				// Unknown command layout is not guessed; only the command byte is
				// consumed, so a future version must be re-derived before use.
				fragment.type = Movement::NONE;
				break;
			}

			movements.push_back(fragment);
		}

		return movements;
	}
}
