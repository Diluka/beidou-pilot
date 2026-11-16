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
#include "FootholdTree.h"

#include <algorithm>
#include <cmath>
#include <iostream>

namespace ms
{
	FootholdTree::FootholdTree(nl::node src)
	{
		int16_t leftw = 30000;
		int16_t rightw = -30000;
		int16_t botb = -30000;
		int16_t topb = 30000;

		for (auto basef : src)
		{
			uint8_t layer;

			try
			{
				layer = static_cast<uint8_t>(std::stoi(basef.name()));
			}
			catch (const std::exception& ex)
			{
				LOG(LOG_ERROR, __func__ << ": " << ex.what());
				continue;
			}

			for (auto midf : basef)
			{
				for (auto lastf : midf)
				{
					uint16_t id;

					try
					{
						id = static_cast<uint16_t>(std::stoi(lastf.name()));
					}
					catch (const std::exception& ex)
					{
						LOG(LOG_ERROR, __func__ << ": " << ex.what());
						continue;
					}

					const Foothold& foothold = footholds.emplace(
						std::piecewise_construct,
						std::forward_as_tuple(id),
						std::forward_as_tuple(lastf, id, layer)
					).first->second;

					if (foothold.l() < leftw)
						leftw = foothold.l();

					if (foothold.r() > rightw)
						rightw = foothold.r();

					if (foothold.b() > botb)
						botb = foothold.b();

					if (foothold.t() < topb)
						topb = foothold.t();

					if (foothold.is_wall())
						continue;

					int16_t start = foothold.l();
					int16_t end = foothold.r();

					for (int16_t i = start; i <= end; i++)
						footholdsbyx.emplace(i, id);
				}
			}
		}

		walls = { leftw + 25, rightw - 25 };
		borders = { topb - 300, botb + 100 };
	}

	FootholdTree::FootholdTree() {}

	void FootholdTree::limit_movement(PhysicsObject& phobj) const
	{
		if (phobj.hmobile())
		{
			double crnt_x = phobj.crnt_x();
			double next_x = phobj.next_x();

			bool left = phobj.hspeed < 0.0f;
			double wall = get_wall(phobj.fhid, left, phobj.next_y());
			bool collision = left ? crnt_x >= wall && next_x <= wall : crnt_x <= wall && next_x >= wall;

			if (!collision && phobj.is_flag_set(PhysicsObject::Flag::TURNATEDGES))
			{
				wall = get_edge(phobj.fhid, left);
				collision = left ? crnt_x >= wall && next_x <= wall : crnt_x <= wall && next_x >= wall;
			}

			if (collision)
			{
				phobj.limitx(wall);
				phobj.clear_flag(PhysicsObject::Flag::TURNATEDGES);
			}
		}

		if (phobj.vmobile())
		{
			double crnt_y = phobj.crnt_y();
			double next_y = phobj.next_y();

			auto ground = Range<double>(
				get_fh(phobj.fhid).ground_below(phobj.crnt_x()),
				get_fh(phobj.fhid).ground_below(phobj.next_x())
				);

			bool collision = crnt_y <= ground.first() && next_y >= ground.second();

			if (collision)
			{
				phobj.limity(ground.second());

				limit_movement(phobj);
			}
			else
			{
				if (next_y < borders.first())
					phobj.limity(borders.first());
				else if (next_y > borders.second())
					phobj.limity(borders.second());
			}
		}
	}

