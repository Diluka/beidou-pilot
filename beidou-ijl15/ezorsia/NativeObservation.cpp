// SPDX-License-Identifier: AGPL-3.0-or-later
#include "stdafx.h"
#include "NativeObservation.h"

#include <array>
#include <chrono>
#include <cstring>
#include <sstream>

namespace NativeObservation {
namespace {
std::uint64_t UnixMs() {
    FILETIME time{};
    GetSystemTimeAsFileTime(&time);
    const auto ticks = (static_cast<std::uint64_t>(time.dwHighDateTime) << 32) | time.dwLowDateTime;
    return (ticks - 116444736000000000ULL) / 10000;
}
}

void Copy(std::uintptr_t address, void* output, std::size_t size) {
    if (size == 0) return;
    SIZE_T copied = 0;
    if (!ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(address),
        output, size, &copied) || copied != size) throw ReadError("native object read unavailable");
}

std::vector<unsigned char> Bytes(std::uintptr_t address, std::size_t size) {
    std::vector<unsigned char> result(size);
    Copy(address, result.data(), size);
    return result;
}

std::string Utf8(const std::string& text) {
    if (text.empty()) return {};
    const int count = MultiByteToWideChar(936, MB_ERR_INVALID_CHARS,
        text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (count == 0) throw ReadError("native text is not valid CP936");
    std::wstring wide(count, L'\0');
    MultiByteToWideChar(936, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), &wide[0], count);
    const int bytes = WideCharToMultiByte(CP_UTF8, 0, wide.data(), count, nullptr, 0, nullptr, nullptr);
    std::string result(bytes, '\0');
    if (bytes != 0) WideCharToMultiByte(CP_UTF8, 0, wide.data(), count, &result[0], bytes, nullptr, nullptr);
    return result;
}

std::string ZxString(std::uintptr_t field, std::size_t maximum) {
    const auto pointer = Read<std::uint32_t>(field);
    if (pointer == 0) return {};
    const auto length = Read<std::uint32_t>(pointer - 4);
    if (length > maximum) throw ReadError("native string exceeds observation boundary");
    const auto bytes = Bytes(pointer, length + 1);
    if (bytes[length] != 0) throw ReadError("native string terminator unavailable");
    return Utf8(std::string(reinterpret_cast<const char*>(bytes.data()), length));
}

std::uint32_t SecureInt(std::uintptr_t address) {
    const auto data = Read<std::array<std::uint32_t, 3>>(address);
    const auto mixed = data[0] ^ 0xBAADF00D;
    const auto checksum = data[1] + ((mixed >> 5) | (mixed << 27));
    if (checksum != data[2]) throw ReadError("native integer checksum unavailable");
    return data[0] ^ ((data[1] << 5) | (data[1] >> 27));
}

std::uint32_t SecureValue(std::uintptr_t address) {
    const auto guards = Read<std::array<unsigned char, 12>>(address);
    std::uint32_t pointer = 0;
    std::memcpy(&pointer, guards.data() + 8, sizeof(pointer));
    const auto encoded = Read<std::array<unsigned char, 10>>(pointer);
    unsigned char key = encoded[4];
    std::uint16_t checksum = 0x9A65;
    std::uint32_t result = 0;
    for (unsigned int index = 0; index < 4; ++index) {
        if (key == 0) key = 42;
        result |= static_cast<std::uint32_t>(encoded[index] ^ key) << (index * 8);
        key = static_cast<unsigned char>(key + encoded[index] + 42);
        checksum = static_cast<std::uint16_t>((checksum << 3) | ((checksum >> 13) + key));
    }
    std::uint16_t expected = 0;
    std::memcpy(&expected, encoded.data() + 8, sizeof(expected));
    if (guards[0] != encoded[5] || guards[4] != encoded[6] || checksum != expected)
        throw ReadError("native value checksum unavailable");
    return result;
}

MapleControl::Observation Collect(const std::string& domain) {
    using Collector = Value (*)();
    const std::pair<const char*, Collector> collectors[]{
        {"stage", Stage}, {"scene", Scene}, {"inventory", Inventory}, {"character", Character},
        {"quests", Quests}, {"hotkeys", Hotkeys}, {"dialog", Dialog}, {"ui", Ui}, {"shop", Shop}
    };
    Collector selected = nullptr;
    for (const auto& entry : collectors) if (domain == entry.first) selected = entry.second;
    MapleControl::Observation result;
    if (selected != nullptr) {
        const auto started = std::chrono::steady_clock::now();
        try {
            result.data = selected();
            result.data["read_seconds"] = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - started).count();
        }
        catch (const ReadError& failure) { result.status = "unavailable"; result.error = failure.what(); }
    }
    else {
        result.status = "unsupported";
        result.error = "unsupported observation domain";
    }
    return result;
}

void Tick(const std::string& directory, const std::string& instance,
    const std::string& run, std::uint64_t generation, std::uint64_t sequence) {
    const std::string path = directory + "\\observation-request.txt";
    const HANDLE input = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (input == INVALID_HANDLE_VALUE) return;
    std::array<char, 513> bytes{};
    DWORD length = 0;
    const bool complete = ReadFile(input, bytes.data(), 512, &length, nullptr) != FALSE;
    CloseHandle(input);
    DeleteFileA(path.c_str());
    std::istringstream request(std::string(bytes.data(), length));
    int protocol = 0;
    std::string target, id, domain, extra;
    if (!complete || length == 512 || !(request >> protocol >> target >> id >> domain) ||
        request >> extra || protocol != 1 || target != instance || id.size() != 32 ||
        id.find_first_not_of("0123456789abcdefABCDEF") != std::string::npos) return;
    const auto observation = Collect(domain);
    const auto output = Value::Object({{"protocol", 1}, {"instance_id", instance}, {"run_id", run},
        {"request_id", id}, {"domain", domain}, {"seq", sequence}, {"scene_generation", generation},
        {"observed_at_ms", UnixMs()}, {"status", observation.status}, {"data", observation.data},
        {"error", observation.error.empty() ? Value{} : Value(observation.error)}}).Dump();
    const std::string temporary = directory + "\\observation.tmp";
    const HANDLE file = CreateFileA(temporary.c_str(), GENERIC_WRITE, 0, nullptr,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    const bool saved = WriteFile(file, output.data(), static_cast<DWORD>(output.size()), &written,
        nullptr) && written == output.size();
    CloseHandle(file);
    if (saved) MoveFileExA(temporary.c_str(), (directory + "\\observation.json").c_str(),
        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}
}
