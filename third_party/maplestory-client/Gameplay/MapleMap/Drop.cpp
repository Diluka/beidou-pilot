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
#include "Drop.h"
#include "DropDisplay.h"
#include "DropFallDisplay.h"

namespace ms
{
	Drop::Drop(int32_t id, int32_t own, Point<int16_t> start, Point<int16_t> dst, int8_t type, int8_t mode, bool pldrp) : MapObject(id)
	{
		owner = own;
		this->start = start;
		this->mode = mode;
		set_position(start.x(), start.y());
		dest = dst;
		pickuptype = type;
		playerdrop = pldrp;

		angle.set(0.0f);
		opacity.set(1.0f);
		moved = 0.0f;
		fallMs = 0;
		looter = nullptr;

		switch (mode)
		{
		case 0:
		case 1:
			state = Drop::State::DROPPED;
			break;
		case 2:
			state = Drop::State::FLOATING;
			phobj.type = PhysicsObject::Type::FIXATED;
			set_position(dest.x(), dest.y() - get_icon_half_height());
			break;
		case 3:
			state = Drop::State::PICKEDUP;
			phobj.vspeed = -5.0f;
			break;
		}
	}

	int8_t Drop::update(const Physics& physics)
	{
		if (instantRemove)
			return -1;

		if (state == Drop::State::PICKEDUP)
		{
			physics.move_object(phobj);
		}

		if (state == Drop::State::DROPPED || state == Drop::State::DESCENDING)
		{
			static const float SPINSTEP = 0.2f;
			fallMs += Constants::TIMESTEP;
			angle += SPINSTEP;

			if (state == Drop::State::DROPPED)
			{
				const double anchorY = dest.y() - get_icon_half_height();
				const double velocity = DropFallVelocityForPickupType(pickuptype);
				const int32_t durationMs = DropFallDurationFor(start.y(), anchorY, pickuptype);
				set_position(DropFallX(start.x(), dest.x(), fallMs, durationMs), DropFallY(start.y(), fallMs, velocity));

				if (fallMs >= durationMs)
				{
					if (DropFallNeedsDescent(start.y(), anchorY))
					{
						state = Drop::State::DESCENDING;
						fallMs = 0;
					}
					else
					{
						phobj.type = PhysicsObject::Type::FIXATED;
						state = Drop::State::FLOATING;
						angle.set(0.0f);
						set_position(dest.x(), anchorY);
					}
				}
			}
			else
			{
				const double anchorY = dest.y() - get_icon_half_height();
				const double velocity = DropFallVelocityForPickupType(pickuptype);
				set_position(dest.x(), DropDescendY(start.y(), fallMs, velocity));

				if (phobj.crnt_y() >= anchorY)
				{
					phobj.type = PhysicsObject::Type::FIXATED;
					state = Drop::State::FLOATING;
					angle.set(0.0f);
					set_position(dest.x(), anchorY);
				}
			}
		}

		if (state == Drop::State::FLOATING)
		{
			phobj.y = dest.y() - get_icon_half_height() + DropFloatingOffsetY(moved);
			moved = DropFloatingNextPhase(moved);
		}

		if (state == Drop::State::PICKEDUP)
		{
			static const uint16_t PICKUPTIME = 48;
			static const float OPCSTEP = 1.0f / PICKUPTIME;

			if (looter)
			{
				double hdelta = looter->x - phobj.x;
				phobj.hspeed = looter->hspeed / 2.0 + (hdelta - 16.0) / PICKUPTIME;
			}

			opacity -= OPCSTEP;

			if (opacity.last() <= OPCSTEP)
			{
				opacity.set(1.0f);

				MapObject::deactivate();
				return -1;
			}
		}

		return phobj.fhlayer;
	}

	void Drop::expire(int8_t type, const PhysicsObject* lt)
	{
		// V17 OnLeaveField 0x50663E removes the drop from the DropPool immediately for
		// every leave type and plays the pickup effect as a separate object. headless
		// has no separate effect, so keep the pool-removal timing (next object update
		// returns -1) instead of the old 48-step fade / fly-to-looter lifecycles.
		(void)lt;
		instantRemove = true;
	}

	Rectangle<int16_t> Drop::bounds() const
	{
		auto lt = get_position();
		auto rb = lt + Point<int16_t>(32, 32);

		return Rectangle<int16_t>(lt, rb);
	}
}