	void FootholdTree::update_fh(PhysicsObject& phobj) const
	{
		if (phobj.type == PhysicsObject::Type::FIXATED && phobj.fhid > 0)
			return;

		const Foothold& curfh = get_fh(phobj.fhid);
		bool checkslope = false;

		double x = phobj.crnt_x();
		double y = phobj.crnt_y();

		if (phobj.onground)
		{
			if (std::floor(x) > curfh.r())
				phobj.fhid = curfh.next();
			else if (std::ceil(x) < curfh.l())
				phobj.fhid = curfh.prev();

			if (phobj.fhid == 0)
				phobj.fhid = get_fhid_below(x, y);
			else
				checkslope = true;
		}
		else
		{
			phobj.fhid = get_fhid_below(x, y);

			if (phobj.fhid == 0)
				return;
		}

		const Foothold& nextfh = get_fh(phobj.fhid);
		phobj.fhslope = nextfh.slope();

		double ground = nextfh.ground_below(x);

		if (phobj.vspeed == 0.0 && checkslope)
		{
			double vdelta = abs(phobj.fhslope);

			if (phobj.fhslope < 0.0)
				vdelta *= (ground - y);
			else if (phobj.fhslope > 0.0)
				vdelta *= (y - ground);

			if (curfh.slope() != 0.0 || nextfh.slope() != 0.0)
			{
				if (phobj.hspeed > 0.0 && vdelta <= phobj.hspeed)
					phobj.y = ground;
				else if (phobj.hspeed < 0.0 && vdelta >= phobj.hspeed)
					phobj.y = ground;
			}
		}

		phobj.onground = phobj.y == ground;

		if (phobj.enablejd || phobj.is_flag_set(PhysicsObject::Flag::CHECKBELOW))
		{
			uint16_t belowid = get_fhid_below(x, nextfh.ground_below(x) + 1.0);

			if (belowid > 0)
			{
				double nextground = get_fh(belowid).ground_below(x);
				phobj.enablejd = (nextground - ground) < 600.0;
				phobj.groundbelow = ground + 1.0;
			}
			else
			{
				phobj.enablejd = false;
			}

			phobj.clear_flag(PhysicsObject::Flag::CHECKBELOW);
		}

		if (phobj.fhlayer == 0 || phobj.onground)
			phobj.fhlayer = nextfh.layer();

		if (phobj.fhid == 0)
		{
			phobj.fhid = curfh.id();
			phobj.limitx(curfh.x1());
		}
	}

	const Foothold& FootholdTree::get_fh(uint16_t fhid) const
	{
		auto iter = footholds.find(fhid);

		if (iter == footholds.end())
			return nullfh;

		return iter->second;
	}

	double FootholdTree::get_wall(uint16_t curid, bool left, double fy) const
	{
		auto shorty = static_cast<int16_t>(fy);
		Range<int16_t> vertical(shorty - 50, shorty - 1);
		const Foothold& cur = get_fh(curid);

		if (left)
		{
			const Foothold& prev = get_fh(cur.prev());

			if (prev.is_blocking(vertical))
				return cur.l();

			const Foothold& prev_prev = get_fh(prev.prev());

			if (prev_prev.is_blocking(vertical))
				return prev.l();

			return walls.first();
		}
		else
		{
			const Foothold& next = get_fh(cur.next());

			if (next.is_blocking(vertical))
				return cur.r();

			const Foothold& next_next = get_fh(next.next());

			if (next_next.is_blocking(vertical))
				return next.r();

			return walls.second();
		}
	}

	double FootholdTree::get_edge(uint16_t curid, bool left) const
	{
		const Foothold& fh = get_fh(curid);

		if (left)
		{
			uint16_t previd = fh.prev();

			if (!previd)
				return fh.l();

			const Foothold& prev = get_fh(previd);
			uint16_t prev_previd = prev.prev();

			if (!prev_previd)
				return prev.l();

			return walls.first();
		}
		else
		{
			uint16_t nextid = fh.next();

			if (!nextid)
				return fh.r();

			const Foothold& next = get_fh(nextid);
			uint16_t next_nextid = next.next();

			if (!next_nextid)
				return next.r();

			return walls.second();
		}
	}

	uint16_t FootholdTree::get_fhid_below(double fx, double fy) const
	{
		uint16_t ret = 0;
		double comp = borders.second();

		int16_t x = static_cast<int16_t>(fx);
		auto range = footholdsbyx.equal_range(x);

		for (auto iter = range.first; iter != range.second; ++iter)
		{
			const Foothold& fh = footholds.at(iter->second);
			double ycomp = fh.ground_below(fx);

			if (comp >= ycomp && ycomp >= fy)
			{
				comp = ycomp;
				ret = fh.id();
			}
		}

		return ret;
	}

	int16_t FootholdTree::get_y_below(Point<int16_t> position) const
	{
		if (uint16_t fhid = get_fhid_below(position.x(), position.y()))
		{
			const Foothold& fh = get_fh(fhid);

			return static_cast<int16_t>(fh.ground_below(position.x()));
		}
		else
		{
			return borders.second();
		}
	}

	Range<int16_t> FootholdTree::get_walls() const
	{
		return walls;
	}

	Range<int16_t> FootholdTree::get_borders() const
	{
		return borders;
	}

