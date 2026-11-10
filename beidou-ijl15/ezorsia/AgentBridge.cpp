#include "stdafx.h"
#include "AgentBridge.h"
#include "Runtime.h"
#include "TaskTransport.h"
#include "NativeKeyInput.h"
#include "NativeItemUse.h"
#include "NativeObservation.h"

#include <array>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>
#include <utility>

// These addresses and layouts belong to BeiDou Client V17, EXE SHA256
// 1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df.
// The bridge calls original client routines; it never builds game packets.
namespace {
struct ClientApplication;
struct InputSystem;
using ApplicationUpdate = void(__thiscall*)(ClientApplication*, int);
using KeyPressed = unsigned int(__thiscall*)(InputSystem*, int);
using InputModifiers = unsigned int(__thiscall*)(InputSystem*);
using InputMessage = void(__stdcall*)(unsigned int, unsigned int, unsigned int);
struct ClientPlayer;
using ActiveSkill = int(__thiscall*)(ClientPlayer*, int, int, int*);
struct ClientContext;
using UseItem = void(__thiscall*)(ClientContext*, int, int);

auto originalUpdate = reinterpret_cast<ApplicationUpdate>(0x009F84D0);
auto originalKeyPressed = reinterpret_cast<KeyPressed>(0x0059A25A);
const auto dispatchInput = reinterpret_cast<InputMessage>(0x009F97B7);
const auto inputModifiers = reinterpret_cast<InputModifiers>(0x0059B1EB);
const auto activeSkill = reinterpret_cast<ActiveSkill>(0x00966F7A);
const auto useItem = reinterpret_cast<UseItem>(0x00A092FB);

struct NativeContext {
    std::uint32_t field = 0;
    std::uint32_t stats = 0;
    std::uint32_t user = 0;
    bool loginStage = false;
};

std::string directory;
std::string instanceId;
std::string runId;
std::string commandId;
std::string commandStatus = "idle";
std::string commandReason;
std::string rejectedId;
std::string rejectedReason;
std::string lastConsumedId;
std::string pendingStatus;
std::string pendingReason;
BeiDouBridge::NativeKeyInput keyInput;
BeiDouBridge::NativeItemUse itemUse;
bool itemResult = false;
std::array<unsigned int, 256> scanCodes{};
std::array<std::uint32_t, 256> nativeScanCodes{};
std::uint32_t nativeScanCodesOwner = 0;
bool scriptCommand = false;
bool haveSkillResult = false;
std::uint32_t lastSkillId = 0;
int lastSkillResult = 0;
const MapleControl::State* currentState = nullptr;
NativeContext currentNative;
std::uint32_t updatedCharacter = 0;
std::uint64_t characterUpdates = 0;
bool haveScene = false;
MapleControl::State previousState;
std::uint64_t sceneGeneration = 1;
std::uint64_t sequence = 0;
std::uint64_t inputEvents = 0;
MapleControl::ActionResult semanticResult;
ULONGLONG lastPublishedAt = 0;

void BeginRelease(const std::string& status, const std::string& reason);
bool BeginNativeAction(const MapleControl::Action& action, std::string& error);
MapleControl::ActionResult NativeResult();
bool NativeRawKeys(const std::vector<std::string>& keys, unsigned int duration, std::string& error);
bool InvokeNativeSkill(std::uint32_t skillId, int& result, std::string& error);
bool NativeLogs(const std::string& scriptId, const std::vector<std::string>& lines);

class BeiDouAdapter final : public MapleControl::Adapter {
public:
    const char* Backend() const override { return "beidou"; }

    const MapleControl::State& Observe() const override { return previousState; }

    MapleControl::Observation ObserveDomain(const std::string& domain) const override {
        return NativeObservation::Collect(domain);
    }

    bool Supports(MapleControl::ActionKind) const override { return true; }

    bool Begin(const MapleControl::Action& action, std::string& error) override {
        return BeginNativeAction(action, error);
    }

    MapleControl::ActionResult Result() const override { return NativeResult(); }

    void Release() override { BeginRelease({}, {}); }

    bool Released() const override { return keyInput.Released() && !itemUse.Pending(); }

    bool ReleasePending() const override { return keyInput.ReleasePending(); }

    bool Logs(const std::string& scriptId, const std::vector<std::string>& lines) override {
        return NativeLogs(scriptId, lines);
    }

    bool SupportsRawKeys() const override { return true; }

    bool RawKeys(const std::vector<std::string>& keys, std::uint32_t duration, std::string& error) override {
        return NativeRawKeys(keys, duration, error);
    }

    bool SupportsSkill() const override { return true; }

    bool Skill(std::uint32_t id, int& result, std::string& error) override {
        return InvokeNativeSkill(id, result, error);
    }
};

BeiDouAdapter adapter;
MapleControl::Runtime runtime(adapter);
std::unique_ptr<MapleControl::TaskTransport> taskTransport;

template <typename T> bool ReadAt(std::uintptr_t address, T& value) {
    SIZE_T count = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(address), &value, sizeof(value), &count)
           && count == sizeof(value);
}

std::string Quote(const std::string& text) {
    std::ostringstream out;
    out << '"';
    for (unsigned char byte : text) {
        if (byte == '"' || byte == '\\')
            out << '\\' << byte;
        else if (byte < 0x20) {
            out << "\\u00" << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(byte)
                << std::dec;
        } else
            out << byte;
    }
    out << '"';
    return out.str();
}

std::string Utf8Name(const char* name, int length) {
    const int wideLength = MultiByteToWideChar(936, MB_ERR_INVALID_CHARS, name, length, nullptr, 0);
    if (wideLength == 0) return {};
    std::wstring wide(wideLength, L'\0');
    MultiByteToWideChar(936, MB_ERR_INVALID_CHARS, name, length, &wide[0], wideLength);
    const int utf8Length = WideCharToMultiByte(CP_UTF8, 0, wide.data(), wideLength, nullptr, 0, nullptr, nullptr);
    std::string result(utf8Length, '\0');
    if (utf8Length != 0)
        WideCharToMultiByte(CP_UTF8, 0, wide.data(), wideLength, &result[0], utf8Length, nullptr, nullptr);
    return result;
}

