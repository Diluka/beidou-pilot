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
#include "OtherChar.h"

#include "../Constants.h"

#include <cmath>
#include "../Gameplay/MovementReplay.h"

namespace ms
{
	OtherChar::OtherChar(int32_t charid, const CharLook& look, uint16_t level, int16_t job, const std::string& name, int8_t stance, Point<int16_t> position) : Char(charid, look, name), level(level), job(job)
	{
		set_position(position);

		lastmove.xpos = position.x();
		lastmove.ypos = position.y();
		lastmove.newstate = stance;

		attackspeed = 6;
		attacking = false;
	}

	int8_t OtherChar::update(const Physics& physics)
	{
		if (replayActive)
		{
			replayAccumulator = static_cast<uint16_t>(replayAccumulator + Constants::TIMESTEP);

			while (!replay.Empty() && replayAccumulator >= replay.StepMs())
			{
				const uint16_t step = replay.StepMs();
				replayAccumulator = static_cast<uint16_t>(replayAccumulator - step);
				const auto before = replay.LastSample();
				const auto after = replay.Advance(step);
				replayMotion = { after.x, after.y, true, after.x - before.x, after.y - before.y, step };
			}

			if (replay.Empty())
				replayActive = false;

			const MovementReplay::Sample& sample = replay.LastSample();
			phobj.x = sample.x;
			phobj.y = sample.y;
			phobj.hspeed = 0.0;
			phobj.vspeed = 0.0;

			if (sample.fh != 0)
				phobj.fhid = sample.fh;

			if (!attacking)
				set_state(sample.state);
		}
		else
		{
			if (replayMotion.known) replayMotion.delta_x = replayMotion.delta_y = 0;
			if (!attacking) set_state(lastmove.newstate);
		}

		physics.get_fht().update_fh(phobj);

		bool aniend = Char::update(physics, get_stancespeed());

		if (aniend && attacking)
			attacking = false;

		return get_layer();
	}

	MotionSample OtherChar::get_motion() const
	{
		if (!replayMotion.known) return phobj.get_motion();
		MotionSample result = replayMotion;
		result.x = phobj.crnt_x();
		result.y = phobj.crnt_y();
		return result;
	}

	void OtherChar::send_movement(const std::vector<Movement>& newmoves)
	{
		if (newmoves.empty())
			return;

		// Remote users advance the received path with the same 30/33ms replay clock
		// as the original Remote User update (docs/V17_EXTENDED_MOTION_RULES.md §10).
		replay.Reset(Point<int16_t>(static_cast<int16_t>(std::llround(phobj.crnt_x())),
		                            static_cast<int16_t>(std::llround(phobj.crnt_y()))),
		             std::vector<Movement>(newmoves));
		replayAccumulator = 0;
		replayActive = true;
		lastmove = newmoves.back();
	}

	void OtherChar::update_skill(int32_t skillid, uint8_t skilllevel)
	{
		skilllevels[skillid] = skilllevel;
	}

	void OtherChar::update_speed(uint8_t as)
	{
		attackspeed = as;
	}

	void OtherChar::update_look(const LookEntry& newlook)
	{
		look = newlook;

		uint8_t laststate = lastmove.newstate;
		set_state(laststate);
	}

	int8_t OtherChar::get_integer_attackspeed() const
	{
		return attackspeed;
	}

	uint16_t OtherChar::get_level() const
	{
		return level;
	}

	int32_t OtherChar::get_skilllevel(int32_t skillid) const
	{
		auto iter = skilllevels.find(skillid);

		if (iter == skilllevels.end())
			return 0;

		return iter->second;
	}
}