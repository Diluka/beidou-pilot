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

#include "Foothold.h"
#include "PhysicsObject.h"

#include <cstdint>
#include <unordered_map>
#include <vector>

namespace ms
{
	// Immutable geometry of one platform as consumed by local-character motion.
	struct FootholdInfo
	{
		bool valid = false;
		uint16_t id = 0;
		int16_t x1 = 0;
		int16_t x2 = 0;
		int16_t y1 = 0;
		int16_t y2 = 0;
		double slope = 0.0;
		double length = 0.0;
		uint8_t layer = 0;
		uint16_t prev = 0;
		uint16_t next = 0;
	};

	// A platform surface point found by a ground query.
	struct GroundHit
	{
		bool found = false;
		uint16_t footholdId = 0;
		double groundY = 0.0;
		double slope = 0.0;
		uint8_t layer = 0;
	};

	// A whole local-character step: start point plus the complete target displacement.
	// The legacy limit_movement/update_fh pair consumes per-8ms integrator speeds and
	// cannot be fed px/s or a 30ms displacement; this input is explicit instead.
	struct LocalSweepInput
	{
		double x = 0.0;
		double y = 0.0;
		double dx = 0.0;
		double dy = 0.0;
		double vx = 0.0;
		double vy = 0.0;
		uint16_t footholdId = 0;
		bool onGround = false;
		uint16_t ignoreFootholdId = 0;
		bool stopAtEdges = false;
	};

	struct LocalSweepResult
	{
		double x = 0.0;
		double y = 0.0;
		double vx = 0.0;
		double vy = 0.0;
		bool onGround = false;
		uint16_t footholdId = 0;
		double footholdSlope = 0.0;
		uint8_t footholdLayer = 0;
		bool landed = false;
		bool hitWall = false;
		bool stoppedAtEdge = false;
		bool leftGround = false;
	};

	// The collection of platforms in a maple map
	// Used for collision-detection
	class FootholdTree
	{
	public:
		FootholdTree(nl::node source);
		FootholdTree();

		// Takes an accelerated PhysicsObject and limits its movement based on the platforms in this tree
		void limit_movement(PhysicsObject& touse) const;
		// Updates a PhysicsObject's fhid based on it's position
		void update_fh(PhysicsObject& touse) const;
		// Determine the point on the ground below the specified position
		int16_t get_y_below(Point<int16_t> position) const;
		// Returns the leftmost and rightmost platform positions of the map
		Range<int16_t> get_walls() const;
		// Returns the topmost and bottommost platform positions of the map
		Range<int16_t> get_borders() const;

		// Immutable geometry for one platform id (zero id / unknown is invalid).
		FootholdInfo GetFoothold(uint16_t id) const;
		// Surface height of one platform at x (linear interpolation along the segment).
		double GroundBelow(double x, const FootholdInfo& foothold) const;
		// Nearest platform surface at or under (x, y), within maxDrop pixels.
		GroundHit QueryGroundBelow(double x, double y, double maxDrop) const;
		// Original jump-down support query: a platform below the current surface less
		// than 600px away enables a down jump; groundbelow is the current surface + 1.
		bool JumpDownAvailable(double x, double groundY, double& groundbelow) const;
		// One whole local-character step: wall/edge limit, platform connection, slope
		// following, air landing and map borders, committed as one end state.
		LocalSweepResult SweepLocalMotion(const LocalSweepInput& input) const;

	private:
		uint16_t get_fhid_below(double fx, double fy) const;
		double get_wall(uint16_t fhid, bool left, double fy) const;
		double get_edge(uint16_t fhid, bool left) const;
		const Foothold& get_fh(uint16_t fhid) const;
		std::vector<uint16_t> footholds_in_x_range(double minx, double maxx) const;

		std::unordered_map<uint16_t, Foothold> footholds;
		std::unordered_multimap<int16_t, uint16_t> footholdsbyx;

		Foothold nullfh;
		Range<int16_t> walls;
		Range<int16_t> borders;
	};
}