bool SecureValue(std::uintptr_t address, std::uint32_t& map) {
    std::array<unsigned char, 12> guards{};
    if (!ReadAt(address, guards)) return false;
    std::uint32_t pointer = 0;
    std::memcpy(&pointer, guards.data() + 8, sizeof(pointer));
    std::array<unsigned char, 10> encrypted{};
    if (!ReadAt(pointer, encrypted)) return false;
    unsigned char key = encrypted[4];
    std::uint16_t checksum = 0x9A65;
    map = 0;
    for (unsigned int index = 0; index < 4; ++index) {
        if (key == 0) key = 42;
        map |= static_cast<std::uint32_t>(encrypted[index] ^ key) << (index * 8);
        key = static_cast<unsigned char>(key + encrypted[index] + 42);
        checksum = static_cast<std::uint16_t>((checksum << 3) | ((checksum >> 13) + key));
    }
    std::uint16_t expected = 0;
    std::memcpy(&expected, encrypted.data() + 8, sizeof(expected));
    return guards[0] == encrypted[5] && guards[4] == encrypted[6] && checksum == expected;
}

bool SecureInteger(std::uintptr_t address, std::uint32_t& value) {
    std::array<std::uint32_t, 3> data{};
    if (!ReadAt(address, data)) return false;
    const std::uint32_t mixed = data[0] ^ 0xBAADF00D;
    const std::uint32_t checksum = data[1] + ((mixed >> 5) | (mixed << 27));
    value = data[0] ^ ((data[1] << 5) | (data[1] >> 27));
    return checksum == data[2];
}

bool CaptureMonsters(std::vector<MapleControl::Monster>& monsters) {
    std::uint32_t pool = 0;
    std::uint32_t vtable = 0;
    std::array<std::uint32_t, 3> membership{};
    if (!ReadAt(0x00BEBFA4, pool) || pool == 0 || !ReadAt(pool, vtable) || vtable != 0x00AF8378
        || !ReadAt(pool + 0x24, membership) || membership[0] > 512)
        return false;
    auto position = membership[1];
    while (position != 0 && monsters.size() < membership[0]) {
        std::uint32_t object = 0;
        std::array<std::uint32_t, 3> vtables{};
        std::array<int, 2> coordinates{};
        std::uint32_t entry = 0;
        MapleControl::Monster monster;
        std::uint32_t activeValue = 0;
        if (!ReadAt(position + 4, object) || object == 0 || !ReadAt(object, vtables)
            || vtables != std::array<std::uint32_t, 3>{0x00AF8270, 0x00AF824C, 0x00AF8248}
            || !ReadAt(object + 0x510, coordinates) || !SecureInteger(object + 0x17C, monster.objectId)
            || !SecureInteger(object + 0x124, activeValue) || !ReadAt(object + 0x188, entry))
            return false;
        monster.x = coordinates[0];
        monster.y = coordinates[1];
        monster.active = activeValue != 0;
        if (entry != 0) {
            if (!SecureInteger(entry + 0x0C, monster.templateId)) return false;
            monster.templateKnown = true;
            std::uint32_t name = 0;
            std::uint32_t nameLength = 0;
            if (ReadAt(entry + 0x30, name) && name != 0 && ReadAt(name - 4, nameLength) && nameLength > 0
                && nameLength <= 512) {
                std::array<char, 513> bytes{};
                SIZE_T read = 0;
                if (ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(name), bytes.data(),
                                      nameLength + 1, &read)
                    && read == nameLength + 1 && bytes[nameLength] == 0)
                    monster.name = Utf8Name(bytes.data(), static_cast<int>(nameLength));
            }
        }
        monsters.push_back(monster);
        std::uint32_t node = 0;
        if (!ReadAt(position - 12, node)) return false;
        position = node == 0 ? 0 : node + 16;
    }
    std::array<std::uint32_t, 3> after{};
    return position == 0 && monsters.size() == membership[0] && ReadAt(pool + 0x24, after) && after == membership;
}

bool CaptureDrops(std::vector<MapleControl::Drop>& drops) {
    std::uint32_t pool = 0;
    std::uint32_t vtable = 0;
    std::array<std::uint32_t, 3> membership{};
    if (!ReadAt(0x00BED6AC, pool) || pool == 0 || !ReadAt(pool, vtable) || vtable != 0x00AF3700
        || !ReadAt(pool + 0x28, membership) || membership[0] > 512)
        return false;
    auto position = membership[1];
    while (position != 0 && drops.size() < membership[0]) {
        std::uint32_t object = 0;
        std::uint32_t money = 0;
        std::uint32_t value = 0;
        std::uint32_t landed = 0;
        std::uint32_t x = 0;
        std::uint32_t y = 0;
        MapleControl::Drop drop;
        if (!ReadAt(position + 4, object) || object == 0 || !ReadAt(object + 0x20, drop.objectId)
            || !ReadAt(object + 0x30, money) || !ReadAt(object + 0x34, value) || !ReadAt(object + 0x48, landed)
            || !SecureValue(object + 0x74, x) || !SecureValue(object + 0x68, y))
            return false;
        drop.x = static_cast<std::int32_t>(x);
        drop.y = static_cast<std::int32_t>(y);
        drop.itemKnown = money == 0;
        drop.itemId = money == 0 ? value : 0;
        drop.moneyKnown = money != 0;
        drop.money = money != 0 ? value : 0;
        drop.landed = landed == 3 ? MapleControl::Fact::True : MapleControl::Fact::False;
        drops.push_back(drop);
        std::uint32_t node = 0;
        if (!ReadAt(position - 12, node)) return false;
        position = node == 0 ? 0 : node + 16;
    }
    std::array<std::uint32_t, 3> after{};
    return position == 0 && drops.size() == membership[0] && ReadAt(pool + 0x28, after) && after == membership;
}

