"""Offline synthetic memory fixture for the cash shop reader; not client evidence."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CashShopReaderFixture(unittest.TestCase):
    def test_window_membership_and_candidate_identity(self):
        source = (ROOT / "beidou-ijl15/ezorsia/ObserveCashShop.cpp").read_text()
        source = source.replace('#include "stdafx.h"', '').replace('#include "NativeObservation.h"', '')
        harness = r'''
#include "NativeObservation.h"
#include <array>
#include <cassert>
#include <cstring>
#include <map>
using Address = std::uint32_t;
std::map<Address, unsigned char> memory;
template <class T> void put(Address a, const T &v) {
    const auto p = reinterpret_cast<const unsigned char*>(&v);
    for (unsigned i = 0; i < sizeof(T); ++i) memory[a+i] = p[i];
}
void fill(Address a, unsigned n) { for (unsigned i=0; i<n; ++i) memory[a+i]=0; }
namespace NativeObservation {
void Copy(std::uintptr_t a, void *out, std::size_t size) {
    auto p=static_cast<unsigned char*>(out);
    for (std::size_t i=0; i<size; ++i) {
        auto it=memory.find(static_cast<Address>(a+i));
        if (it==memory.end()) throw ReadError("missing memory");
        p[i]=it->second;
    }
}
std::vector<unsigned char> Bytes(std::uintptr_t a, std::size_t n) {
    std::vector<unsigned char> out(n); Copy(a,out.data(),n); return out;
}
std::uint32_t SecureInt(std::uintptr_t) { return 40000; }
std::uint32_t SecureValue(std::uintptr_t) { return 9111000; }
Value Window(std::uintptr_t) { return Value::Object(); }
}
''' + source + r'''
int main() {
    using NativeObservation::CashShop;
    put(0xBF1650,std::array<Address,3>{2,0x1100,0x1200});
    put<Address>(0x1100,0x10000); put<Address>(0x1100-12,0x1200-16);
    put<Address>(0x1200,0x20000); put<Address>(0x1200-12,0);
    put(0x10000,std::array<Address,3>{0xAF1C24,0xAF1BD8,0xAF1BD4});
    put(0x20000,std::array<Address,3>{0xAF1D68,0xAF1D1C,0xAF1D18});
    constexpr Address parent=0x10000-0x15bc;
    put<Address>(0x10000+0x240,parent); fill(parent+0x18,0x28);
    put(parent+0x52c,std::array<Address,3>{5,2,2});
    put(0x10000+0x178,std::array<std::int32_t,10>{2,-1,-1,-1,-1,-1,-1,-1,-1,-1});
    put<Address>(0xBE7918,0x30000); put<Address>(0x30000+0x36e0,0x40000);
    put<Address>(0x40000-4,3); put<Address>(0x40000+2*8+4,0x50000);
    fill(0x50000,0x24); put<Address>(0x50000+0x0c,50200093);
    put<Address>(0x50000+0x18,0x60000); put<std::int32_t>(0x50000+0x20,6400); fill(0x60000,10);
    put<Address>(0x20000+0x88,1); put<Address>(0x20000+0x90,0x70000);
    put<Address>(0x70000-4,1); put<Address>(0x70000+4,0x50000);
    const auto output=CashShop().Dump();
    assert(output.find("50200093") != std::string::npos);
    assert(output.find("9111000") != std::string::npos);
    assert(output.find("\"modal_count\":1") != std::string::npos);
    put<Address>(0x70000-4,2);
    bool failed=false; try { CashShop(); } catch (const NativeObservation::ReadError&) { failed=true; }
    assert(failed);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'fixture.cpp'
            exe = Path(tmp) / 'fixture'
            src.write_text(harness)
            subprocess.run(['g++', '-std=c++17', '-I', str(ROOT / 'beidou-ijl15/ezorsia'),
                            '-I', str(ROOT / 'shared/lua-runtime'), str(src),
                            str(ROOT / 'shared/lua-runtime/Observation.cpp'), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
