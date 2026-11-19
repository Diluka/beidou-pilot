// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Contract.h"
#include "NativeTickInput.h"
#include <cassert>

int main() {
    BeiDouBridge::NativeTickInput input;
    MapleControl::Action first;
    first.kind = MapleControl::ActionKind::AutoAp;
    first.sessionId = "first";
    assert(input.SetIntent(first, 7));
    const auto revision = input.IntentRevision();
    assert(input.DispatchPending());
    auto other = first;
    other.sessionId = "second";
    assert(!input.SetIntent(other, 7));
    assert(input.Intent().sessionId == "first");
    assert(input.IntentRevision() == revision);
    assert(input.DispatchPending());
    assert(!input.SetIntent(first, 7));
    assert(input.Intent().sessionId == "first");
    assert(input.IntentRevision() == revision);
    input.TakeDispatch(1);
    assert(input.Dispatched());
    assert(!input.SetIntent(other, 7));
    assert(input.Intent().sessionId == "first");
    assert(input.IntentRevision() == revision);
    assert(input.Dispatched());
    assert(!input.DispatchPending());
}
