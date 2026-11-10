// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Runtime.h"

#include <memory>
#include <string>

namespace MapleControl {

// A management lane for the current Runtime; it never replaces the host's
// whole-session command or its native action owner.
class TaskTransport {
public:
    TaskTransport(std::string directory, std::string runId);
    ~TaskTransport();
    bool Tick(Runtime& runtime, const State& state);

private:
    struct Request;
    bool Publish(const Request& request, const TaskChangeResult& result, const State& state);

    std::string directory;
    std::string runId;
    std::unique_ptr<Request> pending;
};

}
