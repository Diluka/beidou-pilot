"""Exercise the native skill resource reader against a controlled memory boundary."""
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.engines.ui import read_ui

ROOT = pathlib.Path(__file__).resolve().parents[2]


class SkillResourceCounts(unittest.TestCase):
    def test_old_bridge_without_resource_counts(self):
        skills = {'ids': [1001003], 'first_index': 0, 'selected_tab': 0, 'tab_count': 4}
        report = {'windows': [{'skills': skills}], 'dialog': {}, 'observed_at': 'now',
                  'source': 'native', 'readonly': True}
        with patch('beidou_pilot.engines.ui.observe_domain', return_value=report), \
             patch('beidou_pilot.engines.ui.project_geometry', side_effect=lambda value: value):
            result = read_ui()
        self.assertEqual(result['windows'][0]['skills'], skills)
        self.assertNotIn('resource_counts', result['windows'][0]['skills'])

    def test_tick_adapter_hides_only_resource_counts(self):
        bridge = (ROOT / 'beidou-ijl15/ezorsia/AgentBridge.cpp').read_text()
        helper = 'MapleControl::Value TickUiView(' + bridge.split('MapleControl::Value TickUiView(', 1)[1].split('\nclass BeiDouTickAdapter', 1)[0]
        self.assertIn('if (domain == "ui") observation.data = TickUiView(observation.data);', bridge)
        harness = r'''
#include "Observation.h"
#include <cassert>
''' + helper + r'''
int main() {
    using MapleControl::Value;
    auto original = Value::Object({{"windows", Value::Array({
        Value::Object({{"skills", Value::Object({{"ids", Value::Array({42})},
            {"resource_counts", Value::Array({20})}})}, {"name", "skill"}}),
        Value::Object({{"skills", Value()}})})}, {"source", "native"}});
    auto output = TickUiView(original);
    assert(original.Dump().find("resource_counts") != std::string::npos);
    assert(output.Dump() == "{\"windows\":[{\"skills\":{\"ids\":[42]},\"name\":\"skill\"},{\"skills\":null}],\"source\":\"native\"}");
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / 'test.cpp'
            exe = pathlib.Path(tmp) / 'test'
            src.write_text(harness)
            runtime = ROOT / 'shared/lua-runtime'
            subprocess.run(['g++', '-std=c++17', '-I', str(runtime), str(src), str(runtime / 'Observation.cpp'), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_native_reader(self):
        source = (ROOT / 'beidou-ijl15/ezorsia/ObserveUi.cpp').read_text()
        block = source.split('        auto ids = Value::Array();', 1)[1].split('        skills = Value::Object', 1)[0]
        harness = r'''
#include <array>
#include <cstdint>
#include <cstring>
#include <map>
#include <vector>
#include <cassert>
#include <stdexcept>
using Address = std::uint32_t;
struct ReadError : std::runtime_error { using std::runtime_error::runtime_error; };
std::map<Address, unsigned char> memory;
Address mutationAddress = 0; unsigned mutationRead = 0, reads = 0;
Address mutationValue = 0;
template<class T> T Read(Address address) {
    if (address == mutationAddress && ++reads == mutationRead) {
        auto p = reinterpret_cast<const unsigned char*>(&mutationValue);
        for (unsigned i=0; i<sizeof(mutationValue); ++i) memory[address+i] = p[i];
    }
    T value{}; auto p = reinterpret_cast<unsigned char*>(&value);
    for (unsigned i=0; i<sizeof(T); ++i) {
        auto it = memory.find(address+i);
        if (it == memory.end()) throw ReadError("unavailable");
        p[i] = it->second;
    }
    return value;
}
template<class T> void Put(Address address, const T& value) {
    auto p = reinterpret_cast<const unsigned char*>(&value);
    for (unsigned i=0; i<sizeof(T); ++i) memory[address+i] = p[i];
}
struct Value {
    int n = -1; std::vector<Value> values;
    Value() = default; Value(unsigned v): n(v) {}
    static Value Array() { return {}; }
    void Add(Value v) { values.push_back(v); }
};
std::vector<Value> observe(Address array=0x2000, Address length=1) {
    Address address=0x1000;
    auto ids = Value::Array();
''' + block + r'''
    return resourceCounts.values;
}
int main() {
    std::array<Address,16> table = {{0x50C034FA,0x50C034E9,0x50C0391D,0x50C0D90A,0x50C0D939,0x50C0CF8F,0x50C0CF52,0x50C0CD03,0x50C0CCE6,0x50C0CD7A,0x50C0D323,0x50C11666,0x50C034C3,0x50C0349D,0x50C102FA,0x50C102FA}};
    std::array<unsigned char,29> code = {{0x8b,0x44,0x24,0x08,0x85,0xc0,0x75,0x07,0xb8,0x03,0x40,0x00,0x80,0xeb,0x0b,0x8b,0x4c,0x24,0x04,0x8b,0x49,0x30,0x89,0x08,0x33,0xc0,0xc2,0x08,0x00}};
    Put(0x50C131C4,table); Put(0x50C0CCE6,code);
    Put<Address>(0x15f4,0x2000); Put<Address>(0x1ffc,1); Put<Address>(0x2004,0x3000);
    Put<Address>(0x3000,1001003); Put<Address>(0x305c,0x4000); Put<Address>(0x4000,0x50C131C4); Put<unsigned>(0x4030,20);
    assert(observe()[0].n == 20);
    Put<unsigned>(0x4030,0); assert(observe()[0].n == -1);
    Put<unsigned>(0x4030,256); assert(observe()[0].n == -1);
    Put<unsigned>(0x4030,255); assert(observe()[0].n == 255);
    Put<Address>(0x4000,1); assert(observe()[0].n == -1);
    Put<Address>(0x4000,0x50C131C4); code[0] ^= 1; Put(0x50C0CCE6,code); assert(observe()[0].n == -1);
    code[0] ^= 1; Put(0x50C0CCE6,code); table[0] ^= 1; Put(0x50C131C4,table); assert(observe()[0].n == -1);
    table[0] ^= 1; Put(0x50C131C4,table); memory.erase(0x4030); assert(observe()[0].n == -1);
    Put<Address>(0x305c,0); assert(observe()[0].n == -1);
    Put<Address>(0x305c,0x4000); Put<unsigned>(0x4030,20);
    Put<Address>(0x1ffc,2); Put<Address>(0x200c,0x5000); Put<Address>(0x5000,1001004);
    Put<Address>(0x505c,0x6000); Put<Address>(0x6000,0x50C131C4); Put<unsigned>(0x6030,30);
    auto pair = observe(0x2000,2); assert(pair.size()==2 && pair[0].n==20 && pair[1].n==30);
    mutationAddress=0x2004; mutationRead=2; reads=0; mutationValue=0x5000;
    pair=observe(0x2000,2); assert(pair[0].n==-1 && pair[1].n==30);
    mutationAddress=0; Put<Address>(0x2004,0x3000);
    Put<Address>(0x15f4,0x7000); pair=observe(0x2000,2);
    assert(pair.size()==2 && pair[0].n==-1 && pair[1].n==-1);
    Put<Address>(0x15f4,0); assert(observe(0,0).empty());
    Put<Address>(0x15f4,0x2000); Put<Address>(0x4000,0x50D131C4);
    pair=observe(0x2000,2); assert(pair[0].n==-1 && pair[1].n==30);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / 'test.cpp'
            exe = pathlib.Path(tmp) / 'test'
            src.write_text(harness)
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
