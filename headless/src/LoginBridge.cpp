#include "LoginBridge.h"
#include "LoginState.h"
#include "Net/Packets/CharCreationPackets.h"
#include "Net/Encoding.h"
#include <nlohmann/json.hpp>
#include <chrono>
#include <fstream>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>

using Json = nlohmann::json;
namespace {
struct Lock {
    int fd;
    explicit Lock(const std::filesystem::path& p) : fd(open(p.c_str(), O_CREAT | O_RDWR, 0600)) {
        if (fd < 0 || flock(fd, LOCK_EX) != 0) throw std::runtime_error("login lock failed");
    }
    ~Lock() { flock(fd, LOCK_UN); close(fd); }
};
void write_json(const std::filesystem::path& path, const Json& value) {
    auto tmp = path; tmp += ".tmp";
    { std::ofstream out(tmp); if (!out || !(out << value.dump() << '\n')) throw std::runtime_error("login bridge write failed"); }
    std::filesystem::rename(tmp, path);
}
}
LoginBridge::LoginBridge(std::filesystem::path dir, std::string id, std::string runId)
    : directory(std::move(dir)), instance(std::move(id)), run(std::move(runId)) {
    std::filesystem::create_directories(directory / "login-results");
}
void LoginBridge::Publish() {
    auto& state = ms::login_state();
    Json chars = nullptr;
    if (state.characters_known) {
        chars = Json::array();
        for (const auto& c : state.characters) chars.push_back({{"id", c.id}, {"name", c.stats.name}});
    }
    auto now = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    write_json(directory / "login-state.json", {{"protocol",1},{"instance_id",instance},{"run_id",run},
        {"seq",++sequence},{"observed_at_ms",now},{"phase",state.phase},{"error",state.error.empty() ? Json(nullptr) : Json(state.error)},{"characters",chars},
        {"pending_request_id",state.pending_request_id.empty() ? Json(nullptr) : Json(state.pending_request_id)}});
}
void LoginBridge::Result(const std::string& id, const std::string& status, const std::string& error, int32_t cid) {
    write_json(directory / "login-results" / (id + ".json"), {{"protocol",1},{"instance_id",instance},{"run_id",run},
        {"request_id",id},{"operation","create_character"},{"status",status},
        {"error",error.empty() ? Json(nullptr) : Json(error)}, {"character_id",cid > 0 ? Json(cid) : Json(nullptr)}});
}
void LoginBridge::Tick() {
    Lock lock(directory / "login.lock");
    auto& state = ms::login_state();
    if (!state.pending_request_id.empty() && state.creation_status == "accepted" && std::chrono::steady_clock::now() >= deadline) {
        state.creation_status = "unknown";
        state.creation_error = "response_timeout";
        state.phase = "failed";
    }
    if (!state.pending_request_id.empty() && state.creation_status != "accepted") {
        Result(state.pending_request_id, state.creation_status, state.creation_error, state.created_cid);
        state.pending_request_id.clear(); state.creation.reset(); state.creation_status.clear();
    }
    Publish();
    const auto path = directory / "login-command.json";
    if (!std::filesystem::exists(path)) return;
    std::ifstream input(path);
    Json command = Json::parse(input, nullptr, false);
    const bool identity = command.is_object() && command.contains("protocol") && command["protocol"].is_number_integer() && command["protocol"] == 1 &&
        command.contains("instance_id") && command["instance_id"].is_string() && command["instance_id"] == instance &&
        command.contains("run_id") && command["run_id"].is_string() && command["run_id"] == run &&
        command.contains("request_id") && command["request_id"].is_string();
    const auto id = command.is_object() && command.contains("request_id") && command["request_id"].is_string()
        ? command["request_id"].get<std::string>() : std::string{};
    const bool valid_id = id.size() == 32 && id.find_first_not_of("0123456789abcdef") == std::string::npos;
    if (!identity || !valid_id) {
        const auto orphan = directory / (valid_id ? "login-orphan-" + id + ".json" : "login-orphan-command.json");
        if (std::filesystem::exists(orphan)) {
            state.phase = "failed"; state.error = "login_orphan_slot_full_manual_recovery_required"; Publish();
        } else {
            std::filesystem::rename(path, orphan);
        }
        return;
    }
    if (std::filesystem::exists(directory / "login-results" / (id + ".json"))) { std::filesystem::remove(path); return; }
    if (!state.pending_request_id.empty()) return;
    const auto& p = command.value("params", Json());
    bool valid = command.contains("operation") && command["operation"].is_string() && command["operation"] == "create_character" && p.is_object() && p.contains("name") && p["name"].is_string() && !p["name"].get<std::string>().empty() && p.contains("female") && p["female"].is_boolean();
    for (const auto* field : {"job","face","hair","hair_color","skin","top","bottom","shoes","weapon"})
        valid = valid && p.contains(field) && p[field].is_number_integer() && p[field] >= INT32_MIN && p[field] <= INT32_MAX;
    if (!valid || state.phase != "character_list" || !state.characters_known) {
        Result(id, "rejected", valid ? "not_ready" : "invalid_request", 0); std::filesystem::remove(path); return;
    }
    const auto name = p["name"].get<std::string>();
    if (std::any_of(name.begin(), name.end(), [](unsigned char c){ return c < 32; })) {
        Result(id, "rejected", "invalid_request", 0); std::filesystem::remove(path); return;
    }
    try {
        const auto encoded = ms::encode_network_string(name);
        if (ms::decode_network_string(encoded) != name) {
            Result(id, "rejected", "invalid_name_encoding", 0); std::filesystem::remove(path); return;
        }
        // Character entries carry exactly 13 encoded bytes; longer names cannot be confirmed intact.
        if (encoded.size() > 13) {
            Result(id, "rejected", "name_too_long", 0); std::filesystem::remove(path); return;
        }
    } catch (const std::invalid_argument&) {
        Result(id, "rejected", "invalid_name_encoding", 0); std::filesystem::remove(path); return;
    }
    state.creation = ms::CharacterCreation{name,p["job"],p["face"],p["hair"],p["hair_color"],p["skin"],p["top"],p["bottom"],p["shoes"],p["weapon"],p["female"]};
    state.pending_request_id = id; state.creation_status = "accepted"; state.creation_error.clear(); state.created_cid = 0;
    deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    state.phase = "checking_character_name";
    Publish();
    Result(id, "accepted", "", 0);
    std::filesystem::remove(path);
    ms::NameCharPacket(name).dispatch();
}
