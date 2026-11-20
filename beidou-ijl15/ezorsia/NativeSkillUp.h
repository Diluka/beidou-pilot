// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include "NativeSkillUpProtocol.h"
#include <array>
#include <string>

namespace BeiDouBridge { namespace NativeSkillUp {
// Invoked by the update hook on the game thread. The callback validates all
// live facts and consumes the request at most once before calling the client.
template<class Dispatch>
inline void Tick(const std::string& directory, const std::string& instance, const std::string& run, Dispatch dispatch) {
    const std::string path = directory + "\\skill-up.txt";
    // Rename without replacement claims exactly one published file. A stale
    // claim after a crash blocks the lane rather than risking a replay.
    const std::string claimed = directory + "\\skill-up-claimed.txt";
    if (!MoveFileExA(path.c_str(), claimed.c_str(), MOVEFILE_WRITE_THROUGH)) return;
    HANDLE file = CreateFileA(claimed.c_str(), GENERIC_READ | DELETE, FILE_SHARE_READ,
                              nullptr, OPEN_EXISTING, FILE_FLAG_DELETE_ON_CLOSE, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    std::array<char, 4097> bytes{};
    DWORD size = 0;
    const bool complete = ReadFile(file, bytes.data(), 4096, &size, nullptr) && size < 4096;
    const bool closed = CloseHandle(file) != FALSE;
    if (!closed || !complete) return;
    Request request;
    if (!Parse(std::string(bytes.data(), size), request) || request.instance != instance || request.run != run) return;
    static RequestGuard guard;
    const char* reason = "skill_up_duplicate_or_full";
    bool dispatched = false;
    if (guard.Consume(request.requestId)) dispatched = dispatch(request, reason);
    const std::string result = "{\"protocol\":1,\"request_id\":\"" + request.requestId
        + "\",\"status\":\"" + (dispatched ? "invoked" : "rejected")
        + "\",\"reason\":\"" + reason + "\"}\n";
    const std::string temporary = directory + "\\skill-up-result-" + request.requestId + ".tmp";
    const std::string target = directory + "\\skill-up-result-" + request.requestId + ".json";
    file = CreateFileA(temporary.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    const bool ok = WriteFile(file, result.data(), static_cast<DWORD>(result.size()), &written, nullptr)
        && written == result.size();
    const bool resultClosed = CloseHandle(file) != FALSE;
    // A duplicate ID must never overwrite the first outcome.
    if (ok && resultClosed) MoveFileExA(temporary.c_str(), target.c_str(), MOVEFILE_WRITE_THROUGH);
}
// Reconciliation is a separate lane and can only observe/clear a pending fence.
template<class Reconcile>
inline void TickReconcile(const std::string& directory, const std::string& instance, const std::string& run,
                          Reconcile reconcile) {
    const std::string path = directory + "\\skill-up-reconcile.txt";
    const std::string claimed = directory + "\\skill-up-reconcile-claimed.txt";
    if (!MoveFileExA(path.c_str(), claimed.c_str(), MOVEFILE_WRITE_THROUGH)) return;
    HANDLE file = CreateFileA(claimed.c_str(), GENERIC_READ | DELETE, FILE_SHARE_READ, nullptr,
                              OPEN_EXISTING, FILE_FLAG_DELETE_ON_CLOSE, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    std::array<char, 4097> bytes{};
    DWORD size = 0;
    const bool complete = ReadFile(file, bytes.data(), 4096, &size, nullptr) && size < 4096;
    const bool closed = CloseHandle(file) != FALSE;
    if (!complete || !closed) return;
    Request request;
    std::string originalId;
    if (!ParseReconcile(std::string(bytes.data(), size), request, originalId)
        || request.instance != instance || request.run != run) return;
    static RequestGuard guard;
    const char* reason = "skill_up_duplicate_or_full";
    bool confirmed = false;
    if (guard.Consume(request.requestId)) confirmed = reconcile(request, originalId, reason);
    const std::string result = "{\"protocol\":1,\"request_id\":\"" + request.requestId
        + "\",\"status\":\"" + (confirmed ? "confirmed" : "unresolved")
        + "\",\"reason\":\"" + reason + "\"}\n";
    const auto prefix = directory + "\\skill-up-reconcile-result-" + request.requestId;
    file = CreateFileA((prefix + ".tmp").c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    const bool ok = WriteFile(file, result.data(), static_cast<DWORD>(result.size()), &written, nullptr)
        && written == result.size();
    const bool resultClosed = CloseHandle(file) != FALSE;
    if (ok && resultClosed) MoveFileExA((prefix + ".tmp").c_str(), (prefix + ".json").c_str(), MOVEFILE_WRITE_THROUGH);
}
} }
