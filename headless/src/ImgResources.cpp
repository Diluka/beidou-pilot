// SPDX-License-Identifier: AGPL-3.0-or-later
#define NL_NO_PROGRESS_OUTPUT
#define NL_PRESERVE_UNRESOLVED_UOL
// IMG decoding is private to this resource provider. Upstream attribution: NOTICE.
//////////////////////////////////////////////////////////////////////////////////
//	This file is part of the continued NoLifeStory project						//
//	Copyright (C) 2014-2020  Peter Atashian, Ryan Payton						//
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

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define VC_EXTRALEAN
#define NOMINMAX
#include <Windows.h>
#else
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#endif

#include <algorithm>
#include <array>
#ifndef NL_NO_CODECVT
#include <codecvt>
#endif
#include <cstdint>
#include <cstring>
#ifndef NL_NO_STD_FILESYSTEM
#include <filesystem>
namespace sys = std::filesystem;
#else
#include <boost/filesystem.hpp>
namespace sys = boost::filesystem;
#endif
#include <iostream>
#include <locale>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <sstream>

namespace {
std::string u8string(const sys::path& path) {
#ifndef NL_NO_STD_FILESYSTEM
    return path.u8string();
#else
    return path.native();
#endif
}
}

using namespace std::string_literals;

namespace nl {
extern uint8_t key_bms[65536];
extern uint8_t key_gms[65536];
extern uint8_t key_kms[65536];
}

namespace nl::wz {
// Some typedefs
typedef char char8_t;
typedef uint32_t id_t;
typedef uint8_t key_t;
typedef int32_t int_t;
// The keys
// TODO - Use AES to generate these keys at runtime
using ::nl::key_bms;
using ::nl::key_gms;
using ::nl::key_kms;
key_t const* keys[3] = {key_bms, key_gms, key_kms};
// cp1252 table
char16_t const cp1252[0x100] = {
    0x0000, 0x0001, 0x0002, 0x0003, 0x0004, 0x0005, 0x0006, 0x0007, 0x0008, 0x0009, 0x000A, 0x000B, 0x000C, 0x000D,
    0x000E, 0x000F, 0x0010, 0x0011, 0x0012, 0x0013, 0x0014, 0x0015, 0x0016, 0x0017, 0x0018, 0x0019, 0x001A, 0x001B,
    0x001C, 0x001D, 0x001E, 0x001F, 0x0020, 0x0021, 0x0022, 0x0023, 0x0024, 0x0025, 0x0026, 0x0027, 0x0028, 0x0029,
    0x002A, 0x002B, 0x002C, 0x002D, 0x002E, 0x002F, 0x0030, 0x0031, 0x0032, 0x0033, 0x0034, 0x0035, 0x0036, 0x0037,
    0x0038, 0x0039, 0x003A, 0x003B, 0x003C, 0x003D, 0x003E, 0x003F, 0x0040, 0x0041, 0x0042, 0x0043, 0x0044, 0x0045,
    0x0046, 0x0047, 0x0048, 0x0049, 0x004A, 0x004B, 0x004C, 0x004D, 0x004E, 0x004F, 0x0050, 0x0051, 0x0052, 0x0053,
    0x0054, 0x0055, 0x0056, 0x0057, 0x0058, 0x0059, 0x005A, 0x005B, 0x005C, 0x005D, 0x005E, 0x005F, 0x0060, 0x0061,
    0x0062, 0x0063, 0x0064, 0x0065, 0x0066, 0x0067, 0x0068, 0x0069, 0x006A, 0x006B, 0x006C, 0x006D, 0x006E, 0x006F,
    0x0070, 0x0071, 0x0072, 0x0073, 0x0074, 0x0075, 0x0076, 0x0077, 0x0078, 0x0079, 0x007A, 0x007B, 0x007C, 0x007D,
    0x007E, 0x007F, 0x20AC, 0xFFFD, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039,
    0x0152, 0xFFFD, 0x017D, 0xFFFD, 0xFFFD, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122,
    0x0161, 0x203A, 0x0153, 0xFFFD, 0x017E, 0x0178, 0x00A0, 0x00A1, 0x00A2, 0x00A3, 0x00A4, 0x00A5, 0x00A6, 0x00A7,
    0x00A8, 0x00A9, 0x00AA, 0x00AB, 0x00AC, 0x00AD, 0x00AE, 0x00AF, 0x00B0, 0x00B1, 0x00B2, 0x00B3, 0x00B4, 0x00B5,
    0x00B6, 0x00B7, 0x00B8, 0x00B9, 0x00BA, 0x00BB, 0x00BC, 0x00BD, 0x00BE, 0x00BF, 0x00C0, 0x00C1, 0x00C2, 0x00C3,
    0x00C4, 0x00C5, 0x00C6, 0x00C7, 0x00C8, 0x00C9, 0x00CA, 0x00CB, 0x00CC, 0x00CD, 0x00CE, 0x00CF, 0x00D0, 0x00D1,
    0x00D2, 0x00D3, 0x00D4, 0x00D5, 0x00D6, 0x00D7, 0x00D8, 0x00D9, 0x00DA, 0x00DB, 0x00DC, 0x00DD, 0x00DE, 0x00DF,
    0x00E0, 0x00E1, 0x00E2, 0x00E3, 0x00E4, 0x00E5, 0x00E6, 0x00E7, 0x00E8, 0x00E9, 0x00EA, 0x00EB, 0x00EC, 0x00ED,
    0x00EE, 0x00EF, 0x00F0, 0x00F1, 0x00F2, 0x00F3, 0x00F4, 0x00F5, 0x00F6, 0x00F7, 0x00F8, 0x00F9, 0x00FA, 0x00FB,
    0x00FC, 0x00FD, 0x00FE, 0x00FF};

// Input memory mapped file
struct imapfile {
    char const* base = nullptr;
    char const* offset = nullptr;
#ifdef _WIN32
    void* file_handle = nullptr;
    void* map_handle = nullptr;

