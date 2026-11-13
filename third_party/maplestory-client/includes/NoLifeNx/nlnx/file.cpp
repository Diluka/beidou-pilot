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

#include "file_impl.hpp"
#include "node_impl.hpp"
#include <utility>

namespace nl {
    file::file(file&& other) : m_data(std::exchange(other.m_data, nullptr)) {}
    file& file::operator=(file&& other) {
        if (this != &other) {
            close();
            m_data = std::exchange(other.m_data, nullptr);
        }
        return *this;
    }
    file::~file() {
        close();
    }
    void file::open_nodes(std::vector<node::data>&& nodes, std::vector<std::string_view>&& strings,
                          std::shared_ptr<void> owner) {
        close();
        m_data = new data();
        m_data->owned_nodes = std::move(nodes);
        m_data->owned_strings = std::move(strings);
        m_data->owner = std::move(owner);
        m_data->node_table = m_data->owned_nodes.data();
        m_data->node_count = static_cast<uint32_t>(m_data->owned_nodes.size());
        m_data->string_count = static_cast<uint32_t>(m_data->owned_strings.size());
    }
    void file::close() {
        delete m_data;
        m_data = nullptr;
    }
    node file::root() const {
        return {m_data->node_table, m_data};
    }
    file::operator node() const {
        return root();
    }
    uint32_t file::string_count() const {
        return m_data->string_count;
    }
    uint32_t file::bitmap_count() const {
        return m_data->bitmap_count;
    }
    uint32_t file::audio_count() const {
        return m_data->audio_count;
    }
    uint32_t file::node_count() const {
        return m_data->node_count;
    }
    std::string file::get_string(uint32_t i) const {
        return std::string(m_data->get_string_view(i));
    }
    std::string_view _file_data::get_string_view(uint32_t i) const {
        return owned_strings[i];
    }
}
