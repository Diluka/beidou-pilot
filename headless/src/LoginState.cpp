#include "LoginState.h"

namespace ms
{
	LoginState& login_state()
	{
		static LoginState state;
		return state;
	}

	void configure_login(int32_t cid, uint8_t world, uint8_t channel)
	{
		auto& state = login_state();
		state = {};
		state.desired_cid = cid;
		state.world = world;
		state.channel = channel;
		state.phase = "login_requested";
	}
}
