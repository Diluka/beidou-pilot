// SPDX-License-Identifier: AGPL-3.0-or-later
// Original ladder query 0xA45B03 and ladder object fields (+0x08 flag, +0x0C x,
// +0x10 top, +0x14 bottom) against a minimal map image.
#include "ImgResourceFile.h"
#include "Gameplay/MapleMap/MapInfo.h"

#include <cstdlib>
#include <iostream>
#include <string>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

void Near(int actual, int expected, const std::string& message) {
    if (actual != expected) {
        std::cerr << message << ": actual=" << actual << " expected=" << expected << '\n';
        std::exit(1);
    }
}

ms::MapInfo Load(const char* mapDirectory) {
    auto map = load_img_directory(mapDirectory);
    nl::node root = map.root()["Test.img"];
    return ms::MapInfo(root, ms::Range<int16_t>(-9999, 9999), ms::Range<int16_t>(-9999, 9999));
}
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: v17_ladder_query_contract <scenario> <map-directory>\n";
        return 2;
    }
    const ms::MapInfo mapinfo = Load(argv[2]);
    const std::string scenario = argv[1];

    // Entries 1..3: x=95/top=50/bottom=150/uf=1/l=1, x=90/top=200/bottom=250/uf=0/l=0,
    // x=200/top=50/bottom=150/uf=1/l=1.
    if (scenario == "hit") {
        const auto hit = mapinfo.findladder(ms::Point<int16_t>(100, 0), ms::Point<int16_t>(100, 100));
        Check(static_cast<bool>(hit), "expected_a_hit");
        Near(hit->get_x(), 95, "first_hit_by_map_order");
        Near(hit->get_top(), 50, "top_field");
        Near(hit->get_bottom(), 150, "bottom_field");
        Check(hit->is_ladder(), "ladder_flag");
        Check(hit->exits_at_top(), "exits_at_top_flag");
    } else if (scenario == "x_expansion") {
        const auto boundary = mapinfo.findladder(ms::Point<int16_t>(80, 210), ms::Point<int16_t>(80, 210));
        Check(static_cast<bool>(boundary) && boundary->get_x() == 90, "ten_pixels_boundary_hits_second_entry");
        const auto inside = mapinfo.findladder(ms::Point<int16_t>(81, 210), ms::Point<int16_t>(81, 210));
        Check(static_cast<bool>(inside) && inside->get_x() == 90, "nine_pixels_inside_expansion_hits");
        const auto miss = mapinfo.findladder(ms::Point<int16_t>(79, 210), ms::Point<int16_t>(79, 210));
        Check(!miss, "eleven_pixels_outside_expansion_misses");
    } else if (scenario == "y_overlap") {
        const auto no_overlap = mapinfo.findladder(ms::Point<int16_t>(100, 160), ms::Point<int16_t>(100, 190));
        Check(!no_overlap, "no_y_overlap_misses_entry");
        const auto overlap = mapinfo.findladder(ms::Point<int16_t>(100, 140), ms::Point<int16_t>(100, 460));
        Check(static_cast<bool>(overlap) && overlap->get_x() == 95, "y_interval_overlap_hits");
    } else if (scenario == "flags") {
        const auto uf_zero = mapinfo.findladder(ms::Point<int16_t>(90, 200), ms::Point<int16_t>(90, 250));
        Check(static_cast<bool>(uf_zero) && uf_zero->get_x() == 90, "second_entry_reachable");
        Check(!uf_zero->is_ladder(), "rope_flag");
        Check(!uf_zero->exits_at_top(), "uf_zero_top_clamp_flag");
    } else {
        std::cerr << "unknown scenario: " << scenario << '\n';
        return 2;
    }
    return 0;
}
