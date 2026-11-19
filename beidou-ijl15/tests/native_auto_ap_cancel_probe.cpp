// SPDX-License-Identifier: AGPL-3.0-or-later
#include "../ezorsia/NativeAutoApCancelProbe.h"
#include <cassert>

int main() {
    using Probe = BeiDouBridge::NativeAutoApCancelProbe;
    Probe p;
    assert(!p.Bind(0x1000, 0x992eb1));
    p.active = true;
    p.character = 5;
    p.scene = 7;
    p.context = 9;
    assert(!p.Bind(0x1000, 0x992eb2));
    assert(p.Bind(0x1000, 0x992eb1));
    assert(!p.Bind(0x2000, 0x992eb1));
    assert(!p.TakeCancel(0x1000, 0x2000, 0xb3bb24, 1001, 0x8d5251, 5, 7, 9, true));
    assert(!p.TakeCancel(0x1000, 0x1000, 0xb3bb24, 1001, 0x8d5251, 6, 7, 9, true));
    assert(!p.TakeCancel(0x1000, 0x1000, 0xb3bb24, 1001, 0x8d5251, 5, 7, 9, false));
    assert(p.TakeCancel(0x1000, 0x1000, 0xb3bb24, 1001, 0x8d5251, 5, 7, 9, true));
    assert(!p.TakeCancel(0x1000, 0x1000, 0xb3bb24, 1001, 0x8d5251, 5, 7, 9, true));
}