    void open(std::string p) {
        file_handle = CreateFileA(p.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                                  FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
        if (file_handle == INVALID_HANDLE_VALUE) throw std::runtime_error("Failed to open file " + p);
        map_handle = CreateFileMappingA(file_handle, nullptr, PAGE_READONLY, 0, 0, nullptr);
        if (map_handle == nullptr) throw std::runtime_error("Failed to create file mapping of file " + p);
        base = reinterpret_cast<char*>(MapViewOfFile(map_handle, FILE_MAP_READ, 0, 0, 0));
        if (base == nullptr) throw std::runtime_error("Failed to map view of file " + p);
        offset = base;
    }

    ~imapfile() {
        if (base) UnmapViewOfFile(base);
        if (map_handle) CloseHandle(map_handle);
        if (file_handle && file_handle != INVALID_HANDLE_VALUE) CloseHandle(file_handle);
    }
#else
    int file_handle = 0;
    size_t file_size = 0;

    void open(std::string p) {
        if (base) {
            munmap(const_cast<char*>(base), file_size);
            close(file_handle);
        }
        file_handle = ::open(p.c_str(), O_RDONLY);
        if (file_handle == -1) throw std::runtime_error("Failed to open file " + p);
        struct stat finfo;
        if (fstat(file_handle, &finfo) == -1)
            throw std::runtime_error("Failed to obtain file information of file " + p);
        file_size = finfo.st_size;
        base = reinterpret_cast<char const*>(mmap(nullptr, file_size, PROT_READ, MAP_SHARED, file_handle, 0));
        if (reinterpret_cast<intptr_t>(base) == -1)
            throw std::runtime_error("Failed to create memory mapping of file " + p);
        offset = base;
    }

    ~imapfile() {
        if (base) {
            munmap(const_cast<char*>(base), file_size);
            close(file_handle);
        }
    }
#endif
    size_t tell() { return static_cast<size_t>(offset - base); }

    void seek(size_t n) { offset = base + n; }

    void skip(size_t n) { offset += n; }

    template <typename T> T read() {
        auto& v = *reinterpret_cast<T const*>(offset);
        offset += sizeof(T);
        return v;
    }

    int32_t read_cint() {
        int8_t a = read<int8_t>();
        return a != -128 ? a : read<int32_t>();
    }
};

// Node stuff
#pragma pack(push, 1)

struct node {
    enum class type : uint16_t {
        none = 0,
        integer = 1,
        real = 2,
        string = 3,
        vector = 4,
        bitmap = 5,
        audio = 6,
        uol = 7
    };
    uint32_t name = 0;
    uint32_t children = 0;
    uint16_t num = 0;
    uint16_t source_order = 0;
    uint32_t source_file_id = UINT32_MAX;
    type data_type = type::none;

