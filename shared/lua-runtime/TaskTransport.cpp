// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TaskTransport.h"

#include <cerrno>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <utility>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <sys/stat.h>
#endif

namespace MapleControl {
namespace {
bool Identifier(const std::string& value) {
    return value.size() == 32 && value.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos;
}

bool Unsigned(const std::string& text, std::uint64_t& value) {
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos) return false;
    std::istringstream stream(text);
    return static_cast<bool>(stream >> value);
}

bool DecodeName(const std::string& encoded, std::string& name) {
    if (encoded.size() % 2 != 0) return false;
    const std::string digits = "0123456789abcdef";
    for (std::size_t index = 0; index < encoded.size(); index += 2) {
        const auto high = digits.find(encoded[index]);
        const auto low = digits.find(encoded[index + 1]);
        if (high == std::string::npos || low == std::string::npos) return false;
        name.push_back(static_cast<char>(high * 16 + low));
    }
    return true;
}

std::string Quote(const std::string& value) {
    std::ostringstream output;
    output << '"';
    for (unsigned char byte : value) {
        if (byte == '"' || byte == '\\') output << '\\' << byte;
        else if (byte < 32) output << "\\u00" << std::hex << std::setfill('0')
            << std::setw(2) << static_cast<unsigned int>(byte) << std::dec;
        else output << byte;
    }
    output << '"';
    return output.str();
}

bool MakeResultsDirectory(const std::string& path) {
#ifdef _WIN32
    return CreateDirectoryA(path.c_str(), nullptr) || GetLastError() == ERROR_ALREADY_EXISTS;
#else
    return mkdir(path.c_str(), 0700) == 0 || errno == EEXIST;
#endif
}

bool Replace(const std::string& source, const std::string& target) {
#ifdef _WIN32
    return MoveFileExA(source.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != FALSE;
#else
    return std::rename(source.c_str(), target.c_str()) == 0;
#endif
}
}

struct TaskTransport::Request {
    TaskChange change;
    std::string operation;
    std::uint64_t generation = 0;
};

TaskTransport::TaskTransport(std::string bridgeDirectory, std::string registeredRun)
    : directory(std::move(bridgeDirectory)), runId(std::move(registeredRun)) {}
TaskTransport::~TaskTransport() = default;

bool TaskTransport::Publish(const Request& request, const TaskChangeResult& result, const State& state) {
    const auto results = directory + "/task-results";
    if (!MakeResultsDirectory(results)) return false;
    // Malformed packets without a safe request ID still leave an inspectable
    // rejection; their untrusted ID is never used as a path.
    const auto target = results + "/" + (Identifier(request.change.requestId)
        ? request.change.requestId : "invalid-request") + ".json";
    const auto temporary = target + ".tmp";
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output) return false;
    output << "{\"protocol\":1,\"instance_id\":" << Quote(state.instanceId)
        << ",\"run_id\":" << Quote(runId) << ",\"script_id\":" << Quote(result.scriptId)
        << ",\"scene_generation\":" << state.sceneGeneration << ",\"seq\":" << state.sequence
        << ",\"observed_at_ms\":" << state.observedAtMs << ",\"request_id\":" << Quote(result.requestId)
        << ",\"operation\":" << Quote(request.operation) << ",\"name\":" << Quote(result.name)
        << ",\"expected_revision\":" << request.change.expectedRevision << ",\"revision\":" << result.revision
        << ",\"status\":" << Quote(result.status)
        << ",\"reason\":" << (result.reason.empty() ? "null" : Quote(result.reason))
        << ",\"error\":" << (result.error.empty() ? "null" : Quote(result.error))
        << ",\"changed\":" << (result.changed ? "true" : "false")
        << ",\"control_released\":" << (result.controlReleased ? "true" : "false") << "}\n";
    output.close();
    return static_cast<bool>(output) && Replace(temporary, target);
}

