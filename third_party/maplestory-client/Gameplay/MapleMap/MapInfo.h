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

#include "../../Template/Optional.h"
#include "../../Template/Point.h"
#include "../../Template/Range.h"

#include <vector>

namespace ms
{
	class Seat
	{
	public:
		Seat(nl::node source);

		bool inrange(Point<int16_t> position) const;
		Point<int16_t> getpos() const;

	private:
		Point<int16_t> pos;
	};

	class Ladder
	{
	public:
		Ladder(nl::node source);

		bool is_ladder() const;
		int16_t get_x() const;
		// Original ladder object +0x10/+0x14 (map y1/y2).
		int16_t get_top() const;
		int16_t get_bottom() const;
		// Original ladder object +0x08; top exits at top-5 when set, otherwise clamps
		// to top and stays attached (0x9CC727-0x9CC779). Map field mapping is the
		// #250 inference (uf); a direct uf=0 top probe remains open.
		bool exits_at_top() const;

	private:
		int16_t x;
		int16_t y1;
		int16_t y2;
		bool ladder;
		bool exitsAtTop;
	};

	class MapInfo
	{
	public:
		MapInfo(nl::node src, Range<int16_t> walls, Range<int16_t> borders);
		MapInfo();

		bool is_underwater() const;
		bool is_flying() const;
		// Original field attribute multipliers from map info `fs` (0xA45CD6 ->
		// 0x500D61 writes FA+0x00 and FA+0x0C; runtime probe on 211040000:
		// fs=0.2 => FA+00=FA+0C=0.2). Default 1.0 when the key is absent.
		double get_field_force() const;
		double get_field_drag() const;
		std::string get_bgm() const;
		Range<int16_t> get_walls() const;
		Range<int16_t> get_borders() const;

		// Find a seat the player's position
		Optional<const Seat> findseat(Point<int16_t> position) const;
		// Original ladder query 0xA45B03: the segment's x range is expanded by 10 on
		// both sides and its y range must overlap [top, bottom]; the first hit wins.
		Optional<const Ladder> findladder(Point<int16_t> start, Point<int16_t> end) const;

	private:
		int32_t fieldlimit;
		bool cloud;
		std::string bgm;
		std::string mapdesc;
		std::string mapname;
		std::string streetname;
		std::string mapmark;
		bool swim;
		bool fly;
		bool town;
		double fieldForce;
		double fieldDrag;
		bool hideminimap;
		Range<int16_t> mapwalls;
		Range<int16_t> mapborders;
		std::vector<Seat> seats;
		std::vector<Ladder> ladders;
	};
}