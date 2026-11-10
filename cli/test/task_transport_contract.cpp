// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TaskTransport.h"
#include <nlohmann/json.hpp>

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {
using Json = nlohmann::json;
const std::string session(32, 'a');

void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

// The fixture owns only sampled state and native release acknowledgements.
class NativeBoundary final : public MapleControl::Adapter {
public:
    NativeBoundary() {
        state.instanceId = "contract-instance";
        state.inGame = state.ready = state.mapKnown = state.characterKnown = state.positionKnown = true;
        state.sceneGeneration = 1;
        state.mapId = 50000;
        state.character.id = 1;
        state.character.values[6] = 100;
        state.character.known.fill(true);
    }

    const char* Backend() const override { return "contract"; }

    const MapleControl::State& Observe() const override { return state; }

    bool Supports(MapleControl::ActionKind) const override { return true; }

    bool Begin(const MapleControl::Action&, std::string& error) override {
        if (!Released()) {
            error = "native_input_still_owned";
            return false;
        }
        active = true;
        result = {};
        result.dispatched = true;
        return true;
    }

    MapleControl::ActionResult Result() const override { return result; }

    void Release() override {
        active = false;
        releasing = 2;
        ++releaseCalls;
    }

    bool Released() const override { return !active && releasing == 0; }

    bool ReleasePending() const override { return releasing != 0; }

    bool Logs(const std::string& scriptId, const std::vector<std::string>& lines) override {
        Check(scriptId == session, "log changed the active script identity");
        logs.insert(logs.end(), lines.begin(), lines.end());
        return true;
    }

    void Advance() {
        ++state.sequence;
        state.observedAtMs += 20;
        if (releasing != 0) --releasing;
        result.controlReleased = Released();
    }

    MapleControl::State state;
    MapleControl::ActionResult result;
    std::vector<std::string> logs;
    bool active = false;
    int releasing = 0;
    int releaseCalls = 0;
};

std::string Hex(const std::string& value) {
    std::ostringstream encoded;
    for (unsigned char byte : value)
        encoded << std::hex << std::setfill('0') << std::setw(2) << static_cast<unsigned int>(byte);
    return encoded.str();
}

void Write(const std::filesystem::path& path, const std::string& value) {
    std::ofstream output(path, std::ios::binary);
    output << value;
    Check(static_cast<bool>(output), "could not publish contract input");
}

Json Read(const std::filesystem::path& directory, const std::string& requestId) {
    std::ifstream input(directory / "task-results" / (requestId + ".json"));
    Check(static_cast<bool>(input), "management result was not published");
    return Json::parse(input);
}

void Tick(NativeBoundary& native, MapleControl::Runtime& runtime, MapleControl::TaskTransport& transport) {
    native.Advance();
    runtime.Tick();
    Check(transport.Tick(runtime, native.state), "management result publication failed");
}

void AddAndStop(const std::filesystem::path& directory) {
    NativeBoundary native;
    MapleControl::Runtime runtime(native);
    MapleControl::TaskTransport transport(directory.string(), "contract-run");
    std::string error;
    Check(
        runtime.Start(
            session,
            "shared_text='会话'; game.spawn('existing', 0, function() while true do game.log('existing'); game.sleep(0) end end); while true do game.sleep(0) end",
            0, error),
        error);
    Tick(native, runtime, transport);
    const auto before = std::count(native.logs.begin(), native.logs.end(), "[existing] existing");
    const std::string requestId(32, '1');
    const std::string name = "追加 任务";
    Write(directory / "command.txt", "original-session-command\n");
    Write(directory / "scripts" / (requestId + ".lua"),
          "game.acquire()\r\n"
          R"lua(game.log(shared_text .. ':中文 "引号"'))lua"
          "\r\ngame.move('right', 1)\r\nwhile true do game.sleep(0) end\r\n");
    Write(directory / "task-request.txt", "1 contract-instance contract-run " + session + " 1 " + requestId + " add "
                                              + Hex(name) + " 0 10 " + requestId + "\n");
    Tick(native, runtime, transport);
    const auto added = Read(directory, requestId);
    Check(added["status"] == "completed" && added["changed"] == true, "task was not added");
    Check(added["request_id"] == requestId && added["script_id"] == session && added["name"] == name
              && added["instance_id"] == native.state.instanceId && added["run_id"] == "contract-run",
          "management result changed its request identity");
    const auto revision = added["revision"].get<std::uint64_t>();
    Check(revision != 0, "added task did not receive a revision");
    for (int attempt = 0; attempt < 10 && !native.active; ++attempt) Tick(native, runtime, transport);
    Check(native.active, "added Lua source did not reach the native boundary");
    Check(std::find(native.logs.begin(), native.logs.end(), "[追加 任务] 会话:中文 \"引号\"") != native.logs.end(),
          "UTF-8, quotes, CRLF source or shared globals changed in transit");
    Check(std::count(native.logs.begin(), native.logs.end(), "[existing] existing") > before,
          "the existing task did not continue during the added task");

    const std::string stopId(32, '2');
    Write(directory / "task-request.txt", "1 contract-instance contract-run " + session + " 0 " + stopId + " stop "
                                              + Hex(name) + " " + std::to_string(revision) + " 0 -\n");
    Tick(native, runtime, transport);
    Check(Read(directory, stopId)["status"] == "pending", "stop acknowledged before native release");
    Check(native.releaseCalls == 1 && native.releasing != 0, "stop did not request its own native release");
    Tick(native, runtime, transport);
    Check(Read(directory, stopId)["status"] == "pending", "stop lost its pending result identity");
    Tick(native, runtime, transport);
    const auto stopped = Read(directory, stopId);
    Check(stopped["status"] == "completed" && stopped["control_released"] == true && stopped["revision"] == revision,
          "stop did not publish release-confirmed completion");
    Check(runtime.Running() && runtime.CurrentStatus()->id == session, "management stopped the original session");
    std::ifstream command(directory / "command.txt");
    std::string original;
    std::getline(command, original);
    Check(original == "original-session-command", "management overwrote the original command lane");
}

void RejectForeignAndInvalid(const std::filesystem::path& directory) {
    NativeBoundary native;
    MapleControl::Runtime runtime(native);
    MapleControl::TaskTransport transport(directory.string(), "contract-run");
    std::string error;
    Check(runtime.Start(session, "while true do game.sleep(0) end", 0, error), error);
    Tick(native, runtime, transport);

    struct Input {
        std::string instance, run, script, generation, nameHex, source;
    };

    const auto name = Hex("observer");
    const std::vector<Input> inputs{
        {"foreign-instance", "contract-run", session, "1", name, "game.log('unexpected')"},
        {"contract-instance", "foreign-run", session, "1", name, "game.log('unexpected')"},
        {"contract-instance", "contract-run", std::string(32, 'b'), "1", name, "game.log('unexpected')"},
        {"contract-instance", "contract-run", session, "0", name, "game.log('unexpected')"},
        {"contract-instance", "contract-run", session, "1", "gg", "game.log('unexpected')"},
        {"contract-instance", "contract-run", session, "1", name, "local broken ="},
    };
    char requestByte = '3';
    for (const auto& input : inputs) {
        const std::string requestId(32, requestByte++);
        Write(directory / "scripts" / (requestId + ".lua"), input.source);
        Write(directory / "task-request.txt", "1 " + input.instance + " " + input.run + " " + input.script + " "
                                                  + input.generation + " " + requestId + " add " + input.nameHex
                                                  + " 0 10 " + requestId + "\n");
        Tick(native, runtime, transport);
        const auto result = Read(directory, requestId);
        Check(result["status"] == "rejected" && result["request_id"] == requestId,
              "foreign or invalid management input was not rejected independently");
        const auto* current = runtime.CurrentStatus();
        Check(runtime.Running() && current->id == session && current->tasks.size() == 1
                  && current->control.owner == "main" && native.releaseCalls == 0 && native.logs.empty(),
              "rejected management input disturbed the original task or owner");
    }
}
}

int main(int argc, char** argv) {
    Check(argc == 3, "expected a scenario and temporary directory");
    const std::filesystem::path directory(argv[2]);
    std::filesystem::create_directories(directory / "scripts");
    if (std::string(argv[1]) == "add-stop")
        AddAndStop(directory);
    else if (std::string(argv[1]) == "reject")
        RejectForeignAndInvalid(directory);
    else
        Check(false, "unknown transport scenario");
}
