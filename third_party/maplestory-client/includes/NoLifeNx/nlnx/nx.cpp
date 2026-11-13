//////////////////////////////////////////////////////////////////////////////
// NoLifeNx - Part of the NoLifeStory project                               //
// Copyright © 2013 Peter Atashian                                          //
//                                                                          //
// This program is free software: you can redistribute it and/or modify     //
// it under the terms of the GNU Affero General Public License as           //
// published by the Free Software Foundation, either version 3 of the       //
// License, or (at your option) any later version.                          //
//                                                                          //
// This program is distributed in the hope that it will be useful,          //
// but WITHOUT ANY WARRANTY; without even the implied warranty of           //
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            //
// GNU Affero General Public License for more details.                      //
//                                                                          //
// You should have received a copy of the GNU Affero General Public License //
// along with this program.  If not, see <http://www.gnu.org/licenses/>.    //
//////////////////////////////////////////////////////////////////////////////
#include "nx.hpp"
#include "file.hpp"
#include "node.hpp"

#include <vector>
#include <memory>
#include <utility>

namespace nl
{
	namespace nx
	{
		std::vector<std::unique_ptr<file>> files;

		node add_file(file&& value)
		{
			files.emplace_back(new file(std::move(value)));
			return *files.back();
		}

		node Base, Character, Effect, Etc, Item, Map, Map001, Map002, Map2, Mob, Mob001, Mob002, Mob2, Morph, Npc, Quest, Reactor, Skill, Skill001, Skill002, Skill003, Sound, Sound001, Sound002, Sound2, String, TamingMob, UI;

	}
}
