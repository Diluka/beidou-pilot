// SPDX-License-Identifier: AGPL-3.0-or-later
// Exercise the production file-lane functions with an in-memory Win32 boundary.
#include <algorithm>
#include <cassert>
#include <cstring>
#include <map>
#include <string>
using DWORD = unsigned long;
using HANDLE = int;
constexpr HANDLE INVALID_HANDLE_VALUE = -1;
constexpr int GENERIC_READ=1, GENERIC_WRITE=2, DELETE=4, FILE_SHARE_READ=8;
constexpr int OPEN_EXISTING=1, CREATE_ALWAYS=2, FILE_FLAG_DELETE_ON_CLOSE=16;
constexpr int FILE_ATTRIBUTE_NORMAL=0, MOVEFILE_WRITE_THROUGH=0, FALSE=0;
std::map<std::string, std::string> files;
std::string opened;
bool deleteOnClose = false, failWrite = false;
bool MoveFileExA(const char* from, const char* to, int) {
    auto it = files.find(from);
    if (it == files.end() || files.count(to)) return false;
    files[to] = it->second; files.erase(it); return true;
}
HANDLE CreateFileA(const char* path, int, int, void*, int mode, int flags, void*) {
    if (mode == OPEN_EXISTING && !files.count(path)) return INVALID_HANDLE_VALUE;
    if (mode == CREATE_ALWAYS) files[path] = "";
    opened = path; deleteOnClose = (flags & FILE_FLAG_DELETE_ON_CLOSE) != 0; return 1;
}
bool ReadFile(HANDLE, void* out, DWORD cap, DWORD* length, void*) {
    const auto& text = files.at(opened); *length = std::min<DWORD>(cap, text.size());
    std::memcpy(out, text.data(), *length); return true;
}
bool WriteFile(HANDLE, const void* data, DWORD size, DWORD* written, void*) {
    if (failWrite) return false;
    files[opened].assign(static_cast<const char*>(data), size); *written = size; return true;
}
bool CloseHandle(HANDLE) { if (deleteOnClose) files.erase(opened); return true; }
#include "../ezorsia/NativeSkillUp.h"
int main() {
    using namespace BeiDouBridge::NativeSkillUp;
    const std::string oldId(32, 'a'), first(32, 'b'), second(32, 'c');
    Request original; original.requestId=oldId; original.character=123; original.skill=1000;
    PendingFence fence; fence.Arm(original, 100, 2, 4);
    std::uint64_t now = 1;
    auto callback = [&](const Request& r, const std::string& id, const char*& reason) {
        reason = "skill_up_confirmation_pending";
        if (!ReconcileRecorded(fence, r, id, 8, now, 100)
            && !ReconcileObserved(fence, r, id, 8, now, 100, 3, 3)) return false;
        reason="skill_up_observed_delta"; return true;
    };
    auto request = [&](const std::string& id) {
        return "1 instance run " + id + " 8 123 1000 1 123456789 " + oldId;
    };
    const std::string expired(32, 'd'), wrong(32, 'e');
    now = 123456789;
    files["dir\\skill-up-reconcile.txt"] = request(expired);
    TickReconcile("dir", "instance", "run", callback);
    assert(fence.pending && files.at("dir\\skill-up-reconcile-result-" + expired + ".json").find("unresolved") != std::string::npos);
    now = 1;
    files["dir\\skill-up-reconcile.txt"] = "1 instance run " + wrong + " 8 124 1000 1 123456789 " + oldId;
    TickReconcile("dir", "instance", "run", callback);
    assert(fence.pending && files.at("dir\\skill-up-reconcile-result-" + wrong + ".json").find("unresolved") != std::string::npos);
    files["dir\\skill-up-reconcile.txt"] = request(first);
    failWrite = true;
    TickReconcile("dir", "instance", "run", callback);
    assert(!fence.pending && !files.count("dir\\skill-up-reconcile-result-" + first + ".json"));
    failWrite = false;
    files["dir\\skill-up-reconcile.txt"] = request(second);
    TickReconcile("dir", "instance", "run", callback);
    const auto result = files.at("dir\\skill-up-reconcile-result-" + second + ".json");
    assert(result.find("\"status\":\"confirmed\"") != std::string::npos);
    assert(!files.count("dir\\skill-up-reconcile-claimed.txt"));
    const std::string automaticId(32, 'f'), queryId(32, '1');
    original.requestId = automaticId;
    fence.Arm(original, 100, 2, 4);
    assert(fence.Confirm(123, 100, 3, 3)); // The automatic batch path.
    files["dir\\skill-up-reconcile.txt"] = "1 instance run " + queryId + " 8 123 1000 1 123456789 " + automaticId;
    TickReconcile("dir", "instance", "run", callback);
    assert(files.at("dir\\skill-up-reconcile-result-" + queryId + ".json").find("confirmed") != std::string::npos);
}