	FootholdInfo FootholdTree::GetFoothold(uint16_t id) const
	{
		FootholdInfo info;
		const auto iter = footholds.find(id);

		if (iter == footholds.end())
			return info;

		const Foothold& foothold = iter->second;
		info.valid = true;
		info.id = foothold.id();
		info.x1 = foothold.x1();
		info.x2 = foothold.x2();
		info.y1 = foothold.y1();
		info.y2 = foothold.y2();
		info.slope = foothold.slope();
		info.length = foothold.length();
		info.layer = foothold.layer();
		info.prev = foothold.prev();
		info.next = foothold.next();
		return info;
	}

	double FootholdTree::GroundBelow(double x, const FootholdInfo& foothold) const
	{
		if (foothold.x1 == foothold.x2)
			return foothold.y1;

		return foothold.slope * (x - static_cast<double>(foothold.x1)) + static_cast<double>(foothold.y1);
	}

	std::vector<uint16_t> FootholdTree::footholds_in_x_range(double minx, double maxx) const
	{
		std::vector<uint16_t> result;
		const auto first = static_cast<int16_t>(std::floor(minx));
		const auto last = static_cast<int16_t>(std::ceil(maxx));

		for (int32_t column = static_cast<int32_t>(first); column <= static_cast<int32_t>(last); ++column)
		{
			const auto range = footholdsbyx.equal_range(static_cast<int16_t>(column));

			for (auto iter = range.first; iter != range.second; ++iter)
			{
				if (std::find(result.begin(), result.end(), iter->second) == result.end())
					result.push_back(iter->second);
			}
		}

		return result;
	}

	GroundHit FootholdTree::QueryGroundBelow(double x, double y, double maxDrop) const
	{
		GroundHit hit;
		const auto column = static_cast<int16_t>(std::floor(x));
		const auto range = footholdsbyx.equal_range(column);

		for (auto iter = range.first; iter != range.second; ++iter)
		{
			const Foothold& foothold = get_fh(iter->second);

			if (foothold.is_wall())
				continue;

			const double left = std::min<double>(foothold.x1(), foothold.x2());
			const double right = std::max<double>(foothold.x1(), foothold.x2());

			if (x < left - 0.001 || x > right + 0.001)
				continue;

			const double ground = foothold.ground_below(x);

			if (ground < y - 0.001 || ground > y + maxDrop)
				continue;

			if (!hit.found || ground < hit.groundY)
			{
				hit.found = true;
				hit.footholdId = foothold.id();
				hit.groundY = ground;
				hit.slope = foothold.slope();
				hit.layer = foothold.layer();
			}
		}

		return hit;
	}

	bool FootholdTree::JumpDownAvailable(double x, double groundY, double& groundbelow) const
	{
		const uint16_t belowid = get_fhid_below(x, groundY + 1.0);

		if (!belowid)
			return false;

		const double nextground = get_fh(belowid).ground_below(x);

		if (nextground - groundY >= 600.0)
			return false;

		groundbelow = groundY + 1.0;
		return true;
	}

