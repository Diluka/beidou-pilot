#pragma once
#include <filesystem>
#include <string>
#include <cstdint>
#include <chrono>

class LoginBridge {
public:
    LoginBridge(std::filesystem::path directory, std::string instance, std::string run);
    void Tick();
private:
    void Publish();
    void Result(const std::string& id, const std::string& status, const std::string& error, int32_t cid);
    std::filesystem::path directory;
    std::string instance, run;
    uint64_t sequence = 0;
    std::chrono::steady_clock::time_point deadline;
};