bool CaptureInventory(std::uint32_t stats, std::vector<MapleControl::Item>& inventory) {
    for (int type = 1; type <= 5; ++type) {
        std::uint32_t array = 0;
        std::uint32_t length = 0;
        if (!ReadAt(stats + 0x447 + type * 4, array) || array == 0 || !ReadAt(array - 4, length) || length == 0
            || length > 257)
            return false;
        for (std::uint32_t slot = 1; slot < length; ++slot) {
            std::uint32_t object = 0;
            if (!ReadAt(array + slot * 8 + 4, object)) return false;
            if (object == 0) continue;
            std::uint32_t vtable = 0;
            MapleControl::Item item;
            item.inventoryType = type;
            item.slot = static_cast<int>(slot);
            if (!ReadAt(object, vtable) || (vtable != 0x00AF310C && vtable != 0x00AF318C && vtable != 0x00AF3204)
                || !SecureValue(object + 0x0C, item.itemId))
                return false;
            if (vtable == 0x00AF310C) {
                item.quantity = 1;
                item.quantityKnown = true;
            } else if (vtable == 0x00AF318C) {
                std::array<unsigned char, 8> data{};
                if (!ReadAt(object + 0x28, data)) return false;
                std::uint32_t checksum = 0xBAADF00D;
                for (unsigned int index = 0; index < 2; ++index) {
                    const auto mixed = data[index] ^ checksum;
                    checksum = data[index + 2] + ((mixed >> 5) | (mixed << 27));
                }
                std::uint32_t expected = 0;
                std::memcpy(&expected, data.data() + 4, sizeof(expected));
                if (checksum != expected) return false;
                item.quantity = (data[0] ^ data[2]) | ((data[1] ^ data[3]) << 8);
                item.quantityKnown = true;
            }
            inventory.push_back(item);
        }
    }
    return true;
}

std::uint64_t UnixMilliseconds() {
    FILETIME fileTime{};
    GetSystemTimeAsFileTime(&fileTime);
    const auto ticks = (static_cast<std::uint64_t>(fileTime.dwHighDateTime) << 32) | fileTime.dwLowDateTime;
    return (ticks - 116444736000000000ULL) / 10000;
}

bool BindingKey(std::uint32_t id, unsigned int& key, std::string& error) {
    std::uint32_t mapped = 0;
    std::uint32_t input = 0;
    std::uint32_t vtable = 0;
    std::array<unsigned char, 89 * 5> table{};
    if (!ReadAt(0x00BED5A0, mapped) || mapped == 0 || !ReadAt(mapped, vtable) || vtable != 0x00AF5650
        || !ReadAt(mapped + 4, table) || !ReadAt(0x00BEC33C, input) || input == 0) {
        error = "native_binding_unavailable";
        return false;
    }
    for (unsigned int index = 0; index < 89; ++index) {
        std::uint32_t actionId = 0;
        std::memcpy(&actionId, table.data() + index * 5 + 1, sizeof(actionId));
        if (table[index * 5] != 5 || actionId != id) continue;
        // Extended navigation keys share the low seven DIK bits used by CFuncKeyMappedMan.
        unsigned int scan = index;
        if (index == 71 || index == 72 || index == 73 || index == 75 || index == 77 || index == 79 || index == 80
            || index == 81 || index == 82 || index == 83)
            scan |= 0x80;
        if (!ReadAt(input + 0x424 + scan * 4, key) || key == 0 || key > 255) continue;
        return true;
    }
    error = "unsupported: native_action_not_bound";
    return false;
}

MapleControl::State CaptureState(NativeContext& native) {
    MapleControl::State state;
    ReadAt(0x00BEDED4, native.field);
    std::uint32_t stageType = 0;
    native.loginStage = native.field != 0 && ReadAt(native.field, stageType) && stageType == 0x00AF6B24;
    if (native.field != 0) state.mapKnown = SecureValue(native.field + 0x138, state.mapId);
    std::uint32_t context = 0;
    if (ReadAt(0x00BE7918, context) && context != 0 && ReadAt(context + 0x20B8, native.stats) && native.stats != 0) {
        std::array<unsigned char, 0x100> data{};
        if (ReadAt(native.stats, data)) {
            std::memcpy(&state.character.id, data.data(), sizeof(state.character.id));
            int nameLength = 0;
            while (nameLength < 13 && data[4 + nameLength] != 0) ++nameLength;
            state.character.name = Utf8Name(reinterpret_cast<const char*>(data.data() + 4), nameLength);
            const std::array<unsigned int, 13> offsets{0x33, 0x39, 0x41, 0x49, 0x51, 0x59, 0x61,
                                                       0x69, 0x71, 0x79, 0x81, 0x89, 0x91};
            state.characterKnown = true;
            for (unsigned int field = 0; field < offsets.size(); ++field) {
                const unsigned int size = field == 0 ? 1 : field == 12 ? 4 : 2;
                const unsigned int offset = offsets[field];
                std::uint32_t checksum = 0xBAADF00D;
                std::uint32_t value = 0;
                if (size == 4) {
                    std::uint32_t key = 0;
                    std::uint32_t encrypted = 0;
                    std::memcpy(&key, data.data() + offset, sizeof(key));
                    std::memcpy(&encrypted, data.data() + offset + 4, sizeof(encrypted));
                    value = key ^ ((encrypted << 5) | (encrypted >> 27));
                    const std::uint32_t mixed = key ^ checksum;
                    checksum = encrypted + ((mixed >> 5) | (mixed << 27));
                } else
                    for (unsigned int index = 0; index < size; ++index) {
                        const unsigned char key = data[offset + index];
                        const unsigned char encrypted = data[offset + size + index];
                        const std::uint32_t mixed = key ^ checksum;
                        checksum = encrypted + ((mixed >> 5) | (mixed << 27));
                        value |= static_cast<std::uint32_t>(key ^ encrypted) << (index * 8);
                    }
                std::uint32_t expected = 0;
                std::memcpy(&expected, data.data() + offset + size * 2, sizeof(expected));
                if (checksum != expected) state.characterKnown = false;
                state.character.values[field] = value;
            }
        }
    }
    if (ReadAt(0x00BEBF98, native.user) && native.user != 0) {
        std::array<std::uint32_t, 2> vtables{};
        std::array<int, 2> position{};
        state.positionKnown = ReadAt(native.user, vtables) && vtables[0] == 0x00B3D20C && vtables[1] == 0x00B3D1E8
                              && ReadAt(native.user + 0x116C, position);
        if (state.positionKnown) {
            state.x = position[0];
            state.y = position[1];
            std::uint32_t facing = 0;
            state.facingKnown = ReadAt(native.user + 0x570, facing);
            state.facingLeft = (facing & 1) != 0;
        }
    }
    if (state.mapKnown) {
        state.monstersKnown = CaptureMonsters(state.monsters);
        if (!state.monstersKnown) state.monsters.clear();
    }
    if (state.characterKnown) {
        state.inventoryKnown = CaptureInventory(native.stats, state.inventory);
        if (!state.inventoryKnown) state.inventory.clear();
    }
    state.character.known.fill(state.characterKnown);
    state.inGame = !native.loginStage && !(native.field == 0 && native.stats == 0 && native.user == 0);
    state.ready = state.inGame && state.mapKnown && state.characterKnown && state.positionKnown;
    if (state.mapKnown) {
        state.dropsKnown = CaptureDrops(state.drops);
        if (!state.dropsKnown) state.drops.clear();
    }
    return state;
}

