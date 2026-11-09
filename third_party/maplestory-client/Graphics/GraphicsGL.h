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

#include "Text.h"
#include "../Constants.h"
#include "../Error.h"
#include <nlnx/bitmap.hpp>

namespace ms
{
    // Headless presentation backend. Simulation and animation remain in their owners.
    class GraphicsGL : public Singleton<GraphicsGL>
    {
    public:
        GraphicsGL() = default;
        Error init();
        void reinit();
        void clear();
        void addbitmap(const nl::bitmap& bitmap);
        void draw(const nl::bitmap& bitmap, const Rectangle<int16_t>& rectangle, const Range<int16_t>& vertical, const Range<int16_t>& horizontal, const Color& color, float angle);
        Text::Layout createlayout(const std::string& text, Text::Font font, Text::Alignment alignment, Color::Name color, int16_t maxwidth, bool formatted, int16_t line_adj);
        void drawtext(const DrawArgument& args, const Range<int16_t>& vertical, const std::string& text, const Text::Layout& layout, Text::Font font, Color::Name color, Text::Background background);
        void drawrectangle(int16_t x, int16_t y, int16_t width, int16_t height, float red, float green, float blue, float alpha);
        void drawscreenfill(float red, float green, float blue, float alpha);
        void lock();
        void unlock();
        void flush(float opacity);
        void clearscene();
    };
}