    union _data {
        int64_t integer = 0;
        double real;
        uint32_t string;
        int32_t vector[2];

        struct _bitmap {
            uint32_t id;
            uint16_t width;
            uint16_t height;
        } bitmap;

        struct _audio {
            uint32_t id;
            uint32_t length;
        } audio;
    } data;
};

#pragma pack(pop)

struct audio {
    uint32_t length;
    uint64_t data;
};

struct bitmap {
    uint64_t data;
    uint8_t const* key;
};

// The main class itself
struct ImgDecoder {
    // Variables
    imapfile in;
    std::vector<node> nodes = std::vector<node>{{node{}}};
    std::vector<std::pair<id_t, id_t>> nodes_to_sort;
    std::unordered_map<std::string, id_t> string_map;
    std::vector<std::string> strings;
    std::string str_buf;
    std::u16string wstr_buf;
#ifndef NL_NO_CODECVT
    std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t> convert;
#endif
    char8_t const* u8key = nullptr;
    char16_t const* u16key = nullptr;
    std::vector<id_t> uol_path;
    std::vector<std::vector<id_t>> uols;
    std::vector<id_t> link_path;
    std::vector<std::vector<id_t>> links;
    std::vector<bitmap> bitmaps;
    std::vector<audio> audios;
    std::string source_filename;

    explicit ImgDecoder(sys::path filename) : source_filename(u8string(filename)) {}

    // Methods
    std::string convert_str(std::u16string const& p_str) {
#ifndef NL_NO_CODECVT
        return convert.to_bytes(p_str);
#else
        std::array<char, 0x10000> buf;
        std::wstring wbuf{p_str.cbegin(), p_str.cend()};
        auto size = std::wcstombs(buf.data(), wbuf.data(), buf.size());
        return {buf.data(), size};
#endif
    }

    id_t add_string(std::string str) {
        auto result = string_map.emplace(str, static_cast<id_t>(strings.size()));
        if (result.second) strings.push_back(std::move(str));
        return result.first->second;
    }

    id_t read_enc_string() {
        auto len = in.read<int8_t>();
        if (len > 0) {
            auto slen = len == 127 ? in.read<uint32_t>() : len;
            auto ows = reinterpret_cast<char16_t const*>(in.offset);
            in.skip(slen * 2u);
            auto mask = 0xAAAAu;
            wstr_buf.resize(slen);
            for (auto i = 0u; i < std::min(slen, 0x10000u); ++i) {
                wstr_buf[i] = static_cast<char16_t>(ows[i] ^ u16key[i] ^ mask);
                ++mask;
            }
            for (auto i = 0x10000u; i < slen; ++i) {
                wstr_buf[i] = static_cast<char16_t>(ows[i] ^ mask);
                ++mask;
            }
            return add_string(convert_str(wstr_buf));
        }
        if (len < 0) {
            auto slen = len == -128 ? in.read<uint32_t>() : -len;
            auto os = reinterpret_cast<char8_t const*>(in.offset);
            in.skip(slen);
            auto mask = 0xAAu;
            str_buf.resize(slen);
            for (auto i = 0u; i < std::min(slen, 0x10000u); ++i) {
                str_buf[i] = static_cast<char8_t>(os[i] ^ u8key[i] ^ mask);
                ++mask;
            }
            for (auto i = 0x10000u; i < slen; ++i) {
                str_buf[i] = static_cast<char8_t>(os[i] ^ mask);
                ++mask;
            }
            if (std::any_of(str_buf.begin(), str_buf.end(),
                            [](char const& c) { return static_cast<uint8_t>(c) >= 0x80; })) {
                wstr_buf.clear();
                std::transform(str_buf.cbegin(), str_buf.cend(), std::back_inserter(wstr_buf),
                               [](char c) { return cp1252[static_cast<unsigned char>(c)]; });
                return add_string(convert_str(wstr_buf));
            }
            return add_string(str_buf);
        }
        return 0;
    }

    id_t read_prop_string(size_t p_offset) {
        auto a = in.read<uint8_t>();
        switch (a) {
        case 0x00:
        case 0x73:
            return read_enc_string();
        case 0x01:
        case 0x1B: {
            auto o = in.read<int32_t>() + p_offset;
            auto p = in.tell();
            in.seek(o);
            auto s = read_enc_string();
            in.seek(p);
            return s;
        }
        default:
            throw std::runtime_error("Unknown property string type: " + std::to_string(a));
        }
    }

