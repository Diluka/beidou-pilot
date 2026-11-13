// SPDX-License-Identifier: AGPL-3.0-or-later
#include "HeadlessState.h"
#include "LoginState.h"
#include "LoginBridge.h"
#include "SharedLuaAdapter.h"
#include <nlohmann/json.hpp>
#include "Configuration.h"
#include "Constants.h"
#include "Character/Player.h"
#include "Gameplay/Stage.h"
#include "Gameplay/MapleMap/MapPortals.h"
#include "Gameplay/Combat/DamageNumber.h"
#include "IO/UI.h"
#include "Net/Session.h"
#include "Net/Packets/LoginPackets.h"
#include "Util/ImgFiles.h"

#include <chrono>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <thread>

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;
volatile std::sig_atomic_t interrupted = 0;

namespace
{
    Json diagnostics(std::uint64_t tick)
    {
        const auto& login = ms::login_state();
        Json characters = Json::array();
        for (const auto& character : login.characters)
            characters.push_back({{"id", character.id}, {"name", character.stats.name}});
        return {{"tick", tick}, {"run_id", login.run_id}, {"phase", login.phase}, {"characters", login.characters_known ? characters : Json(nullptr)},
            {"connected", ms::Session::get().is_connected()},
            {"rx_packets", login.rx_packets}, {"tx_packets", login.tx_packets},
            {"last_opcode", login.last_opcode}, {"packet_parse_errors", login.packet_parse_errors},
            {"last_packet_error", login.last_packet_error}};
    }
}