	LocalSweepResult FootholdTree::SweepLocalMotion(const LocalSweepInput& input) const
	{
		LocalSweepResult result;
		result.x = input.x;
		result.y = input.y;
		result.vx = input.vx;
		result.vy = input.vy;
		result.onGround = input.onGround;
		result.footholdId = input.footholdId;

		const auto initial = GetFoothold(input.footholdId);

		if (initial.valid)
		{
			result.footholdSlope = initial.slope;
			result.footholdLayer = initial.layer;
		}

		double dx = input.dx;
		double dy = input.dy;

		// 1) Whole-segment horizontal limit: walls first, then rush-style edges.
		if (dx != 0.0)
		{
			const bool left = dx < 0.0;
			const double horizontalY = input.y + dy;
			double wall = get_wall(input.footholdId, left, horizontalY);
			bool collision = left ? input.x >= wall && input.x + dx <= wall
														: input.x <= wall && input.x + dx >= wall;

			if (collision)
			{
				dx = wall - input.x;
				result.vx = 0.0;
				result.hitWall = true;
			}
			else if (input.stopAtEdges && input.footholdId)
			{
				wall = get_edge(input.footholdId, left);
				collision = left ? input.x >= wall && input.x + dx <= wall
												 : input.x <= wall && input.x + dx >= wall;

				if (collision)
				{
					dx = wall - input.x;
					result.vx = 0.0;
					result.stoppedAtEdge = true;
				}
			}
		}

		const double targetX = input.x + dx;
		const double targetY = input.y + dy;

		if (result.onGround)
		{
			// 2) Ground: follow the connected platform chain, otherwise fall off the edge.
			bool attached = false;
			FootholdInfo foothold = GetFoothold(input.footholdId);

			for (int8_t link = 0; link < 8 && foothold.valid && !attached; ++link)
			{
				const double low = std::min<double>(foothold.x1, foothold.x2);
				const double high = std::max<double>(foothold.x1, foothold.x2);

				if (targetX >= low - 1.0 && targetX <= high + 1.0)
				{
					result.x = targetX;
					result.y = GroundBelow(targetX, foothold);
					result.onGround = true;
					result.footholdId = foothold.id;
					result.footholdSlope = foothold.slope;
					result.footholdLayer = foothold.layer;
					attached = true;
					break;
				}

				const uint16_t neighbor = targetX > high ? foothold.next : targetX < low ? foothold.prev : 0;

				if (!neighbor)
					break;

				foothold = GetFoothold(neighbor);
			}

			if (!attached)
			{
				const GroundHit hit = QueryGroundBelow(targetX, input.y, 1.0);

				if (hit.found)
				{
					result.x = targetX;
					result.y = hit.groundY;
					result.onGround = true;
					result.footholdId = hit.footholdId;
					result.footholdSlope = hit.slope;
					result.footholdLayer = hit.layer;
					attached = true;
				}
			}

			if (attached)
			{
				const double length = std::sqrt(1.0 + result.footholdSlope * result.footholdSlope);
				const double cos = 1.0 / length;
				const double sin = result.footholdSlope / length;
				const double tangent = result.vx * cos + result.vy * sin;
				result.vx = tangent * cos;
				result.vy = tangent * sin;
			}
			else
			{
				// Walked off the end of every connected platform: the rest of the
				// displacement is airborne, gravity resumes on the next step.
				result.x = targetX;
				result.y = targetY;
				result.onGround = false;
				result.footholdId = 0;
				result.footholdSlope = 0.0;
				result.leftGround = true;
			}
		}
		else if (dy > 0.0)
		{
			// 3) Air: earliest platform surface crossed by the whole step.
			const double minx = std::min(input.x, targetX);
			const double maxx = std::max(input.x, targetX);
			const std::vector<uint16_t> candidates = footholds_in_x_range(minx, maxx);
			double best = 2.0;
			uint16_t bestid = 0;

			for (const uint16_t id : candidates)
			{
				if (id == input.ignoreFootholdId)
					continue;

				const FootholdInfo foothold = GetFoothold(id);

				if (!foothold.valid)
					continue;

				const double denominator = dy - foothold.slope * dx;

				if (std::abs(denominator) < 1e-12)
					continue;

				const double t = (static_cast<double>(foothold.y1) - input.y
													+ foothold.slope * (input.x - static_cast<double>(foothold.x1)))
											 / denominator;

				if (t <= 0.0 || t > 1.0 + 1e-9 || t >= best)
					continue;

				const double crossX = input.x + t * dx;
				const double left = std::min<double>(foothold.x1, foothold.x2);
				const double right = std::max<double>(foothold.x1, foothold.x2);

				if (crossX < left - 0.01 || crossX > right + 0.01)
					continue;

				best = t;
				bestid = id;
			}

			if (bestid)
			{
				const FootholdInfo foothold = GetFoothold(bestid);
				result.x = input.x + best * dx;
				result.y = GroundBelow(result.x, foothold);
				result.onGround = true;
				result.footholdId = bestid;
				result.footholdSlope = foothold.slope;
				result.footholdLayer = foothold.layer;
				result.landed = true;

				const double length = std::sqrt(1.0 + foothold.slope * foothold.slope);
				const double cos = 1.0 / length;
				const double sin = foothold.slope / length;
				const double tangent = result.vx * cos + result.vy * sin;
				result.vx = tangent * cos;
				result.vy = tangent * sin;
			}
			else
			{
				result.x = targetX;
				result.y = targetY;
			}
		}
		else
		{
			result.x = targetX;
			result.y = targetY;
		}

		if (result.y < borders.first())
		{
			result.y = borders.first();
			result.vy = 0.0;
		}
		else if (result.y > borders.second())
		{
			result.y = borders.second();
			result.vy = 0.0;
		}

		return result;
	}
}