    void deduce_key() {
        auto len = in.read<int8_t>();
        if (len >= 0) throw std::runtime_error("I give up");
        auto slen = len == -128 ? in.read<uint32_t>() : -len;
        u8key = nullptr;
        for (auto key : keys) {
            auto os = reinterpret_cast<char8_t const*>(in.offset);
            uint8_t mask = 0xAA;
            auto k = reinterpret_cast<char8_t const*>(key);
            bool valid = true;
            for (auto i = 0u; i < slen; ++i, ++mask) {
                auto c = static_cast<uint8_t>(os[i] ^ k[i] ^ mask);
                if (c < 0x20 || c >= 0x80) {
                    valid = false;
                }
            }
            if (valid) {
                u8key = reinterpret_cast<char8_t const*>(key);
                u16key = reinterpret_cast<char16_t const*>(key);
            }
        }
        if (!u8key) throw std::runtime_error("Failed to identify the locale");
        in.skip(slen);
    }

    void sort_nodes(id_t first, id_t count) {
        std::sort(nodes.begin() + first, nodes.begin() + first + count,
                  [this](node const& n1, node const& n2) { return strings[n1.name] < strings[n2.name]; });
    }

    void find_uols(id_t uol_node) {
        auto& n = nodes[uol_node];
        if (n.data_type == node::type::uol) {
            uol_path.push_back(uol_node);
            uols.push_back(uol_path);
            uol_path.pop_back();
        } else if (n.num != 0) {
            uol_path.push_back(uol_node);
            for (auto i = 0u; i < n.num; ++i) find_uols(n.children + i);
            uol_path.pop_back();
        }
    }

    //std::vector<std::string> name_path;
    void find_links(id_t link_node, std::string const& str) {
        auto& n = nodes[link_node];
        auto& s = strings[n.name];
        if (s == str) {
            link_path.push_back(link_node);
            //name_path.push_back(s);
            links.push_back(link_path);
            link_path.pop_back();
            //name_path.pop_back();
        } else if (n.num != 0) {
            link_path.push_back(link_node);
            //name_path.push_back(s);
            for (auto i = 0u; i < n.num; ++i) find_links(n.children + i, str);
            link_path.pop_back();
            //name_path.pop_back();
        }
    }

    id_t get_child(id_t parent_node, std::string const& str) {
        if (parent_node == 0) return 0;
        auto& n = nodes[parent_node];
        auto first = nodes.begin() + n.children;
        auto last = first + n.num;
        auto it = std::lower_bound(first, last, str,
                                   [this](node const& n, std::string const& s) { return strings[n.name] < s; });
        if (it == last) return 0;
        if (strings[it->name] != str) return 0;
        return static_cast<id_t>(it - nodes.begin());
    }

    id_t get_child_full(id_t parent_node, std::string const& str) {
        auto& n = nodes[parent_node];
        auto first = nodes.begin() + n.children;
        auto last = first + n.num;
        auto it = std::lower_bound(first, last, str,
                                   [this](node const& n, std::string const& s) { return strings[n.name] < s; });
        if (it == last) return 0;
        if (strings[it->name] != str) return 0;
        return static_cast<id_t>(it - nodes.begin());
    }

    bool resolve_uol(std::vector<id_t> uol, std::unordered_set<id_t> const& pending) {
        auto& n = nodes[uol.back()];
        uol.pop_back();
        if (n.data_type != node::type::uol) throw std::runtime_error("Welp. I failed.");
        auto& s = strings[n.data.string];
        auto b = 0u;
        for (auto i = 0u; i < s.size(); ++i)
            if (s[i] == '/') {
                if (i - b == 2 && s[b] == '.' && s[b + 1] == '.') {
                    if (uol.size() == 1) return false;
                    uol.pop_back();
                } else {
                    auto const child = get_child_full(uol.back(), s.substr(b, i - b));
                    if (child == 0) return false;
                    uol.push_back(child);
                }
                b = ++i;
            }
        uol.push_back(get_child_full(uol.back(), s.substr(b)));
        if (uol.back() == 0) return false;
        auto& nr = nodes[uol.back()];
        if (nr.data_type == node::type::uol || pending.find(uol.back()) != pending.end()) return false;
        n.data_type = nr.data_type;
        n.children = nr.children;
        n.num = nr.num;
        n.data.integer = nr.data.integer;
        n.source_file_id = nr.source_file_id;
        return true;
    }