unsigned int __fastcall KeyPressedHook(InputSystem* input, void*, int key) {
    const auto& owned = keyInput.Owned();
    const auto& held = keyInput.Held();
    if (key >= 0 && key < 256 && owned[key]) return held[key] ? 1 : 0;
    // The native input system exposes both side-specific and aggregate modifier keys.
    if (key == VK_SHIFT && (owned[VK_LSHIFT] || owned[VK_RSHIFT]))
        return held[VK_LSHIFT] || held[VK_RSHIFT] || originalKeyPressed(input, key);
    if (key == VK_CONTROL && (owned[VK_LCONTROL] || owned[VK_RCONTROL]))
        return held[VK_LCONTROL] || held[VK_RCONTROL] || originalKeyPressed(input, key);
    if (key == VK_MENU && (owned[VK_LMENU] || owned[VK_RMENU]))
        return held[VK_LMENU] || held[VK_RMENU] || originalKeyPressed(input, key);
    return originalKeyPressed(input, key);
}

bool SendKey(unsigned int key, bool down, std::uint64_t epoch) {
    std::uint32_t windowManager = 0;
    std::uint32_t input = 0;
    if (!ReadAt(0x00BEC20C, windowManager) || windowManager == 0 || !ReadAt(0x00BEC33C, input) || input == 0)
        return false;
    unsigned int flags = ((scanCodes[key] & 0x7F) | ((scanCodes[key] & 0x80) << 1)) << 16;
    // 0x59B1EB's low flags encode modifiers, not a Win32 repeat count.
    flags |= inputModifiers(reinterpret_cast<InputSystem*>(input));
    if (!down) flags |= 0x80000000;
    // Native keyboard polling emits the aggregate VK and retains the side in DIK/flags.
    const unsigned int messageKey = key == VK_LSHIFT || key == VK_RSHIFT       ? VK_SHIFT
                                    : key == VK_LCONTROL || key == VK_RCONTROL ? VK_CONTROL
                                    : key == VK_LMENU || key == VK_RMENU       ? VK_MENU
                                                                               : key;
    if (down && epoch != keyInput.Epoch()) return true;
    keyInput.MarkDispatched(epoch);
    ++inputEvents;
    dispatchInput(0x100, messageKey, flags);
    return true;
}

void BeginRelease(const std::string& status, const std::string& reason) {
    itemUse.Cancel();
    keyInput.Release();
    pendingStatus = status;
    pendingReason = reason;
}

bool ApplyDesiredKeys(const std::vector<unsigned int>& keys, unsigned int durationMs, std::string& error) {
    std::array<bool, 256> desired{};
    if (keys.empty()) {
        pendingStatus.clear();
        pendingReason.clear();
        keyInput.Request(desired, durationMs, currentNative.user, GetTickCount64());
        return true;
    }
    if (!currentState->mapKnown || !currentState->characterKnown || !currentState->positionKnown
        || currentState->character.values[6] == 0) {
        error = "state_unavailable_or_dead";
        return false;
    }
    std::uint32_t input = 0;
    if (!ReadAt(0x00BEC33C, input) || input == 0) {
        error = "input_route_unavailable";
        return false;
    }
    if (nativeScanCodesOwner != input) {
        if (!ReadAt(input + 0x24, nativeScanCodes)) {
            error = "input_key_map_unavailable";
            return false;
        }
        nativeScanCodesOwner = input;
    }
    for (unsigned int key : keys) {
        if (key == 0 || key > 255 || nativeScanCodes[key] == 0 || nativeScanCodes[key] > 255) {
            error = "unsupported_native_key";
            return false;
        }
        desired[key] = true;
        scanCodes[key] = nativeScanCodes[key];
    }
    // A nonblocking Lua keys update replaces the desired set without flickering unchanged keys.
    pendingStatus.clear();
    pendingReason.clear();
    keyInput.Request(desired, durationMs, currentNative.user, GetTickCount64());
    return true;
}

