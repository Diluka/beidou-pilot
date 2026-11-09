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

#include <fstream>
#include <vector>
#include <memory>
#include <stdexcept>

namespace nl
{
	namespace nx
	{
		std::vector<std::unique_ptr<file>> files;

		bool exists(std::string name)
		{
			return std::ifstream(name).is_open();
		}

		node add_file(std::string name)
		{
			if (!exists(name))
				return {};

			files.emplace_back(new file(name));

			return *files.back();
		}

		node Base, Character, Effect, Etc, Item, Map, Map001, Map002, Map2, Mob, Mob001, Mob002, Mob2, Morph, Npc, Quest, Reactor, Skill, Skill001, Skill002, Skill003, Sound, Sound001, Sound002, Sound2, String, TamingMob, UI;

		void load_all()
		{
			if (exists("Base.nx"))
			{
				Base = add_file("Base.nx");
				Character = add_file("Character.nx");
				Effect = add_file("Effect.nx");
				Etc = add_file("Etc.nx");
				Item = add_file("Item.nx");
				Map = add_file("Map.nx");
				Map001 = exists("Map001.nx") ? add_file("Map001.nx") : Map;
				Map002 = exists("Map002.nx") ? add_file("Map002.nx") : Map;
				Map2 = exists("Map2.nx") ? add_file("Map2.nx") : Map;
				Mob = add_file("Mob.nx");
				Mob001 = exists("Mob001.nx") ? add_file("Mob001.nx") : Mob;
				Mob002 = exists("Mob002.nx") ? add_file("Mob002.nx") : Mob;
				Mob2 = exists("Mob2.nx") ? add_file("Mob2.nx") : Mob;
				Morph = add_file("Morph.nx");
				Npc = add_file("Npc.nx");
				Quest = add_file("Quest.nx");
				Reactor = add_file("Reactor.nx");
				Skill = add_file("Skill.nx");
				Skill001 = exists("Skill001.nx") ? add_file("Skill001.nx") : Skill;
				Skill002 = exists("Skill002.nx") ? add_file("Skill002.nx") : Skill;
				Skill003 = exists("Skill003.nx") ? add_file("Skill003.nx") : Skill;
				Sound = add_file("Sound.nx");
				Sound001 = exists("Sound001.nx") ? add_file("Sound001.nx") : Sound;
				Sound002 = exists("Sound002.nx") ? add_file("Sound002.nx") : Sound;
				Sound2 = exists("Sound2.nx") ? add_file("Sound2.nx") : Sound;
				String = add_file("String.nx");
				TamingMob = add_file("TamingMob.nx");
				UI = add_file("UI.nx");
			}
			else if (exists("Data.nx"))
			{
				Base = add_file("Data.nx");
				Character = Base["Character"];
				Effect = Base["Effect"];
				Etc = Base["Etc"];
				Item = Base["Item"];
				Map = Base["Map"];
				Map001 = Base["Map001"];
				Map002 = Base["Map002"];
				Map2 = Base["Map2"];
				Mob = Base["Mob"];
				Mob001 = Base["Mob001"];
				Mob002 = Base["Mob002"];
				Mob2 = Base["Mob2"];
				Morph = Base["Morph"];
				Npc = Base["Npc"];
				Quest = Base["Quest"];
				Reactor = Base["Reactor"];
				Skill = Base["Skill"];
				Skill001 = Base["Skill001"];
				Skill002 = Base["Skill002"];
				Skill003 = Base["Skill003"];
				Sound = Base["Sound"];
				Sound001 = Base["Sound001"];
				Sound002 = Base["Sound002"];
				Sound2 = Base["Sound2"];
				String = Base["String"];
				TamingMob = Base["TamingMob"];
				UI = Base["UI"];
			}
			else
			{
				throw std::runtime_error("Failed to locate nx files.");
			}
		}
	}
}
