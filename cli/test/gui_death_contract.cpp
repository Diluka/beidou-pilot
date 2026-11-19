#include "NativeDeath.h"
#include <cassert>

int main() {
    MapleControl::State state;
    using MapleControl::Fact;
    state.character.values[6] = 0;
    assert(BeiDouBridge::DeathFromState(state) == Fact::Unknown);
    state.character.values[6] = 1;
    assert(BeiDouBridge::DeathFromState(state) == Fact::Unknown);
    state.ready = true;
    assert(BeiDouBridge::DeathFromState(state) == Fact::False);
    state.character.values[6] = 0;
    assert(BeiDouBridge::DeathFromState(state) == Fact::True);
    state.character.values[6] = 50;
    assert(BeiDouBridge::DeathFromState(state) == Fact::False);
    state.ready = false;
    assert(BeiDouBridge::DeathFromState(state) == Fact::Unknown);
}