    bool resolve_source(std::vector<id_t> link, std::unordered_set<id_t> const& pending) {
        auto& n = nodes[link.back()];
        link.pop_back();
        auto& s = strings[n.data.string];
        std::istringstream stream(s);
        std::vector<std::string> parts;
        std::string segment;
        while (std::getline(stream, segment, '/')) parts.push_back(segment);
        if (!parts.empty() && parts.front() == sys::path(source_filename).filename().string())
            parts.erase(parts.begin());
        id_t r = 0;
        for (auto const& part : parts) {
            r = get_child_full(r, part);
            if (r == 0) return false;
        }
        if (pending.find(r) != pending.end()) return false;
        auto& nr = nodes[r];
        if (nr.data_type != node::type::bitmap) return false;
        auto& pn = nodes[link.back()];
        pn.data = nr.data;
        pn.source_file_id = nr.source_file_id;
        return true;
    }

    bool resolve_outlink(std::vector<id_t> link, std::unordered_set<id_t> const& pending) {
        auto& n = nodes[link.back()];
        link.pop_back();
        auto& s = strings[n.data.string];
        std::istringstream stream(s);
        std::vector<std::string> parts;
        std::string segment;
        while (std::getline(stream, segment, '/')) parts.push_back(segment);
        if (!parts.empty() && parts.front() == sys::path(source_filename).filename().string())
            parts.erase(parts.begin());
        id_t r = 0;
        for (auto const& part : parts) {
            r = get_child_full(r, part);
            if (r == 0) return false;
        }
        if (pending.find(r) != pending.end()) return false;
        auto& nr = nodes[r];
        if (nr.data_type != node::type::bitmap) return false;
        auto& pn = nodes[link.back()];
        pn.data = nr.data;
        pn.source_file_id = nr.source_file_id;
        return true;
    }

    bool resolve_inlink(std::vector<id_t> link, std::unordered_set<id_t> const& pending) {
        auto& n = nodes[link.back()];
        link.pop_back();
        auto& s = strings[n.data.string];
        std::istringstream stream(s);
        std::vector<std::string> parts;
        std::string segment;
        while (std::getline(stream, segment, '/')) parts.push_back(segment);
        auto r = link.back();
        auto& pn = nodes[r];
        for (;;) {
            //auto & p = nodes[r];
            //auto & pn = strings[p.name];
            for (auto const& part : parts) {
                r = get_child_full(r, part);
                if (r == 0) break;
            }
            if (r != 0) break;
            link.pop_back();
            if (link.size() == 0) break;
            r = link.back();
        }
        if (r == 0 || pending.find(r) != pending.end()) return false;
        auto& nr = nodes[r];
        if (nr.data_type != node::type::bitmap) return false;
        pn.data = nr.data;
        pn.source_file_id = nr.source_file_id;
        return true;
    }

    void uol_fail(std::vector<id_t>& uol) {
        std::cerr << "Unresolved UOL: ";
        for (auto id : uol) std::cerr << '/' << strings[nodes[id].name];
        std::cerr << std::endl;
        //std::cerr << "Invalid UOL: ";
        //for (auto id : uol) {
        //auto & n = nodes[id];
        //std::cerr << '/' << strings[n.name];
        //}
        auto& n = nodes[uol.back()];
        if (n.data_type == node::type::uol) {
            //std::cerr << " = \"" << strings[n.data.string] << "\"" << std::endl;
            // If we failed to resolve any uols, just turn them into useless empty nodes
#ifndef NL_PRESERVE_UNRESOLVED_UOL
            n.data_type = node::type::none;
#endif
        } else {
            std::cerr << " claims to be an invalid UOL but isn't a UOL???" << std::endl;
        }
    }

    void source_fail(std::vector<id_t>& link, std::string const& str) {
        auto& n = nodes[link.back()];
        std::cerr << "Failed to find " << str << " for [" << strings[n.data.string] << "]." << std::endl;
        auto& parent = nodes[link[link.size() - 2]];
        if (parent.data_type == node::type::bitmap) {
            parent.data_type = node::type::none;
            parent.source_file_id = UINT32_MAX;
        }
    }

