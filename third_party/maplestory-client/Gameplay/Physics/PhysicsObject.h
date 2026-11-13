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

#include "../../Constants.h"

#include "../../Template/Interpolated.h"
#include "../../Template/Point.h"

namespace ms
{
	// Complete logical-update displacement, not the integrator's next-step speed.
	struct MotionSample
	{
		double x;
		double y;
		bool known;
		double delta_x;
		double delta_y;
		uint16_t interval_ms;
	};

	// Structure that contains all properties for movement calculations
	struct MovingObject
	{
		Linear<double> x;
		Linear<double> y;
		double hspeed = 0.0;
		double vspeed = 0.0;

		// Bracket one complete native update. First measurement and explicit
		// repositioning stay unknown; measured zero remains distinguishable.
		void begin_motion_sample()
		{
			motion_start_x = crnt_x();
			motion_start_y = crnt_y();
			motion_continuous = motion_sampled;
			motion_known = false;
		}

		void end_motion_sample()
		{
			motion_known = motion_continuous;
			motion_delta_x = crnt_x() - motion_start_x;
			motion_delta_y = crnt_y() - motion_start_y;
			motion_sampled = true;
		}

		void reset_motion_sample()
		{
			motion_sampled = false;
			motion_continuous = false;
			motion_known = false;
		}

		MotionSample get_motion() const
		{
			return { crnt_x(), crnt_y(), motion_known,
				motion_known ? motion_delta_x : 0.0,
				motion_known ? motion_delta_y : 0.0,
				motion_known ? Constants::TIMESTEP : uint16_t{0} };
		}

		void normalize()
		{
			x.normalize();
			y.normalize();
		}

		void move()
		{
			x += hspeed;
			y += vspeed;
		}

		void set_x(double d)
		{
			x.set(d);
			reset_motion_sample();
		}

		void set_y(double d)
		{
			y.set(d);
			reset_motion_sample();
		}

		void limitx(double d)
		{
			x = d;
			hspeed = 0.0;
		}

		void limity(double d)
		{
			y = d;
			vspeed = 0.0;
		}

		void movexuntil(double d, uint16_t delay)
		{
			if (delay)
			{
				double hdelta = d - x.get();
				hspeed = Constants::TIMESTEP * hdelta / delay;
			}
		}

		void moveyuntil(double d, uint16_t delay)
		{
			if (delay)
			{
				double vdelta = d - y.get();
				vspeed = Constants::TIMESTEP * vdelta / delay;
			}
		}

		bool hmobile() const
		{
			return hspeed != 0.0;
		}

		bool vmobile() const
		{
			return vspeed != 0.0;
		}

		bool mobile() const
		{
			return hmobile() || vmobile();
		}

		double crnt_x() const
		{
			return x.get();
		}

		double crnt_y() const
		{
			return y.get();
		}

		double next_x() const
		{
			return x + hspeed;
		}

		double next_y() const
		{
			return y + vspeed;
		}

		int16_t get_x() const
		{
			double rounded = std::round(x.get());
			return static_cast<int16_t>(rounded);
		}

		int16_t get_y() const
		{
			double rounded = std::round(y.get());
			return static_cast<int16_t>(rounded);
		}

		int16_t get_last_x() const
		{
			double rounded = std::round(x.last());
			return static_cast<int16_t>(rounded);
		}

		int16_t get_last_y() const
		{
			double rounded = std::round(y.last());
			return static_cast<int16_t>(rounded);
		}

		Point<int16_t> get_position() const
		{
			return { get_x(), get_y() };
		}

		int16_t get_absolute_x(double viewx, float alpha) const
		{
			double interx = x.normalized() ? std::round(x.get()) : x.get(alpha);

			return static_cast<int16_t>(
				std::round(interx + viewx)
				);
		}

		int16_t get_absolute_y(double viewy, float alpha) const
		{
			double intery = y.normalized() ? std::round(y.get()) : y.get(alpha);

			return static_cast<int16_t>(
				std::round(intery + viewy)
				);
		}

		Point<int16_t> get_absolute(double viewx, double viewy, float alpha) const
		{
			return { get_absolute_x(viewx, alpha), get_absolute_y(viewy, alpha) };
		}

	private:
		// Owned by this native lifetime; no rounded-position or global-OID history.
		// set_x/set_y invalidate explicit jumps, including jumps inside an update.
		double motion_start_x = 0.0;
		double motion_start_y = 0.0;
		double motion_delta_x = 0.0;
		double motion_delta_y = 0.0;
		bool motion_sampled = false;
		bool motion_continuous = false;
		bool motion_known = false;
	};

	// Structure that contains all properties necessary for physics calculations
	struct PhysicsObject : public MovingObject
	{
		// Determines which physics engine to use
		enum Type
		{
			NORMAL,
			ICE,
			SWIMMING,
			FLYING,
			FIXATED
		};

		enum Flag
		{
			NOGRAVITY = 0x0001,
			TURNATEDGES = 0x0002,
			CHECKBELOW = 0x0004
		};

		Type type = Type::NORMAL;
		int32_t flags = 0;
		uint16_t fhid = 0;
		double fhslope = 0.0;
		int8_t fhlayer = 0;
		double groundbelow = 0.0;
		bool onground = true;
		bool enablejd = false;

		double hforce = 0.0;
		double vforce = 0.0;
		double hacc = 0.0;
		double vacc = 0.0;

		bool is_flag_set(Flag f)
		{
			return (flags & f) != 0;
		}

		bool is_flag_not_set(Flag f)
		{
			return !is_flag_set(f);
		}

		void set_flag(Flag f)
		{
			flags |= f;
		}

		void clear_flag(Flag f)
		{
			flags &= ~f;
		}

		void clear_flags()
		{
			flags = 0;
		}
	};
}