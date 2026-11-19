"""Exercise GUI native delta projection at the map-reader boundary."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class SkillLevelDeltas(unittest.TestCase):
    def test_actual_map_reader_stability_boundary(self):
        source = (ROOT / 'beidou-ijl15/ezorsia/ObserveCharacter.cpp').read_text()
        at = 'template<class T> T At(' + source.split('template<class T> T At(', 1)[1].split('\nAddress U32', 1)[0]
        reader = 'struct MapNode {' + source.split('struct MapNode {', 1)[1].split('\nValue StringArray', 1)[0]
        harness = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <set>
#include <stdexcept>
#include <vector>
using Address = std::uint32_t;
struct ReadError : std::runtime_error { using std::runtime_error::runtime_error; };
std::map<Address, unsigned char> memory;
unsigned headerReads = 0; int mutation = 0;
template<class T> void Put(Address a, T value) { auto p = reinterpret_cast<unsigned char*>(&value); for (unsigned i=0;i<sizeof(T);++i) memory[a+i]=p[i]; }
std::vector<unsigned char> Bytes(Address a, std::size_t n) {
    if (a == 0x1000 && ++headerReads == 2) {
        if (mutation == 1) Put<Address>(0x100c, 0);
        if (mutation == 2) Put<Address>(0x300c, 9);
    }
    std::vector<unsigned char> result;
    for (std::size_t i=0;i<n;++i) {
        auto it=memory.find(a+i); if (it==memory.end()) throw ReadError("unavailable"); result.push_back(it->second);
    }
    return result;
}
''' + at + '\n' + reader + r'''
int main() {
    for (Address i=0;i<24;++i) memory[0x1000+i]=0;
    for (Address i=0;i<16;++i) memory[0x3000+i]=0;
    Put<Address>(0x1000,0xaf2074); Put<Address>(0x1004,0x2000);
    Put<Address>(0x1008,1); Put<Address>(0x100c,1); Put<Address>(0x2000,0x3000);
    Put<Address>(0x3000,0xaf3314); Put<Address>(0x3008,42); Put<Address>(0x300c,7);
    auto nodes=MapRecords(0x1000,0xaf2074,0xaf3314,16);
    assert(nodes.size()==1 && At<Address>(nodes[0].bytes,12)==7);
    headerReads=0; mutation=2;
    nodes=MapRecords(0x1000,0xaf2074,0xaf3314,16);
    assert(At<Address>(nodes[0].bytes,12)==7 && At<Address>(Bytes(0x3000,16),12)==9);
    headerReads=0; mutation=1; bool rejected=false;
    try { MapRecords(0x1000,0xaf2074,0xaf3314,16); } catch (const ReadError&) { rejected=true; }
    assert(rejected);
    Put<Address>(0x100c,1); headerReads=0; mutation=0; memory.erase(0x3008); rejected=false;
    try { MapRecords(0x1000,0xaf2074,0xaf3314,16); } catch (const ReadError&) { rejected=true; }
    assert(rejected);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'test.cpp'
            exe = pathlib.Path(tmp) / 'test'
            path.write_text(harness)
            subprocess.run(['g++', '-std=c++17', str(path), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_native_projection_and_tick_filter(self):
        character = (ROOT / 'beidou-ijl15/ezorsia/ObserveCharacter.cpp').read_text()
        block = character.split('    try {\n        const auto records = MapRecords(character + 0x47F', 1)[1].split('    try {\n        const std::array<unsigned char, 64> readerCode', 1)[0]
        block = '    try {\n        const auto records = MapRecords(character + 0x47F' + block
        bridge = (ROOT / 'beidou-ijl15/ezorsia/AgentBridge.cpp').read_text()
        helper = 'MapleControl::Value TickCharacterView(' + bridge.split('MapleControl::Value TickCharacterView(', 1)[1].split('\nclass BeiDouTickAdapter', 1)[0]
        self.assertIn('observation.data = TickCharacterView(observation.data);', bridge)
        harness = r'''
#include "Observation.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <stdexcept>
#include <vector>
using MapleControl::Value;
using Address = std::uint32_t;
struct ReadError : std::runtime_error { using std::runtime_error::runtime_error; };
struct MapNode { std::vector<unsigned char> bytes; };
std::vector<MapNode> nodes;
bool failed = false, changed = false;
std::vector<MapNode> MapRecords(Address address, Address table, Address node, int size) {
    assert(address == 0x147f && table == 0xaf2074 && node == 0xaf3314 && size == 16);
    if (failed) throw ReadError("bad map"); return nodes;
}
Address CurrentCharacter() { return changed ? 2 : 0x1000; }
template<class T> T At(const std::vector<unsigned char>& bytes, size_t offset) {
    T value{}; std::memcpy(&value, bytes.data()+offset, sizeof(value)); return value;
}
MapNode record(Address id, std::int32_t delta) {
    MapNode result{std::vector<unsigned char>(16)};
    std::memcpy(result.bytes.data()+8, &id, 4); std::memcpy(result.bytes.data()+12, &delta, 4); return result;
}
Value sample() {
    Address character = 0x1000;
    auto result = Value::Object({{"skill_level_deltas", Value()}, {"skill_level_deltas_complete", false}});
''' + block + r'''
    return result;
}
''' + helper + r'''
int main() {
    assert(sample().Dump() == "{\"skill_level_deltas\":{},\"skill_level_deltas_complete\":true}");
    nodes = {record(42,-3), record(43,5)};
    auto original = sample();
    assert(original.Dump() == "{\"skill_level_deltas\":{\"42\":-3,\"43\":5},\"skill_level_deltas_complete\":true}");
    original["skill_point_books"] = Value::Object({{"2",9}});
    original["skill_point_books_complete"] = true;
    original["character_id"] = 77;
    assert(TickCharacterView(original).Dump() == "{\"character_id\":77}");
    nodes.push_back(record(42,1));
    assert(sample().Dump() == "{\"skill_level_deltas\":null,\"skill_level_deltas_complete\":false}");
    nodes.clear(); failed = true;
    assert(sample().Dump() == "{\"skill_level_deltas\":null,\"skill_level_deltas_complete\":false}");
    failed = false; changed = true;
    assert(sample().Dump() == "{\"skill_level_deltas\":null,\"skill_level_deltas_complete\":false}");
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / 'test.cpp'
            exe = pathlib.Path(tmp) / 'test'
            source.write_text(harness)
            runtime = ROOT / 'shared/lua-runtime'
            subprocess.run(['g++', '-std=c++17', '-I', str(runtime), str(source), str(runtime / 'Observation.cpp'), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