    void extended_property(id_t prop_node, size_t p_offset) {
        auto& n = nodes[prop_node];
        auto& st = strings[read_prop_string(p_offset)];
        if (st == "Property") {
            in.skip(2);
            sub_property(prop_node, p_offset);
        } else if (st == "Canvas") {
            in.skip(1);
            if (in.read<uint8_t>() == 1) {
                in.skip(2);
                sub_property(prop_node, p_offset);
            }
            // Have to recalculate n, because address may have changed
            // because sub_property may increase the size of nodes
            auto& nn = nodes[prop_node];
            nn.data_type = node::type::bitmap;
            nn.data.bitmap.id = static_cast<uint32_t>(bitmaps.size());
            bitmaps.push_back({in.tell(), reinterpret_cast<uint8_t const*>(u8key)});
            nn.data.bitmap.width = static_cast<uint16_t>(in.read_cint());
            nn.data.bitmap.height = static_cast<uint16_t>(in.read_cint());
        } else if (st == "Shape2D#Vector2D") {
            n.data_type = node::type::vector;
            n.data.vector[0] = in.read_cint();
            n.data.vector[1] = in.read_cint();
        } else if (st == "Shape2D#Convex2D") {
            auto count = static_cast<id_t>(in.read_cint());
            auto ni = static_cast<id_t>(nodes.size());
            n.num = static_cast<uint16_t>(count);
            n.children = ni;
            nodes.resize(nodes.size() + count);
            for (auto i = 0u; i < count; ++i) {
                auto& nn = nodes[ni + i];
                nn.source_order = static_cast<uint16_t>(i);
                auto es = std::to_string(i);
                nn.name = add_string(std::move(es));
                extended_property(ni, p_offset);
            }
            nodes_to_sort.emplace_back(ni, count);
        } else if (st == "Sound_DX8") {
            n.data_type = node::type::audio;
            n.data.audio.id = static_cast<uint32_t>(audios.size());
            audio a;
            in.skip(1); // Always 0
            a.length = static_cast<uint32_t>(in.read_cint()) + 82u;
            n.data.audio.length = a.length;
            in.read_cint();
            a.data = in.tell();
            audios.push_back(a);
        } else if (st == "UOL") {
            in.skip(1);
            n.data_type = node::type::uol;
            n.data.string = read_prop_string(p_offset);
        } else {
            throw std::runtime_error("Unknown sub property type: " + st);
        }
    }

    void sub_property(id_t prop_node, size_t p_offset) {
        auto& n = nodes[prop_node];
        auto count = static_cast<id_t>(in.read_cint());
        auto ni = static_cast<id_t>(nodes.size());
        n.num = static_cast<uint16_t>(count);
        n.children = ni;
        nodes.resize(nodes.size() + count);
        for (auto i = 0u; i < count; ++i) {
            auto& nn = nodes[ni + i];
            nn.source_order = static_cast<uint16_t>(i);
            nn.name = read_prop_string(p_offset);
            auto type = in.read<uint8_t>();
            uint8_t num;
            size_t p;
            switch (type) {
            case 0x00: // Turning null nodes into integers with an id. Useful for zmap.img
                nn.data_type = node::type::integer;
                nn.data.integer = i;
                break;
            case 0x0B: // TODO: Check if 0x0B really is a 16bit int
            case 0x02:
                nn.data_type = node::type::integer;
                nn.data.integer = in.read<uint16_t>();
                break;
            case 0x03:
                nn.data_type = node::type::integer;
                nn.data.integer = in.read_cint();
                break;
            case 0x04:
                nn.data_type = node::type::real;
                num = in.read<uint8_t>();
                if (num == 0x80) {
                    nn.data.real = in.read<float>();
                } else {
                    nn.data.real = static_cast<int8_t>(num);
                }
                break;
            case 0x05:
                nn.data_type = node::type::real;
                nn.data.real = in.read<double>();
                break;
            case 0x08:
                nn.data_type = node::type::string;
                nn.data.string = read_prop_string(p_offset);
                break;
            case 0x09:
                p = in.read<int32_t>() + in.tell();
                extended_property(ni + i, p_offset);
                in.seek(p);
                break;
            case 0x13:
                nn.data_type = node::type::integer;
                nn.data.integer = in.read_cint();
                break;
            case 0x14:
                nn.data_type = node::type::integer;
                num = in.read<uint8_t>();
                if (num == 0x80) {
                    nn.data.integer = in.read<int64_t>();
                } else {
                    nn.data.integer = static_cast<int8_t>(num);
                }
                break;
            default:
                throw std::runtime_error("Unknown sub property type: " + std::to_string(type));
            }
        }
        nodes_to_sort.emplace_back(ni, count);
    }

