#include "HeadlessState.h"

namespace ms
{
	HeadlessState& headless_state()
	{
		static HeadlessState state;
		return state;
	}
}
