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
#include "ImgFiles.h"

#ifdef USE_NX
#include <filesystem>
#include <stdexcept>
#include <string>

#include "ImgResourceFile.h"
#include <nlnx/node.hpp>
#include <nlnx/nx.hpp>

namespace ms
{
	namespace ImgFiles
	{
		Error init()
		{
			try
			{
				const auto root = std::filesystem::current_path();
				auto add = [](std::filesystem::path const& path, bool base_only = false) {
					if (!std::filesystem::is_directory(path))
						throw std::runtime_error("Missing IMG directory: " + path.string());
					return nl::nx::add_file(load_img_directory(path, base_only));
				};
				auto optional = [&](char const* name) {
					const auto path = root / name;
					return std::filesystem::is_directory(path) ? add(path) : nl::node{};
				};

				nl::nx::Base = add(root, true);
				nl::nx::Character = add(root / "Character");
				nl::nx::Effect = add(root / "Effect");
				nl::nx::Etc = add(root / "Etc");
				nl::nx::Item = add(root / "Item");
				nl::nx::Map = add(root / "Map");
				nl::nx::Map001 = std::filesystem::is_directory(root / "Map001") ? add(root / "Map001") : nl::nx::Map;
				nl::nx::Map002 = std::filesystem::is_directory(root / "Map002") ? add(root / "Map002") : nl::nx::Map;
				nl::nx::Map2 = std::filesystem::is_directory(root / "Map2") ? add(root / "Map2") : nl::nx::Map;
				nl::nx::Mob = add(root / "Mob");
				nl::nx::Mob001 = std::filesystem::is_directory(root / "Mob001") ? add(root / "Mob001") : nl::nx::Mob;
				nl::nx::Mob002 = std::filesystem::is_directory(root / "Mob002") ? add(root / "Mob002") : nl::nx::Mob;
				nl::nx::Mob2 = std::filesystem::is_directory(root / "Mob2") ? add(root / "Mob2") : nl::nx::Mob;
				nl::nx::Morph = optional("Morph");
				nl::nx::Npc = add(root / "Npc");
				nl::nx::Quest = optional("Quest");
				nl::nx::Reactor = add(root / "Reactor");
				nl::nx::Skill = add(root / "Skill");
				nl::nx::Skill001 = std::filesystem::is_directory(root / "Skill001") ? add(root / "Skill001") : nl::nx::Skill;
				nl::nx::Skill002 = std::filesystem::is_directory(root / "Skill002") ? add(root / "Skill002") : nl::nx::Skill;
				nl::nx::Skill003 = std::filesystem::is_directory(root / "Skill003") ? add(root / "Skill003") : nl::nx::Skill;
				nl::nx::Sound = optional("Sound");
				nl::nx::Sound001 = std::filesystem::is_directory(root / "Sound001") ? add(root / "Sound001") : nl::nx::Sound;
				nl::nx::Sound002 = std::filesystem::is_directory(root / "Sound002") ? add(root / "Sound002") : nl::nx::Sound;
				nl::nx::Sound2 = std::filesystem::is_directory(root / "Sound2") ? add(root / "Sound2") : nl::nx::Sound;
				nl::nx::String = add(root / "String");
				nl::nx::TamingMob = optional("TamingMob");
				nl::nx::UI = optional("UI");
			}
			catch (const std::exception& ex)
			{
				static const std::string message = ex.what();

				return Error(Error::Code::NLNX, message.c_str());
			}

			return Error::Code::NONE;
		}
	}
}
#endif
