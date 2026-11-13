// SPDX-License-Identifier: AGPL-3.0-or-later
#include "LoginState.h"
#include <cassert>

int main()
{
    auto& state = ms::login_state();
    state.tos_sent = true;
    state.gender_sent = true;
    state.accept_tos = true;
    state.account_female = false;
    state.characters_known = true;
    state.run_id = "old-run";
    ms::configure_login(42, 1, 2);
    assert(state.desired_cid == 42 && state.world == 1 && state.channel == 2);
    assert(state.phase == "login_requested" && state.run_id.empty());
    assert(!state.tos_sent && !state.gender_sent && !state.accept_tos);
    assert(!state.account_female && !state.characters_known);
    ms::configure_login(0, 0, 0);
    assert(state.desired_cid == 0 && state.phase == "login_requested");
}