bool TaskTransport::Tick(Runtime& runtime, const State& state) {
    if (directory.empty()) return true;
    if (pending) {
        const auto* result = runtime.CurrentTaskChange();
        if (result != nullptr && result->requestId == pending->change.requestId && result->status != "pending") {
            if (!Publish(*pending, *result, state)) return false;
            pending.reset();
        }
    }
    const auto path = directory + "/task-request.txt";
    errno = 0;
    std::ifstream input(path, std::ios::binary);
    if (!input) return errno == ENOENT;
    std::string line;
    std::getline(input, line);
    if (input.bad()) return false;
    input.close();
    if (std::remove(path.c_str()) != 0) return false;

    Request request;
    std::string instance, registeredRun, generation, encodedName, expectedRevision, sourceId, extra;
    unsigned int protocol = 0;
    long long priority = 0;
    std::istringstream stream(line);
    const bool header = static_cast<bool>(stream >> protocol >> instance >> registeredRun
        >> request.change.scriptId >> generation >> request.change.requestId >> request.operation
        >> encodedName >> expectedRevision >> priority >> sourceId);
    TaskChangeResult rejected;
    rejected.requestId = request.change.requestId;
    rejected.scriptId = request.change.scriptId;
    rejected.status = "rejected";
    rejected.reason = "invalid_task_request";
    if (!header || line.size() > 1024 || protocol != 1 || !Identifier(request.change.requestId)
        || !Identifier(request.change.scriptId) || !Unsigned(generation, request.generation)
        || !Unsigned(expectedRevision, request.change.expectedRevision)
        || priority < (std::numeric_limits<int>::min)() || priority > (std::numeric_limits<int>::max)()
        || !DecodeName(encodedName, request.change.name) || (stream >> extra)) {
        rejected.name = request.change.name;
        return Publish(request, rejected, state);
    }
    rejected.name = request.change.name;
    const auto existingPath = directory + "/task-results/" + request.change.requestId + ".json";
    std::ifstream existing(existingPath, std::ios::binary);
    if (existing) return true; // A retained response makes repeated IDs read-only.
    if (request.operation == "add") request.change.operation = TaskOperation::Add;
    else if (request.operation == "replace") request.change.operation = TaskOperation::Replace;
    else if (request.operation == "stop") request.change.operation = TaskOperation::Stop;
    else return Publish(request, rejected, state);
    if (instance != state.instanceId || registeredRun != runId
        || (request.change.operation != TaskOperation::Stop && request.generation != state.sceneGeneration)) {
        rejected.reason = "task_identity_mismatch";
        return Publish(request, rejected, state);
    }
    if ((request.change.operation == TaskOperation::Stop && (sourceId != "-" || priority != 0))
        || (request.change.operation != TaskOperation::Stop && sourceId != request.change.requestId)
        || (request.change.operation == TaskOperation::Add && request.change.expectedRevision != 0))
        return Publish(request, rejected, state);

    request.change.priority = static_cast<int>(priority);
    if (request.change.operation != TaskOperation::Stop) {
        std::ifstream source(directory + "/scripts/" + sourceId + ".lua", std::ios::binary | std::ios::ate);
        const auto size = source ? source.tellg() : std::streampos(-1);
        if (size < 0 || size > 1024 * 1024) {
            rejected.reason = "task_source_unavailable";
            return Publish(request, rejected, state);
        }
        request.change.source.resize(static_cast<std::size_t>(size));
        source.seekg(0);
        if (!request.change.source.empty()) source.read(&request.change.source[0],
            static_cast<std::streamsize>(request.change.source.size()));
        if (!source) {
            rejected.reason = "task_source_unavailable";
            return Publish(request, rejected, state);
        }
    }
    const auto result = runtime.ManageTask(request.change);
    if (!Publish(request, result, state)) return false;
    if (result.status == "pending") pending.reset(new Request(std::move(request)));
    return true;
}

}
