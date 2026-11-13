// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Original-client login/creation action lane.
//
// Every action revalidates the observed identity and page before calling one
// original client routine on the game thread. Unknown or changed state is
// reported as rejected; nothing is retried and no packet or field is forged.
#include "stdafx.h"
#include "LoginAction.h"
#include "NativeObservation.h"

#include <array>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace BeiDouBridge {
namespace LoginAction {
namespace {

// BeiDou Client V17, EXE SHA256
// 1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df.
const std::uint32_t kLoginState = 0x00BEDED4;
const std::uint32_t kLoginVtable = 0x00AF6B24;
const std::uint32_t kWindowManager = 0x00BEC20C;
const std::uint32_t kWindowManagerVtable = 0x00B3F13C;

const std::uint32_t kTermsVtable = 0x00AF79C8;
const std::uint32_t kGenderVtable = 0x00AF7298;
const std::uint32_t kLoginFormVtable = 0x00AF7940;
const std::uint32_t kWorldVtable = 0x00AF7A90;
const std::uint32_t kChannelVtable = 0x00AF7B4C;
const std::uint32_t kCharacterListVtable = 0x00AF6D90;
const std::uint32_t kCategoryVtable = 0x00AF7360;
const std::uint32_t kNameVtable = 0x00AF7564;
const std::uint32_t kAppearanceVtable = 0x00AF777C;

const std::uint32_t kTermsButton = 0x00621B0D;
const std::uint32_t kWorldButton = 0x00624AE8;
const std::uint32_t kChannelButton = 0x00628978;
const std::uint32_t kCharacterListButton = 0x00601667;
const std::uint32_t kCategoryButton = 0x0061747F;
const std::uint32_t kNameButton = 0x006175EA;
const std::uint32_t kAppearanceButton = 0x006182E9;

const std::uint32_t kStepLogin = 0;
const std::uint32_t kStepWorld = 1;
const std::uint32_t kStepCharacterList = 2;
const std::uint32_t kStepCategory = 3;
const std::uint32_t kStepCreate = 4;

using SubmitLogin = int(__thiscall*)(void*, const char*, const char*);
using SendGender = void(__thiscall*)(void*, int);
using SelectChannel = void(__thiscall*)(void*, int, int);
using CheckName = void(__thiscall*)(void*, const char*);
using ButtonHandler = void(__thiscall*)(void*, int);

const auto submitLogin = reinterpret_cast<SubmitLogin>(0x005F6952);
const auto sendGender = reinterpret_cast<SendGender>(0x005FC68C);
const auto selectChannel = reinterpret_cast<SelectChannel>(0x005F6D6A);
const auto checkName = reinterpret_cast<CheckName>(0x005F7FE7);

struct Request {
    std::string requestId;
    std::string action;
    std::array<std::string, 3> arguments;
};

struct LoginState {
    std::uint32_t login = 0;
    std::uint32_t step = 0;
    std::uint32_t transition = 0;
    std::uint32_t pending = 0;
};

struct WindowSpec {
    std::uint32_t vtable;
    std::uint32_t button;
    std::uint32_t ownerOffset;
    std::uint32_t step;
};

const WindowSpec windows[] = {
    {kTermsVtable, kTermsButton, 0, kStepLogin},
    {kWorldVtable, kWorldButton, 0x80, kStepWorld},
    {kChannelVtable, kChannelButton, 0xD4, kStepWorld},
    {kCharacterListVtable, kCharacterListButton, 0x70, kStepCharacterList},
    {kCategoryVtable, kCategoryButton, 0x6C, kStepCategory},
    {kNameVtable, kNameButton, 0x6C, kStepCreate},
    {kAppearanceVtable, kAppearanceButton, 0x6C, kStepCreate},
};

std::string Quote(const std::string& text) {
    std::string quoted = "\"";
    for (const char character : text) {
        switch (character) {
        case '"':
            quoted += "\\\"";
            break;
        case '\\':
            quoted += "\\\\";
            break;
        case '\n':
            quoted += "\\n";
            break;
        case '\r':
            quoted += "\\r";
            break;
        case '\t':
            quoted += "\\t";
            break;
        default:
            if (static_cast<unsigned char>(character) < 0x20) {
                const char digits[] = "0123456789abcdef";
                quoted += "\\u00";
                quoted += digits[(static_cast<unsigned char>(character) >> 4) & 0x0F];
                quoted += digits[static_cast<unsigned char>(character) & 0x0F];
            } else {
                quoted += character;
            }
        }
    }
    quoted += '"';
    return quoted;
}

bool WriteResult(const std::string& directory, const std::string& instance, const std::string& run,
                 const Request& request, const char* status, const std::string& reason) {
    std::ostringstream out;
    out << "{\"protocol\":1,\"instance_id\":" << Quote(instance) << ",\"run_id\":" << Quote(run)
        << ",\"request_id\":" << Quote(request.requestId) << ",\"action\":" << Quote(request.action)
        << ",\"status\":" << Quote(status) << ",\"reason\":" << (reason.empty() ? "null" : Quote(reason)) << "}\n";
    const std::string bytes = out.str();
    const std::string temporary = directory + "\\login-action-result.tmp";
    const HANDLE file =
        CreateFileA(temporary.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    const bool complete =
        WriteFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr) && written == bytes.size();
    const bool closed = CloseHandle(file) != FALSE;
    return complete && closed
           && MoveFileExA(temporary.c_str(), (directory + "\\login-action-result.json").c_str(),
                          MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}

bool ReadRequest(const std::string& directory, std::string& instance, Request& request) {
    const std::string path = directory + "\\login-action.txt";
    const HANDLE input = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr,
                                     OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (input == INVALID_HANDLE_VALUE) return false;
    std::array<char, 4097> bytes{};
    DWORD length = 0;
    const bool complete = ReadFile(input, bytes.data(), 4096, &length, nullptr) != FALSE && length < 4096;
    CloseHandle(input);
    DeleteFileA(path.c_str());
    if (!complete) return false;
    std::istringstream stream(std::string(bytes.data(), length));
    unsigned int protocol = 0;
    std::string extra;
    if (!(stream >> protocol >> instance >> request.requestId >> request.action >> request.arguments[0]
          >> request.arguments[1] >> request.arguments[2])
        || protocol != 1 || (stream >> extra))
        return false;
    return true;
}

bool DecodeBase64(const std::string& text, std::string& output) {
    output.clear();
    if (text == "-") return true;
    if (text.empty() || text.size() % 4 != 0) return false;
    const auto decode = [](char character) -> int {
        if (character >= 'A' && character <= 'Z') return character - 'A';
        if (character >= 'a' && character <= 'z') return character - 'a' + 26;
        if (character >= '0' && character <= '9') return character - '0' + 52;
        if (character == '+') return 62;
        if (character == '/') return 63;
        return -1;
    };
    for (std::size_t index = 0; index < text.size(); index += 4) {
        int values[4] = {};
        int padding = 0;
        for (int slot = 0; slot < 4; ++slot) {
            const char character = text[index + slot];
            if (character == '=') {
                if (index + 4 != text.size() || slot < 2) return false;
                values[slot] = 0;
                ++padding;
            } else {
                if (padding != 0) return false;
                values[slot] = decode(character);
                if (values[slot] < 0) return false;
            }
        }
        const std::uint32_t chunk =
            (static_cast<std::uint32_t>(values[0]) << 18) | (static_cast<std::uint32_t>(values[1]) << 12)
            | (static_cast<std::uint32_t>(values[2]) << 6) | static_cast<std::uint32_t>(values[3]);
        output += static_cast<char>((chunk >> 16) & 0xFF);
        if (padding < 2) output += static_cast<char>((chunk >> 8) & 0xFF);
        if (padding < 1) output += static_cast<char>(chunk & 0xFF);
    }
    return true;
}

bool ParseAddress(const std::string& text, std::uint32_t& address) {
    if (text.size() < 3 || text.size() > 10 || text[0] != '0' || (text[1] != 'x' && text[1] != 'X')) return false;
    std::uint32_t value = 0;
    for (std::size_t index = 2; index < text.size(); ++index) {
        const char character = text[index];
        unsigned int digit = 0;
        if (character >= '0' && character <= '9')
            digit = static_cast<unsigned int>(character - '0');
        else if (character >= 'a' && character <= 'f')
            digit = static_cast<unsigned int>(character - 'a' + 10);
        else if (character >= 'A' && character <= 'F')
            digit = static_cast<unsigned int>(character - 'A' + 10);
        else
            return false;
        if (value > 0x0FFFFFFF) return false;
        value = (value << 4) | digit;
    }
    if (value < 0x00010000) return false;
    address = value;
    return true;
}

bool ParseInteger(const std::string& text, int maximum, int& value) {
    if (text.empty() || text.size() > 9) return false;
    int parsed = 0;
    for (const char character : text) {
        if (character < '0' || character > '9') return false;
        parsed = parsed * 10 + (character - '0');
        if (parsed > maximum) return false;
    }
    value = parsed;
    return true;
}

bool Read32(const std::uint32_t address, std::uint32_t& value) {
    if (address == 0) return false;
    try {
        value = NativeObservation::Read<std::uint32_t>(address);
        return true;
    } catch (...) {
        return false;
    }
}

bool LoadLogin(LoginState& state) {
    std::uint32_t manager = 0, table = 0;
    if (!Read32(kWindowManager, manager) || manager == 0) return false;
    if (!Read32(manager, table) || table != kWindowManagerVtable) return false;
    if (!Read32(kLoginState, state.login) || state.login == 0) return false;
    if (!Read32(state.login, table) || table != kLoginVtable) return false;
    return Read32(state.login + 0x168, state.step) && Read32(state.login + 0x16C, state.transition)
           && Read32(state.login + 0x170, state.pending);
}

bool ActiveWindow(const std::uint32_t address, std::uint32_t& table) {
    if (!Read32(address, table)) return false;
    bool known = false, present = false;
    try {
        present = NativeObservation::WindowActive(address, known);
    } catch (...) {
        return false;
    }
    return present && known;
}

bool WindowOwner(const std::uint32_t address, const std::uint32_t offset, const std::uint32_t login) {
    if (offset == 0) return true;
    std::uint32_t owner = 0;
    return Read32(address + offset, owner) && owner == login;
}

bool ButtonSlot(const std::uint32_t address, const std::uint32_t expected) {
    std::uint32_t table = 0, handler = 0;
    return Read32(address, table) && Read32(table + 0x20, handler) && handler == expected;
}

bool RequireStep(const LoginState& state, const std::uint32_t step) {
    return state.step == step && state.transition == 0 && state.pending == 0;
}

bool PageWindow(const LoginState& state, const std::uint32_t address, const std::uint32_t vtable,
                const std::uint32_t ownerOffset) {
    std::uint32_t table = 0;
    return ActiveWindow(address, table) && table == vtable && WindowOwner(address, ownerOffset, state.login);
}

const WindowSpec* FindWindowSpec(const std::uint32_t vtable) {
    for (const auto& spec : windows)
        if (spec.vtable == vtable) return &spec;
    return nullptr;
}

bool Dispatch(const Request& request, std::string& reason) {
    LoginState state;
    if (!LoadLogin(state)) {
        reason = "login_state_unavailable";
        return false;
    }
    if (request.action == "submit_login") {
        std::uint32_t address = 0;
        std::string user, password;
        if (!ParseAddress(request.arguments[0], address) || !DecodeBase64(request.arguments[1], user)
            || !DecodeBase64(request.arguments[2], password) || user.empty() || password.empty()) {
            reason = "invalid_arguments";
            return false;
        }
        if (!RequireStep(state, kStepLogin)) {
            reason = "login_state_changed";
            return false;
        }
        std::uint32_t table = 0, account = 0, secret = 0;
        if (!ActiveWindow(address, table) || table != kLoginFormVtable || !WindowOwner(address, 0x80, state.login)) {
            reason = "login_form_not_active";
            return false;
        }
        if (!Read32(address + 0xCC, account) || account == 0 || !Read32(address + 0xD4, secret) || secret == 0) {
            reason = "login_form_edits_unavailable";
            return false;
        }
        const int accepted = submitLogin(reinterpret_cast<void*>(state.login), user.c_str(), password.c_str());
        if (accepted == 0) {
            reason = "login_submit_not_accepted";
            return false;
        }
        return true;
    }
    if (request.action == "accept_terms") {
        std::uint32_t address = 0;
        if (!ParseAddress(request.arguments[0], address)) {
            reason = "invalid_arguments";
            return false;
        }
        std::uint32_t table = 0;
        if (!RequireStep(state, kStepLogin) || !ActiveWindow(address, table) || table != kTermsVtable
            || !ButtonSlot(address, kTermsButton)) {
            reason = "terms_page_not_active";
            return false;
        }
        reinterpret_cast<ButtonHandler>(kTermsButton)(reinterpret_cast<void*>(address), 1);
        return true;
    }
    if (request.action == "select_gender") {
        std::uint32_t address = 0;
        int gender = 0;
        if (!ParseAddress(request.arguments[0], address) || !ParseInteger(request.arguments[1], 1, gender)) {
            reason = "invalid_arguments";
            return false;
        }
        std::uint32_t table = 0;
        if (!RequireStep(state, kStepLogin) || !ActiveWindow(address, table) || table != kGenderVtable) {
            reason = "gender_page_not_active";
            return false;
        }
        sendGender(reinterpret_cast<void*>(state.login), gender);
        return true;
    }
    if (request.action == "select_world") {
        std::uint32_t address = 0;
        int index = 0;
        if (!ParseAddress(request.arguments[0], address) || !ParseInteger(request.arguments[1], 30, index)) {
            reason = "invalid_arguments";
            return false;
        }
        const WindowSpec* spec = FindWindowSpec(kWorldVtable);
        if (!RequireStep(state, kStepWorld) || spec == nullptr
            || !PageWindow(state, address, kWorldVtable, spec->ownerOffset) || !ButtonSlot(address, kWorldButton)) {
            reason = "world_page_not_active";
            return false;
        }
        std::uint32_t count = 0;
        if (!Read32(address + 0x84, count) || static_cast<std::uint32_t>(index) >= count) {
            reason = "world_selection_unavailable";
            return false;
        }
        reinterpret_cast<ButtonHandler>(kWorldButton)(reinterpret_cast<void*>(address), 1000 + index);
        return true;
    }
    if (request.action == "select_channel") {
        int channelIndex = 0;
        std::uint32_t address = 0;
        if (!ParseInteger(request.arguments[0], 40, channelIndex) || !ParseAddress(request.arguments[1], address)) {
            reason = "invalid_arguments";
            return false;
        }
        std::uint32_t table = 0, ready = 0;
        if (!RequireStep(state, kStepWorld) || !ActiveWindow(address, table) || table != kChannelVtable
            || !WindowOwner(address, 0xD4, state.login) || !Read32(address + 0xB8, ready) || ready != 0) {
            reason = "channel_page_not_active";
            return false;
        }
        std::uint32_t entry = 0, worldValue = 0, channels = 0, channelCount = 0;
        if (!Read32(address + 0xE0, entry) || entry == 0 || !Read32(entry, worldValue)
            || !Read32(entry + 0x1C, channels) || channels == 0 || !Read32(channels - 4, channelCount)
            || static_cast<std::uint32_t>(channelIndex) >= channelCount || channelCount > 40) {
            reason = "channel_list_unavailable";
            return false;
        }
        selectChannel(reinterpret_cast<void*>(state.login), static_cast<int>(worldValue), channelIndex);
        return true;
    }
    if (request.action == "check_name") {
        std::uint32_t address = 0;
        std::string name;
        if (!ParseAddress(request.arguments[0], address) || !DecodeBase64(request.arguments[1], name) || name.empty()
            || name.size() > 12) {
            reason = "invalid_arguments";
            return false;
        }
        for (const char character : name)
            if (character < 0x20 || character > 0x7E) {
                reason = "invalid_arguments";
                return false;
            }
        if (!RequireStep(state, kStepCreate) || !PageWindow(state, address, kNameVtable, 0x6C)
            || !ButtonSlot(address, kNameButton)) {
            reason = "name_page_not_active";
            return false;
        }
        checkName(reinterpret_cast<void*>(state.login), name.c_str());
        return true;
    }
    if (request.action == "ui_button") {
        std::uint32_t address = 0;
        int control = 0;
        if (!ParseAddress(request.arguments[0], address) || !ParseInteger(request.arguments[1], 2000, control)) {
            reason = "invalid_arguments";
            return false;
        }
        std::uint32_t table = 0;
        if (!ActiveWindow(address, table)) {
            reason = "window_not_active";
            return false;
        }
        const WindowSpec* spec = FindWindowSpec(table);
        if (spec == nullptr) {
            reason = "window_not_supported";
            return false;
        }
        if (!RequireStep(state, spec->step) || !WindowOwner(address, spec->ownerOffset, state.login)
            || !ButtonSlot(address, spec->button)) {
            reason = "window_state_mismatch";
            return false;
        }
        reinterpret_cast<ButtonHandler>(spec->button)(reinterpret_cast<void*>(address), control);
        return true;
    }
    reason = "unsupported_action";
    return false;
}

bool ValidRequestId(const std::string& text) {
    if (text.size() != 32) return false;
    for (const char character : text)
        if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f')
              || (character >= 'A' && character <= 'F')))
            return false;
    return true;
}

} // namespace

void Tick(const std::string& directory, const std::string& instance, const std::string& run) {
    std::string target;
    Request request;
    if (!ReadRequest(directory, target, request)) return;
    if (target != instance || !ValidRequestId(request.requestId)) return;
    std::string reason;
    bool dispatched = false;
    try {
        dispatched = Dispatch(request, reason);
    } catch (const NativeObservation::ReadError&) {
        reason = "native_read_failed";
    } catch (...) {
        reason = "native_action_failed";
    }
    WriteResult(directory, instance, run, request, dispatched ? "dispatched" : "rejected", reason);
}

} // namespace LoginAction
} // namespace BeiDouBridge
