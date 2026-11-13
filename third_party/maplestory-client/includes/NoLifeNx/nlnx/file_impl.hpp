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

#pragma once
#include "file.hpp"
#include "node_impl.hpp"
#include <memory>
#include <string_view>
#include <vector>

namespace nl {
    // Storage for the IMG parser's in-memory node compatibility view.
    struct _file_data {
        node::data const * node_table = nullptr;
        uint32_t node_count = 0;
        uint32_t string_count = 0;
        uint32_t bitmap_count = 0;
        uint32_t audio_count = 0;
        std::vector<node::data> owned_nodes;
        std::vector<std::string_view> owned_strings;
        std::shared_ptr<void> owner;
        std::string_view get_string_view(uint32_t index) const;
    };
}