    void img(id_t img_node, int32_t size) {
        auto p = in.tell();
        auto n1 = in.read<uint8_t>();
        if (n1 == 1) {
            lua_script(img_node);
        } else {
            deduce_key();
            in.seek(p);
            extended_property(img_node, p);
        }
        in.seek(p + size);
    }

    void lua_script(id_t script_node) {
        auto slen = static_cast<uint32_t>(in.read_cint());
        if (slen > 0x1ffff) throw std::runtime_error("Lua script is too long");
        auto os = reinterpret_cast<char8_t const*>(in.offset);
        str_buf.resize(slen);
        auto key = key_kms;
        u8key = reinterpret_cast<char8_t const*>(key);
        for (auto i = 0u; i < slen; ++i) {
            str_buf[i] = static_cast<char8_t>(os[i] ^ u8key[i]);
        }
        in.skip(slen);
        auto string = add_string(str_buf);
        auto& n = nodes[script_node];
        n.data_type = node::type::string;
        n.data.string = string;
    }

    void finish_parse() {
        for (auto const& n : nodes_to_sort) sort_nodes(n.first, n.second);
#ifndef NL_NO_PROGRESS_OUTPUT
        auto progress = [](char const* value) { std::cout << value; };
#else
        auto progress = [](char const*) {};
#endif
        progress("Parsing references...");
        find_uols(0);
        find_links(0, "source");
        auto sources = std::move(links);
        links.clear();
        find_links(0, "_outlink");
        auto outlinks = std::move(links);
        links.clear();
        find_links(0, "_inlink");
        auto inlinks = std::move(links);
        links.clear();

        for (;;) {
            std::unordered_set<id_t> pending;
            for (auto const& uol : uols) pending.insert(uol.back());
            for (auto const* group : {&sources, &outlinks, &inlinks})
                for (auto const& link : *group) pending.insert(link[link.size() - 2]);

            auto remaining = uols.size() + sources.size() + outlinks.size() + inlinks.size();
            auto erase_resolved = [](auto& group, auto resolve) {
                group.erase(std::remove_if(group.begin(), group.end(), resolve), group.end());
            };
            erase_resolved(uols, [this, &pending](auto const& path) { return resolve_uol(path, pending); });
            erase_resolved(sources, [this, &pending](auto const& path) { return resolve_source(path, pending); });
            erase_resolved(outlinks, [this, &pending](auto const& path) { return resolve_outlink(path, pending); });
            erase_resolved(inlinks, [this, &pending](auto const& path) { return resolve_inlink(path, pending); });
            if (remaining == uols.size() + sources.size() + outlinks.size() + inlinks.size()) break;
        }
        for (auto& path : uols) uol_fail(path);
        for (auto& path : sources) source_fail(path, "source");
        for (auto& path : outlinks) source_fail(path, "_outlink");
        for (auto& path : inlinks) source_fail(path, "_inlink");
        progress("Done!\n");
    }
};
}

namespace nl {
using id_t = wz::id_t;
using ImgDecoder = wz::ImgDecoder;
}

#include "ImgResources.h"

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
class DirectoryParser final : public nl::ImgDecoder {
public:
    DirectoryParser(std::filesystem::path source, bool base_only)
        : nl::ImgDecoder(source), source(std::move(source)), base_only(base_only) {}

    void parse() {
        add_string({});
        add_directory(0, source);
        finish_parse();
    }

    std::filesystem::path source;
    bool base_only;
    std::vector<std::string> sources;

private:
    void assign_source(nl::wz::id_t parent, uint32_t source_id) {
        auto& node = nodes[parent];
        node.source_file_id = source_id;
        for (uint32_t index = 0; index < node.num; ++index) assign_source(node.children + index, source_id);
    }

