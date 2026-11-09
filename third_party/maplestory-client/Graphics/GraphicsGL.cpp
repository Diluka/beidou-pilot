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
#include "GraphicsGL.h"

namespace ms
{
    Error GraphicsGL::init() { return Error::NONE; }
    void GraphicsGL::reinit() {}
    void GraphicsGL::clear() {}
    void GraphicsGL::addbitmap(const nl::bitmap&) {}
    void GraphicsGL::draw(const nl::bitmap&, const Rectangle<int16_t>&, const Range<int16_t>&, const Range<int16_t>&, const Color&, float) {}
    void GraphicsGL::drawtext(const DrawArgument&, const Range<int16_t>&, const std::string&, const Text::Layout&, Text::Font, Color::Name, Text::Background) {}
    void GraphicsGL::drawrectangle(int16_t, int16_t, int16_t, int16_t, float, float, float, float) {}
    void GraphicsGL::drawscreenfill(float, float, float, float) {}
    void GraphicsGL::lock() {}
    void GraphicsGL::unlock() {}
    void GraphicsGL::flush(float) {}
    void GraphicsGL::clearscene() {}

    Text::Layout GraphicsGL::createlayout(const std::string& text, Text::Font, Text::Alignment, Color::Name color, int16_t maxwidth, bool, int16_t line_adj)
    {
        // UI callers retain a bounded layout without opening a font or graphics device.
        constexpr int16_t advance = 6;
        const auto line_height = static_cast<int16_t>(12 + line_adj);
        std::vector<Text::Layout::Line> lines;
        std::vector<int16_t> advances(text.size() + 1);
        int16_t x = 0;
        int16_t y = line_height;
        int16_t width = 0;
        size_t first = 0;
        for (size_t i = 0; i < text.size(); ++i)
        {
            if (text[i] == '\n' || (maxwidth > 0 && x + advance > maxwidth))
            {
                lines.push_back({{{first, i, Text::A12M, color}}, {0, y}});
                width = std::max(width, x);
                x = 0;
                y += line_height;
                first = text[i] == '\n' ? i + 1 : i;
            }
            advances[i] = x;
            if (text[i] != '\n')
                x += advance;
        }
        advances[text.size()] = x;
        lines.push_back({{{first, text.size(), Text::A12M, color}}, {0, y}});
        return {lines, advances, std::max(width, x), y, x, y};
    }
}
