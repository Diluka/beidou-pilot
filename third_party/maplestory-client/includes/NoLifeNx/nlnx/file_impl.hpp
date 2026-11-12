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
#pragma pack(push, 1)
    struct file::header {
        uint32_t const magic;
        uint32_t const node_count;
        uint64_t const node_offset;
        uint32_t const string_count;
        uint64_t const string_offset;
        uint32_t const bitmap_count;
        uint64_t const bitmap_offset;
        uint32_t const audio_count;
        uint64_t const audio_offset;
    };
#pragma pack(pop)
    struct _file_data {
        void const * base = nullptr;
        node::data const * node_table = nullptr;
        uint64_t const * string_table = nullptr;
        uint64_t const * bitmap_table = nullptr;
        uint64_t const * audio_table = nullptr;
        file::header const * header = nullptr;
        bool memory_backed = false;
        uint32_t node_count = 0;
        uint32_t string_count = 0;
        uint32_t bitmap_count = 0;
        uint32_t audio_count = 0;
        std::vector<node::data> owned_nodes;
        std::vector<std::string_view> owned_strings;
        std::shared_ptr<void> owner;
#ifdef _WIN32
        void * file_handle = nullptr;
        void * map = nullptr;
#else
        int file_handle = 0;
        size_t size = 0;
#endif
        std::string_view get_string_view(uint32_t index) const;
    };
}