    void add_directory(nl::wz::id_t parent, std::filesystem::path const& path) {
        std::vector<std::filesystem::path> entries;
        for (auto const& entry : std::filesystem::directory_iterator(path)) {
            if ((!base_only && entry.is_directory()) || (entry.is_regular_file() && entry.path().extension() == ".img"))
                entries.push_back(entry.path());
        }
        std::sort(entries.begin(), entries.end());
        auto first = static_cast<nl::wz::id_t>(nodes.size());
        nodes[parent].children = first;
        nodes[parent].num = static_cast<uint16_t>(entries.size());
        nodes.resize(first + entries.size());
        for (size_t index = 0; index < entries.size(); ++index) {
            auto child = first + static_cast<nl::wz::id_t>(index);
            auto const& entry = entries[index];
            nodes[child].name = add_string(entry.filename().string());
            nodes[child].source_order = static_cast<uint16_t>(index);
            if (std::filesystem::is_directory(entry)) {
                add_directory(child, entry);
            } else {
                const auto source_id = static_cast<uint32_t>(sources.size());
                sources.push_back(entry.string());
                in.open(entry.string());
                img(child, static_cast<int32_t>(std::filesystem::file_size(entry)));
                assign_source(child, source_id);
            }
        }
        nodes_to_sort.emplace_back(first, entries.size());
    }
};

void set_error(char* output, size_t capacity, std::string const& error) {
    if (!output || capacity == 0) return;
    const auto length = std::min(capacity - 1, error.size());
    std::memcpy(output, error.data(), length);
    output[length] = '\0';
}
}

struct BeidouImgDirectory {
    explicit BeidouImgDirectory(std::filesystem::path const& path, bool base_only) : parser(path, base_only) {
        parser.parse();
    }

    DirectoryParser parser;
};

extern "C" int beidou_img_directory_open(const char* path, int base_only, BeidouImgDirectory** result, char* error,
                                         size_t error_capacity) {
    if (!path || !result) {
        set_error(error, error_capacity, "IMG directory path and result are required");
        return 0;
    }
    try {
        *result = new BeidouImgDirectory(path, base_only != 0);
        return 1;
    } catch (std::exception const& failure) {
        *result = nullptr;
        set_error(error, error_capacity, failure.what());
        return 0;
    }
}

extern "C" void beidou_img_directory_close(BeidouImgDirectory* directory) {
    delete directory;
}

extern "C" size_t beidou_img_directory_node_count(BeidouImgDirectory const* directory) {
    return directory ? directory->parser.nodes.size() : 0;
}

extern "C" size_t beidou_img_directory_string_count(BeidouImgDirectory const* directory) {
    return directory ? directory->parser.strings.size() : 0;
}

extern "C" size_t beidou_img_directory_source_count(BeidouImgDirectory const* directory) {
    return directory ? directory->parser.sources.size() : 0;
}

extern "C" int beidou_img_directory_node(BeidouImgDirectory const* directory, size_t index, BeidouImgNodeInfo* result) {
    if (!directory || !result || index >= directory->parser.nodes.size()) return 0;
    auto const& source = directory->parser.nodes[index];
    *result = {};
    result->name_string_id = source.name;
    result->children = source.children;
    result->source_file_id = source.source_file_id;
    result->source_order = source.source_order;
    result->child_count = source.num;
    result->type = static_cast<uint16_t>(source.data_type);
    switch (source.data_type) {
    case nl::wz::node::type::integer:
        result->integer = source.data.integer;
        break;
    case nl::wz::node::type::real:
        result->real = source.data.real;
        break;
    case nl::wz::node::type::string:
    case nl::wz::node::type::uol:
        result->value_string_id = source.data.string;
        break;
    case nl::wz::node::type::vector:
        result->vector_x = source.data.vector[0];
        result->vector_y = source.data.vector[1];
        break;
    case nl::wz::node::type::bitmap:
        result->bitmap_id = source.data.bitmap.id;
        result->bitmap_width = source.data.bitmap.width;
        result->bitmap_height = source.data.bitmap.height;
        break;
    case nl::wz::node::type::audio:
        result->audio_id = source.data.audio.id;
        result->audio_length = source.data.audio.length;
        break;
    case nl::wz::node::type::none:
        break;
    }
    return 1;
}

extern "C" const char* beidou_img_directory_string(BeidouImgDirectory const* directory, size_t index, size_t* length) {
    if (!directory || !length || index >= directory->parser.strings.size()) return nullptr;
    auto const& value = directory->parser.strings[index];
    *length = value.size();
    return value.data();
}

extern "C" const char* beidou_img_directory_source(BeidouImgDirectory const* directory, size_t index, size_t* length) {
    if (!directory || !length || index >= directory->parser.sources.size()) return nullptr;
    auto const& value = directory->parser.sources[index];
    *length = value.size();
    return value.data();
}
