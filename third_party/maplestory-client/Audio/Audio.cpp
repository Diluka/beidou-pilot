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
#include "Audio.h"

namespace ms
{
    Sound::Sound(Name) : id(0) {}
    Sound::Sound(int32_t) : id(0) {}
    Sound::Sound(nl::node) : id(0) {}
    Sound::Sound() : id(0) {}
    void Sound::play() const {}
    Error Sound::init() { return Error::NONE; }
    void Sound::close() {}
    bool Sound::set_sfxvolume(uint8_t) { return true; }
    Music::Music(std::string value) : path(std::move(value)) {}
    void Music::play() const {}
    void Music::play_once() const {}
    Error Music::init() { return Error::NONE; }
    bool Music::set_bgmvolume(uint8_t) { return true; }
}