bool Publish(const MapleControl::State& state) {
    const bool ready = state.ready;
    std::ostringstream out;
    out << "{\"protocol\":1,\"instance_id\":" << Quote(instanceId) << ",\"pid\":" << GetCurrentProcessId()
        << ",\"run_id\":" << Quote(runId) << ",\"seq\":" << state.sequence
        << ",\"observed_at_ms\":" << state.observedAtMs << ",\"scene_generation\":" << sceneGeneration
        << ",\"ready\":" << (ready ? "true" : "false") << ",\"map_id\":";
    if (state.mapKnown)
        out << state.mapId;
    else
        out << "null";
    out << ",\"character\":";
    if (state.characterKnown) {
        out << "{\"id\":" << state.character.id << ",\"name\":" << Quote(state.character.name);
        const std::array<const char*, 13> names{
            "level",  "job", "strength", "dexterity",      "intelligence", "luck",      "hp",
            "max_hp", "mp",  "max_mp",   "ability_points", "skill_points", "experience"};
        for (unsigned int index = 0; index < names.size(); ++index) {
            out << ',' << Quote(names[index]) << ':';
            if (state.character.known[index])
                out << state.character.values[index];
            else
                out << "null";
        }
        out << '}';
    } else
        out << "null";
    out << ",\"position\":";
    if (state.positionKnown)
        out << "{\"x\":" << state.x << ",\"y\":" << state.y << '}';
    else
        out << "null";
    out << ",\"facing\":";
    if (state.facingKnown)
        out << Quote(state.facingLeft ? "Left" : "Right");
    else
        out << "null";
    out << ",\"monsters\":";
    if (state.monstersKnown) {
        out << '[';
        bool separator = false;
        for (const auto& monster : state.monsters) {
            if (separator) out << ',';
            separator = true;
            out << "{\"object_id\":" << monster.objectId << ",\"template_id\":";
            if (monster.templateKnown)
                out << monster.templateId;
            else
                out << "null";
            out << ",\"name\":" << (monster.name.empty() ? "null" : Quote(monster.name)) << ",\"x\":" << monster.x
                << ",\"y\":" << monster.y << ",\"active\":" << (monster.active ? "true" : "false") << '}';
        }
        out << ']';
    } else
        out << "null";
    out << ",\"backend\":\"beidou\",\"capabilities\":{\"move\":true,\"face\":true,\"jump\":true,\"attack\":true,\"pickup\":true,\"use_item\":true,\"stop\":true,\"raw_keys\":true,\"skill\":true},\"inventory\":";
    if (state.inventoryKnown) {
        out << '[';
        bool separator = false;
        for (const auto& item : state.inventory) {
            if (separator) out << ',';
            separator = true;
            out << "{\"inventory_type\":" << item.inventoryType << ",\"slot\":" << item.slot
                << ",\"item_id\":" << item.itemId << ",\"quantity\":";
            if (item.quantityKnown)
                out << item.quantity;
            else
                out << "null";
            out << '}';
        }
        out << ']';
    } else
        out << "null";
    out << ",\"drops\":";
    if (state.dropsKnown) {
        out << '[';
        bool separator = false;
        for (const auto& drop : state.drops) {
            if (separator) out << ',';
            separator = true;
            out << "{\"object_id\":" << drop.objectId << ",\"x\":" << drop.x << ",\"y\":" << drop.y << ",\"item_id\":";
            if (drop.itemKnown)
                out << drop.itemId;
            else
                out << "null";
            out << ",\"money\":";
            if (drop.moneyKnown)
                out << drop.money;
            else
                out << "null";
            out << ",\"landed\":";
            if (drop.landed == MapleControl::Fact::Unknown)
                out << "null";
            else
                out << (drop.landed == MapleControl::Fact::True ? "true" : "false");
            out << '}';
        }
        out << ']';
    } else
        out << "null";
    out << ",\"held_keys\":[";
    bool separator = false;
    const auto& held = keyInput.Held();
    for (unsigned int key = 0; key < held.size(); ++key)
        if (held[key]) {
            if (separator) out << ',';
            out << key;
            separator = true;
        }
    out << "],\"command\":{\"id\":" << (commandId.empty() ? "null" : Quote(commandId))
        << ",\"status\":" << Quote(commandStatus)
        << ",\"reason\":" << (commandReason.empty() ? "null" : Quote(commandReason)) << "},\"rejected_command\":";
    if (rejectedReason.empty())
        out << "null";
    else
        out << "{\"id\":" << (rejectedId.empty() ? "null" : Quote(rejectedId))
            << ",\"status\":\"rejected\",\"reason\":" << Quote(rejectedReason) << '}';
    out << ",\"script\":";
    const auto* script = runtime.CurrentStatus();
    if (script == nullptr)
        out << "null";
    else {
        out << "{\"id\":" << Quote(script->id) << ",\"status\":" << Quote(script->status)
            << ",\"reason\":" << (script->reason.empty() ? "null" : Quote(script->reason))
            << ",\"error\":" << (script->error.empty() ? "null" : Quote(script->error))
            << ",\"resumes\":" << script->resumes << ",\"budget_yields\":" << script->budgetYields
            << ",\"last_resume_us\":" << script->lastResumeUs << ",\"max_resume_us\":" << script->maxResumeUs
            << ",\"tasks\":[";
        bool taskSeparator = false;
        for (const auto& task : script->tasks) {
            if (taskSeparator) out << ',';
            out << "{\"name\":" << Quote(task.name) << ",\"revision\":" << task.revision
                << ",\"priority\":" << task.priority << ",\"status\":" << Quote(task.status)
                << ",\"wait\":" << Quote(task.wait)
                << ",\"reason\":" << (task.reason.empty() ? "null" : Quote(task.reason))
                << ",\"error\":" << (task.error.empty() ? "null" : Quote(task.error)) << '}';
            taskSeparator = true;
        }
        const auto& control = script->control;
        out << "],\"control\":{\"owner\":" << (control.owner.empty() ? "null" : Quote(control.owner))
            << ",\"pending\":" << (control.pending.empty() ? "null" : Quote(control.pending))
            << ",\"from\":" << (control.from.empty() ? "null" : Quote(control.from))
            << ",\"to\":" << (control.to.empty() ? "null" : Quote(control.to))
            << ",\"reason\":" << (control.reason.empty() ? "null" : Quote(control.reason)) << "}}";
    }
    out << ",\"last_skill\":";
    if (haveSkillResult)
        out << "{\"skill_id\":" << lastSkillId << ",\"native_result\":" << lastSkillResult << '}';
    else
        out << "null";
    const auto actionResult = NativeResult();
    out << ",\"action_result\":{\"dispatched\":" << (actionResult.dispatched ? "true" : "false")
        << ",\"control_released\":" << (actionResult.controlReleased ? "true" : "false") << ",\"settled\":";
    if (actionResult.settled == MapleControl::Fact::Unknown)
        out << "null";
    else
        out << (actionResult.settled == MapleControl::Fact::True ? "true" : "false");
    out << ",\"effect\":" << Quote(actionResult.effect) << ",\"reason\":" << Quote(actionResult.reason) << '}';
    out << ",\"input_events\":" << inputEvents << "}\n";
    const std::string bytes = out.str();
    const std::string temporary = directory + "\\state.tmp";
    const HANDLE file =
        CreateFileA(temporary.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    const bool complete =
        WriteFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr) && written == bytes.size();
    const bool closed = CloseHandle(file) != FALSE;
    return complete && closed
           && MoveFileExA(temporary.c_str(), (directory + "\\state.json").c_str(),
                          MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}

void ReadCommand() {
    std::ifstream input(directory + "\\command.txt");
    if (!input) return;
    std::string line;
    std::getline(input, line);
    input.close();
    DeleteFileA((directory + "\\command.txt").c_str());
    std::istringstream stream(line);
    unsigned int protocol = 0;
    std::uint64_t generation = 0;
    std::uint64_t value = 0;
    std::string targetInstance, id, operation, scriptId, extra;
    const bool header =
        line.size() <= 1024
        && static_cast<bool>(stream >> protocol >> targetInstance >> generation >> id >> operation >> value);
    if (!header) {
        rejectedId = id;
        rejectedReason = "invalid_command";
        return;
    }
    if (id == lastConsumedId) return;
    lastConsumedId = id;
    rejectedId.clear();
    rejectedReason.clear();
    bool valid = protocol == 1 && targetInstance == instanceId && !id.empty() && id.size() <= 64
                 && id.find_first_not_of("0123456789abcdefABCDEF-") == std::string::npos;
    if (operation == "script") {
        stream >> scriptId;
        valid = valid && generation == sceneGeneration && value <= 0xffffffffULL && scriptId.size() == 32
                && scriptId.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos && !(stream >> extra)
                && previousState.ready && previousState.character.values[6] > 0;
    } else
        valid = valid && operation == "stop" && value == 0 && !(stream >> extra);
    const bool busy = operation != "stop" && (runtime.Running() || !adapter.Released());
    if (!valid || busy) {
        rejectedId = id;
        rejectedReason = busy ? "busy" : "invalid_or_stale_command";
        if (!runtime.Running() && adapter.Released()) {
            commandId = id;
            commandStatus = "rejected";
            commandReason = rejectedReason;
        }
        return;
    }
    commandId = id;
    commandStatus = "running";
    commandReason.clear();
    if (operation == "stop") {
        runtime.Cancel("stopped");
        scriptCommand = false;
        BeginRelease("completed", "stopped");
        return;
    }
    std::ifstream sourceFile(directory + "\\scripts\\" + scriptId + ".lua", std::ios::binary);
    std::string source;
    bool sourceValid = false;
    if (sourceFile) {
        sourceFile.seekg(0, std::ios::end);
        const auto length = sourceFile.tellg();
        if (length >= 0 && length <= 1024 * 1024) {
            source.resize(static_cast<std::size_t>(length));
            sourceFile.seekg(0);
            sourceFile.read(&source[0], static_cast<std::streamsize>(source.size()));
            sourceValid = static_cast<bool>(sourceFile);
        }
    }
    std::string error;
    if (!sourceValid || !runtime.Start(scriptId, source, static_cast<std::uint32_t>(value), error)) {
        scriptCommand = false;
        commandStatus = "rejected";
        commandReason = error.empty() ? "script_file_unavailable" : "script_load_error";
    } else
        scriptCommand = true;
}

void Tick() {
    const ULONGLONG now = GetTickCount64();
    NativeContext native;
    MapleControl::State state = CaptureState(native);
    const bool changed =
        haveScene
        && (native.field != currentNative.field || native.stats != currentNative.stats
            || state.mapKnown != previousState.mapKnown || (state.mapKnown && state.mapId != previousState.mapId)
            || (state.characterKnown && state.character.id != previousState.character.id));
    if (changed) ++sceneGeneration;
    state.instanceId = instanceId;
    state.sequence = ++sequence;
    state.observedAtMs = UnixMilliseconds();
    state.sceneGeneration = sceneGeneration;
    currentNative = native;
    previousState = std::move(state);
    currentState = &previousState;
    haveScene = true;

    // CallUpdate may return without advancing its 30ms character step. Confirm the actual consumer.
    const bool oldCharacterExited =
        native.loginStage || (native.field == 0 && native.stats == 0 && native.user == 0)
        || (previousState.characterKnown && previousState.positionKnown && native.user != keyInput.ReleaseCharacter());
    if (keyInput.ConfirmRelease(updatedCharacter, characterUpdates, oldCharacterExited)) {
        if (!pendingStatus.empty()) {
            commandStatus = pendingStatus;
            commandReason = pendingReason;
        }
        pendingStatus.clear();
        pendingReason.clear();
    }
    const bool ready = previousState.ready;
    if (keyInput.Active()
        && (changed || !ready || previousState.character.values[6] == 0 || now >= keyInput.Deadline()))
        BeginRelease({}, {});

    ReadCommand();
    runtime.Tick(changed);
    if (!taskTransport->Tick(runtime, previousState)) runtime.Cancel("task_result_write_failed");
    if (scriptCommand && !runtime.Running()) {
        const auto* script = runtime.CurrentStatus();
        commandStatus = script->status;
        commandReason = script->reason;
        scriptCommand = false;
    }
    NativeObservation::Tick(directory, instanceId, runId, sceneGeneration, sequence);
    if (now - lastPublishedAt >= 25) {
        if (!Publish(previousState)) {
            if (runtime.Running())
                runtime.Cancel("state_publish_failed");
            else if (keyInput.Active() || itemUse.Pending())
                BeginRelease({}, {});
        }
        lastPublishedAt = now;
    }
    if (itemUse.Pending()) {
        std::uint32_t context = 0;
        if (!ReadAt(0x00BE7918, context)) context = 0;
        const auto consumed = itemUse.Consume(
            previousState.characterKnown ? previousState.character.id : 0, sceneGeneration, context,
            [](const BeiDouBridge::NativeItemUse::Item& item) {
                useItem(reinterpret_cast<ClientContext*>(item.context), item.slot, static_cast<int>(item.itemId));
            });
        if (consumed == BeiDouBridge::NativeItemUse::Consumption::ContextChanged) {
            semanticResult.reason = "item_context_changed";
            runtime.Cancel("item_context_changed");
        }
        return;
    }
    // Native delivery may remain in a UI message loop. Lua and management have
    // already returned, and a superseded delivery frame has no old tail work.
    if (keyInput.Active() && GetTickCount64() >= keyInput.Deadline()) BeginRelease({}, {});
    const auto delivered = keyInput.Flush(SendKey, [] { return characterUpdates; });
    if (delivered.failed && delivered.epoch == keyInput.Epoch()) {
        semanticResult.reason = "input_route_unavailable";
        runtime.Cancel("native_input_failed");
        commandReason = "native_input_failed";
        pendingReason = "native_input_failed";
        BeginRelease(pendingStatus, pendingReason);
    }
}

void __fastcall UpdateHook(ClientApplication* app, void*, int now) {
    originalUpdate(app, now);
    Tick();
}
}

