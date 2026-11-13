// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <string>

namespace BeiDouBridge {
namespace LoginAction {

// Execute at most one queued original-client login/creation action on the game
// thread. The request file is consumed immediately; an invalid identity, page,
// or state is reported as rejected without calling any client routine.
void Tick(const std::string& directory, const std::string& instance, const std::string& run);

}
}
