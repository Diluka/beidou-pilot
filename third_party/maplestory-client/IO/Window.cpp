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
#include "Window.h"

namespace ms
{
    Error Window::init() { return Error::NONE; }
    Error Window::initwindow() { return Error::NONE; }
    bool Window::not_closed() const { return true; }
    void Window::update() {}
    void Window::begin() const {}
    void Window::end() const {}
    void Window::fadeout(float, std::function<void()> procedure) { procedure(); }
    void Window::check_events() {}
    void Window::setclipboard(const std::string& text) const { clipboard = text; }
    std::string Window::getclipboard() const { return clipboard; }
    void Window::toggle_fullscreen() {}
}