bool AgentBridge::Install() {
    std::array<char, MAX_PATH> path{};
    const DWORD length = GetEnvironmentVariableA("MAPLE_BRIDGE_DIR", path.data(), static_cast<DWORD>(path.size()));
    if (length == 0) return true;
    if (length >= path.size()) return false;
    directory.assign(path.data(), length);
    if (!CreateDirectoryA(directory.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return false;
    std::array<char, 128> run{};
    const DWORD runLength = GetEnvironmentVariableA("RUN_ID", run.data(), static_cast<DWORD>(run.size()));
    if (runLength < run.size()) runId.assign(run.data(), runLength);
    taskTransport.reset(new MapleControl::TaskTransport(directory, runId));
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) return false;
    std::ostringstream identity;
    identity << GetCurrentProcessId() << '-' << std::hex << created.dwHighDateTime << '-' << created.dwLowDateTime;
    instanceId = identity.str();
    if (!Memory::SetHook(true, reinterpret_cast<void**>(&originalKeyPressed), KeyPressedHook)) return false;
    if (!Memory::SetHook(true, reinterpret_cast<void**>(&originalUpdate), UpdateHook)) {
        Memory::SetHook(false, reinterpret_cast<void**>(&originalKeyPressed), KeyPressedHook);
        return false;
    }
    return true;
}

namespace {
bool BeginNativeAction(const MapleControl::Action& action, std::string& error) {
    semanticResult = MapleControl::ActionResult{};
    if (action.kind == MapleControl::ActionKind::Stop) {
        semanticResult.reason = "stop_requested";
        BeginRelease({}, {});
        return true;
    }
    itemResult = false;
    if (!currentState->ready || currentState->character.values[6] == 0) {
        error = "state_unavailable_or_dead";
        return false;
    }
    if (!adapter.Released()) {
        error = "action_in_progress";
        return false;
    }
    unsigned int key = 0;
    unsigned int duration = action.durationMs == 0 ? 60 : action.durationMs;
    switch (action.kind) {
    case MapleControl::ActionKind::Move:
    case MapleControl::ActionKind::Face:
        if (action.direction == "left")
            key = VK_LEFT;
        else if (action.direction == "right")
            key = VK_RIGHT;
        else if (action.direction == "up" && action.kind == MapleControl::ActionKind::Move)
            key = VK_UP;
        else if (action.direction == "down" && action.kind == MapleControl::ActionKind::Move)
            key = VK_DOWN;
        else {
            error = "unsupported: direction";
            return false;
        }
        if (action.kind == MapleControl::ActionKind::Face) {
            if (currentState->facingKnown && currentState->facingLeft == (key == VK_LEFT)) {
                semanticResult.reason = "already_facing";
                BeginRelease({}, {});
                return true;
            }
            duration = 30;
        }
        break;
    case MapleControl::ActionKind::Jump:
        if (!BindingKey(53, key, error)) return false;
        break;
    case MapleControl::ActionKind::Attack:
        if (!BindingKey(52, key, error)) return false;
        break;
    case MapleControl::ActionKind::Pickup:
        if (!BindingKey(50, key, error)) return false;
        break;
    case MapleControl::ActionKind::UseItem: {
        if (action.itemId / 10000 != 200) {
            error = "unsupported: ordinary HP/MP potion required";
            return false;
        }
        if (!currentState->inventoryKnown) {
            error = "inventory_unavailable";
            return false;
        }
        int slot = 0;
        bool quantityUnknown = false;
        for (const auto& item : currentState->inventory) {
            if (item.inventoryType != 2 || item.itemId != action.itemId) continue;
            if (!item.quantityKnown) {
                quantityUnknown = true;
                continue;
            }
            if (item.quantity > 0) {
                slot = item.slot;
                break;
            }
        }
        if (slot == 0) {
            error = quantityUnknown ? "inventory_unavailable" : "item_not_in_inventory";
            return false;
        }
        std::uint32_t context = 0;
        if (!ReadAt(0x00BE7918, context) || context == 0) {
            error = "native_context_unavailable";
            return false;
        }
        itemUse.Request({currentState->character.id, currentState->sceneGeneration, context, slot, action.itemId});
        itemResult = true;
        semanticResult.reason = "item_use_requested";
        return true;
    }
    case MapleControl::ActionKind::Stop:
        break;
    }
    if (!ApplyDesiredKeys({key}, duration, error)) return false;
    semanticResult.reason = "native_action_requested";
    return true;
}

MapleControl::ActionResult NativeResult() {
    auto result = semanticResult;
    result.dispatched = itemResult ? itemUse.Dispatched() : keyInput.Dispatched() && result.reason != "already_facing";
    result.controlReleased = adapter.Released();
    if (result.dispatched && result.reason == "native_action_requested") result.reason = "native_action_dispatched";
    if (result.dispatched && result.reason == "native_keys_requested") result.reason = "native_keys_dispatched";
    return result;
}

bool NativeRawKeys(const std::vector<std::string>& names, unsigned int duration, std::string& error) {
    struct NamedKey {
        const char* name;
        unsigned int code;
    };

    static const NamedKey named[]{{"Left", VK_LEFT},
                                  {"Right", VK_RIGHT},
                                  {"Up", VK_UP},
                                  {"Down", VK_DOWN},
                                  {"Control_L", VK_LCONTROL},
                                  {"Control_R", VK_RCONTROL},
                                  {"Ctrl", VK_LCONTROL},
                                  {"Control", VK_LCONTROL},
                                  {"Alt_L", VK_LMENU},
                                  {"Alt_R", VK_RMENU},
                                  {"Alt", VK_LMENU},
                                  {"Shift_L", VK_LSHIFT},
                                  {"Shift_R", VK_RSHIFT},
                                  {"Shift", VK_LSHIFT},
                                  {"space", VK_SPACE},
                                  {"Return", VK_RETURN},
                                  {"Escape", VK_ESCAPE},
                                  {"Tab", VK_TAB},
                                  {"Home", VK_HOME},
                                  {"End", VK_END},
                                  {"Prior", VK_PRIOR},
                                  {"Next", VK_NEXT},
                                  {"Insert", VK_INSERT},
                                  {"Delete", VK_DELETE},
                                  {"BackSpace", VK_BACK}};
    std::vector<unsigned int> keys;
    for (const auto& name : names) {
        unsigned int key = 0;
        for (const auto& entry : named)
            if (name == entry.name) {
                key = entry.code;
                break;
            }
        if (key == 0 && name.size() == 1) {
            if (name[0] >= 'a' && name[0] <= 'z')
                key = name[0] - 'a' + 'A';
            else if ((name[0] >= 'A' && name[0] <= 'Z') || (name[0] >= '0' && name[0] <= '9'))
                key = name[0];
        }
        if (key == 0 && name.size() >= 2 && name.size() <= 3 && name[0] == 'F' && name[1] >= '1' && name[1] <= '9') {
            unsigned int number = name[1] - '0';
            if (name.size() == 3) {
                if (name[2] < '0' || name[2] > '9') {
                    error = "unsupported: raw_key";
                    return false;
                }
                number = number * 10 + name[2] - '0';
            }
            if (number <= 12) key = VK_F1 + number - 1;
        }
        if (key == 0) {
            error = "unsupported: raw_key";
            return false;
        }
        keys.push_back(key);
    }
    if (!ApplyDesiredKeys(keys, duration, error)) return false;
    itemResult = false;
    semanticResult = MapleControl::ActionResult{};
    semanticResult.reason = "native_keys_requested";
    return true;
}

bool InvokeNativeSkill(std::uint32_t skillId, int& result, std::string& error) {
    if (!currentState->mapKnown || !currentState->characterKnown || !currentState->positionKnown
        || currentState->character.values[6] == 0) {
        error = "state_unavailable_or_dead";
        return false;
    }
    std::uint32_t player = 0;
    if (!ReadAt(0x00BEBF98, player) || player != currentNative.user) {
        error = "character_changed";
        return false;
    }
    result = activeSkill(reinterpret_cast<ClientPlayer*>(player), static_cast<int>(skillId), 0, nullptr);
    haveSkillResult = true;
    lastSkillId = skillId;
    lastSkillResult = result;
    return true;
}

bool NativeLogs(const std::string& scriptId, const std::vector<std::string>& lines) {
    std::ostringstream records;
    for (const auto& line : lines)
        records << "{\"script_id\":" << Quote(scriptId) << ",\"at_ms\":" << GetTickCount64()
                << ",\"text\":" << Quote(line) << "}\n";
    const std::string bytes = records.str();
    const HANDLE file =
        CreateFileA((directory + "\\script-events.jsonl").c_str(), FILE_APPEND_DATA,
                    FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        return false;
    }
    DWORD written = 0;
    const bool complete =
        WriteFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr) && written == bytes.size();
    CloseHandle(file);
    return complete;
}
}

void AgentBridge::CharacterUpdated(std::uintptr_t player) {
    std::uint32_t current = 0;
    if (ReadAt(0x00BEBF98, current) && current == player) {
        updatedCharacter = current;
        ++characterUpdates;
    }
}