int main(int argc, char** argv)
{
    // Existing client diagnostics go to stderr; stdout contains JSONL exclusively.
    std::ostream output(std::cout.rdbuf());
    std::cout.rdbuf(std::cerr.rdbuf());
    const auto emit = [&output](Json value) { output << value.dump(-1, ' ', false, Json::error_handler_t::replace) << '\n' << std::flush; };
    try
    {
        if (argc != 3 || (std::string(argv[1]) != "--config" && std::string(argv[1]) != "--check-resources"))
            throw std::invalid_argument("usage: beidou-headless --config PRIVATE.json | --check-resources DIR");
        const bool offline = std::string(argv[1]) == "--check-resources";
        Json config;
        std::filesystem::path bridgeDirectory;
        if (!offline)
        {
            std::ifstream file(argv[2]);
            if (!file) throw std::runtime_error("cannot open private configuration");
            config = Json::parse(file);
            bridgeDirectory = config.at("bridge_dir").get<std::string>();
            if (bridgeDirectory.empty()) throw std::invalid_argument("bridge_dir is required; control uses the shared Lua bridge");
            if (config.contains("max_seconds")) throw std::invalid_argument("max_seconds is unsupported; Docker owns the client instance lifetime");
        }
        const auto resources = std::filesystem::absolute(offline ? argv[2] : config.at("resources_dir").get<std::string>());
        std::filesystem::current_path(resources);
        const auto resource_error = ms::ImgFiles::init();
        if (resource_error) throw std::runtime_error(resource_error.get_message());
        ms::Char::init();
        ms::DamageNumber::init();
        ms::MapPortals::init();
        ms::Stage::get().init();
        ms::UI::get().init();
        emit({{"event", "resources_ready"}, {"headless", true}, {"render_backend", "none"}});
        if (offline) return 0;

        ms::Setting<ms::ServerIP>::get().save(config.at("server_host").get<std::string>());
        ms::Setting<ms::ServerPort>::get().save(std::to_string(config.value("server_port", 8484)));
        ms::Setting<ms::SaveLogin>::get().save(false);
        char macs[] = "02-00-00-00-00-04";
        char hwid[] = "020000000004";
        char volume[] = "00000004";
        ms::Configuration::get().set_macs(macs);
        ms::Configuration::get().set_hwid(hwid, volume);
        const auto cid = config.value("character_id", 0);
        if (config.contains("character_id") && cid <= 0) throw std::invalid_argument("character_id must be positive");
        ms::configure_login(cid, config.value("world", 0), config.value("channel", 0));
        ms::login_state().run_id = config.value("run_id", std::string{});
        ms::login_state().accept_tos = config.value("accept_tos", false);
        if (config.contains("account_female")) ms::login_state().account_female = config.at("account_female").get<bool>();
        if (!ms::Session::get().init(config.at("server_host").get<std::string>().c_str(), std::to_string(config.value("server_port", 8484)).c_str()))
            throw std::runtime_error("login connection failed");
        ms::LoginPacket(config.at("username").get<std::string>(), config.at("password").get<std::string>()).dispatch();
        std::signal(SIGINT, [](int signal) { interrupted = signal; });
        std::signal(SIGTERM, [](int signal) { interrupted = signal; });
        SharedLuaAdapter bridge(bridgeDirectory, config.value("run_id", std::string{}));
        LoginBridge loginBridge(bridgeDirectory, bridge.Observe().instanceId, config.value("run_id", std::string{}));
        auto next_login_bridge = Clock::now();
        auto next_tick = Clock::now();
        auto next_diagnostics = next_tick;
        std::uint64_t tick = 0;
        std::string last_phase;
        std::string exit_reason;
        int exit_code = 0;
        while (!interrupted)
        {
            const auto now = Clock::now();
            ms::Session::get().read();
            if (ms::headless_state().in_game) ms::login_state().phase = "in_game";
            if (now >= next_login_bridge) {
                loginBridge.Tick();
                next_login_bridge = now + std::chrono::milliseconds(100);
            }
            if (!ms::Session::get().is_connected())
            {
                if (!ms::login_state().pending_request_id.empty())
                    ms::stop_pending_creation("disconnected");
                if (ms::login_state().error.empty()) ms::login_state().error = "disconnected";
                ms::login_state().phase = "failed";
                loginBridge.Tick();
                exit_reason = "disconnected";
                exit_code = 2;
                emit({{"event", "disconnected"}, {"diagnostics", diagnostics(tick)}});
                break;
            }
            // Keep the real 8 ms simulation clock even while the controller is idle.
            if (now >= next_tick)
            {
                ms::Stage::get().update();
                ++tick;
                bridge.Tick(tick, false);
                next_tick += std::chrono::milliseconds(ms::Constants::TIMESTEP);
            }
            const auto& phase = ms::login_state().phase;
            if (phase != last_phase)
            {
                emit({{"event", "phase"}, {"phase", phase}, {"diagnostics", diagnostics(tick)}});
                last_phase = phase;
            }
            if (now >= next_diagnostics)
            {
                emit({{"event", "runtime"}, {"diagnostics", diagnostics(tick)}});
                next_diagnostics = now + std::chrono::seconds(10);
            }
            if (!ms::login_state().error.empty()) {
                if (!ms::login_state().pending_request_id.empty()) ms::stop_pending_creation("client_failed");
                loginBridge.Tick();
                throw std::runtime_error(ms::login_state().error);
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        if (exit_reason.empty()) exit_reason = interrupted == SIGINT ? "sigint" : "sigterm";
        if (!ms::login_state().pending_request_id.empty()) {
            ms::stop_pending_creation("client_stopped");
            loginBridge.Tick();
        }
        bridge.Shutdown();
        ms::Stage::get().stop_actions();
        emit({{"event", "stopping"}, {"reason", exit_reason}, {"exit_code", exit_code}, {"diagnostics", diagnostics(tick)}});
        ms::Session::get().close();
        emit({{"event", "closed"}, {"reason", exit_reason}, {"exit_code", exit_code},
            {"connected", ms::Session::get().is_connected()}});
        return exit_code;
    }
    catch (const std::exception& error)
    {
        emit({{"event", "fatal"}, {"reason", "fatal_error"}, {"exit_code", 1}, {"message", error.what()}});
        return 1;
    }
}
