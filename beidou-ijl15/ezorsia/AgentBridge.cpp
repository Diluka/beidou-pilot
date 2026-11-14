#include "stdafx.h"
#include "AgentBridge.h"
#include "Contract.h"
#include "TickRuntime.h"
#include "NativeKeyUnion.h"
#include "NativeTickInput.h"
#include "EventTransport.h"
#include "NativeKeyBindings.h"
#include "NativeItemUse.h"
#include "NativeObservation.h"
#include "NativeMotion.h"
#include "NativeSceneTerrain.h"
#include "LoginAction.h"

#include <array>
#include <algorithm>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <fstream>
#include <limits>
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
std::string sceneDataRoot;
std::string instanceId;
std::string runId;
std::string commandId;
std::string commandStatus = "idle";
std::string commandReason;
std::string rejectedId;
std::string rejectedReason;
std::string lastConsumedId;
std::string latestScriptId;
BeiDouBridge::NativeTickInput tickInput;
BeiDouBridge::NativeKeyUnion nativeKeys{&tickInput.movement, &tickInput.action};
bool scriptCommand = false;
bool stopCommand = false;
std::string commandScriptId;
const MapleControl::State* currentState = nullptr;
NativeContext currentNative;
std::uint32_t updatedCharacter = 0;
std::uint64_t characterUpdates = 0;
bool haveScene = false;
MapleControl::State previousState;
std::uint64_t sceneGeneration = 1;
std::uint64_t sequence = 0;
std::uint64_t inputEvents = 0;
std::array<unsigned int, 256> scanCodes{};
std::array<std::uint32_t, 256> nativeScanCodes{};
std::uint32_t nativeScanCodesOwner = 0;
ULONGLONG lastPublishedAt = 0;
bool eventsPublished = false;

bool InvokeNativeSkill(std::uint32_t skillId, int& result, std::string& error);
bool NativeLogs(const std::string& scriptId, const std::vector<std::string>& lines);
bool RequestNativeItem(std::uint32_t itemId, BeiDouBridge::NativeItemUse& target, std::string& error);
const MapleControl::Value& Member(const MapleControl::Value& object, const std::string& name);

class BeiDouTickAdapter final : public MapleControl::TickAdapter {
public:
    const MapleControl::State& Observe() const override { return previousState; }

    MapleControl::Observation ObserveDomain(const std::string& domain) const override {
        if (domain == "terrain") return BeiDouBridge::ObserveSceneTerrain(previousState, sceneDataRoot);
        auto observation = NativeObservation::Collect(domain);
        if (domain == "character") {
            // CharacterData's verified maps are learned skill levels, not active
            // TemporaryStat/buff records. Do not infer buffs from those maps.
            observation.data["buffs"] = MapleControl::Value{};
            observation.data["buffs_status"] = "unsupported";
            observation.data["buffs_unavailable"] = "native_buff_details_unavailable";
        }
        return observation;
    }

    bool Supports(MapleControl::ActionKind kind) const override {
        return kind == MapleControl::ActionKind::Jump || kind == MapleControl::ActionKind::Attack
               || kind == MapleControl::ActionKind::Pickup || kind == MapleControl::ActionKind::UseItem;
    }

    bool SupportsSkill() const override { return true; }

    bool SetActionIntent(const MapleControl::Action& action, std::string& error) override;

    const MapleControl::Action* ActiveAction() const override { return tickInput.ActiveAction(); }

    bool ActionIntentSettled() const override { return tickInput.ActionIntentSettled(); }

    bool SetHeldKeys(const std::vector<std::string>& keys, std::string& error) override;

    bool HeldKeysSettled() const override { return tickInput.HeldKeysSettled(); }

    MapleControl::ActionResult Result() const override { return tickInput.Result(); }

    void Release() override { tickInput.Release(currentNative.user); }

    void ReleaseAction() override { tickInput.ReleaseAction(); }

    bool Released() const override { return tickInput.Released(); }

    bool ReleasePending() const override { return tickInput.ReleasePending(); }

    bool Logs(const std::string& id, const std::vector<std::string>& lines) override { return NativeLogs(id, lines); }
};

BeiDouTickAdapter tickAdapter;
MapleControl::TickRuntime tickRuntime(tickAdapter);
std::unique_ptr<MapleControl::EventTransport> eventTransport;

template <typename T> bool ReadAt(std::uintptr_t address, T& value) {
    SIZE_T count = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(address), &value, sizeof(value), &count)
           && count == sizeof(value);
}

BeiDouBridge::NativeActionState CaptureNativeAction(std::uintptr_t user) {
    return BeiDouBridge::ReadNativeActionState(
        user, [](std::uintptr_t address, std::uint32_t& value) { return ReadAt(address, value); });
}

BeiDouBridge::NativeRepeatSettings CaptureNativeRepeat() {
    std::uint32_t input = 0;
    if (!ReadAt(0x00BEC33C, input)) return {};
    return BeiDouBridge::ReadNativeRepeatSettings(
        input, [](std::uintptr_t address, std::uint32_t& value) { return ReadAt(address, value); });
}

const MapleControl::Value& Member(const MapleControl::Value& object, const std::string& name) {
    for (const auto& entry : object.Members())
        if (entry.first == name) return entry.second;
    static const MapleControl::Value unknown;
    return unknown;
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
        monster.SetPosition(coordinates[0], coordinates[1]);
        monster.velocity = NativeMotion::CaptureVelocity(NativeMotion::EntityKind::Mob, object);
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
        drop.SetPosition(static_cast<std::int32_t>(x), static_cast<std::int32_t>(y));
        drop.positionSource = MapleControl::MovableObject::PositionSource::NativeDropDestination;
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

bool BindingKey(BeiDouBridge::NativeBindingType type, std::uint32_t id, unsigned int& key, std::string& error) {
    std::uint32_t mapped = 0;
    std::uint32_t input = 0;
    std::uint32_t vtable = 0;
    std::array<unsigned char, 89 * 5> table{};
    if (!ReadAt(0x00BED5A0, mapped) || mapped == 0 || !ReadAt(mapped, vtable) || vtable != 0x00AF5650
        || !ReadAt(mapped + 4, table) || !ReadAt(0x00BEC33C, input) || input == 0) {
        error = "native_binding_unavailable";
        return false;
    }
    if (BeiDouBridge::FindNativeBinding(table, type, id, key, [input](unsigned scan, unsigned int& value) {
            return ReadAt(input + 0x424 + scan * 4, value);
        }))
        return true;
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
    if (state.positionKnown) state.character.SetPosition(state.x, state.y);
    state.characterUpdatesKnown = state.ready && updatedCharacter == native.user;
    state.characterUpdates = characterUpdates;
    if (state.ready) {
        auto motion = NativeMotion::Capture(native.user);
        state.character.velocity = std::move(motion.velocity);
        state.character.movement = std::move(motion.movement);
        state.onGround = motion.onGround;
        state.actionIdle = CaptureNativeAction(native.user).idle;
    }
    if (state.mapKnown) {
        state.dropsKnown = CaptureDrops(state.drops);
        if (!state.dropsKnown) state.drops.clear();
    }
    state.playersKnown = false;
    state.players.clear();
    state.playersComplete = MapleControl::Fact::Unknown;
    if (state.ready) {
        try {
            NativeObservation::Players(state.players);
            state.playersKnown = true;
            state.playersComplete = MapleControl::Fact::True;
        } catch (const NativeObservation::ReadError&) {
            state.players.clear();
            state.playersComplete = MapleControl::Fact::False;
        }
        try {
            NativeObservation::Npcs(state.npcs);
            state.npcsKnown = true;
        } catch (const NativeObservation::ReadError&) {
            state.npcs.clear();
        }
    }
    // The ordinary bullet display list is not a proved complete Projectile
    // motion collection. Leave projectilesKnown/Complete unknown, not empty.
    return state;
}

unsigned int __fastcall KeyPressedHook(InputSystem* input, void*, int key) {
    if (key >= 0 && key < 256 && nativeKeys.Owned(key)) return nativeKeys.Held(key) ? 1 : 0;
    // The native input system exposes both side-specific and aggregate modifier keys.
    if (key == VK_SHIFT && (nativeKeys.Owned(VK_LSHIFT) || nativeKeys.Owned(VK_RSHIFT)))
        return nativeKeys.Held(VK_LSHIFT) || nativeKeys.Held(VK_RSHIFT) || originalKeyPressed(input, key);
    if (key == VK_CONTROL && (nativeKeys.Owned(VK_LCONTROL) || nativeKeys.Owned(VK_RCONTROL)))
        return nativeKeys.Held(VK_LCONTROL) || nativeKeys.Held(VK_RCONTROL) || originalKeyPressed(input, key);
    if (key == VK_MENU && (nativeKeys.Owned(VK_LMENU) || nativeKeys.Owned(VK_RMENU)))
        return nativeKeys.Held(VK_LMENU) || nativeKeys.Held(VK_RMENU) || originalKeyPressed(input, key);
    return originalKeyPressed(input, key);
}

bool SendOwnedKey(BeiDouBridge::NativeKeyInput& source, unsigned int key, bool down, std::uint64_t epoch) {
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
    if (down && epoch != source.Epoch()) return true;
    return nativeKeys.Deliver(source, key, down, epoch, [messageKey, flags](unsigned int, bool physicalDown) {
        auto physicalFlags = flags;
        if (physicalDown)
            physicalFlags &= ~0x80000000u;
        else
            physicalFlags |= 0x80000000u;
        ++inputEvents;
        dispatchInput(0x100, messageKey, physicalFlags);
        return true;
    });
}

bool ResolveOwnedKeys(const std::vector<unsigned int>& keys, BeiDouBridge::NativeKeyInput::Mask& desired,
                      std::string& error) {
    if (keys.empty()) return true;
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
    return true;
}

bool ApplyOwnedKeys(BeiDouBridge::NativeKeyInput& target, const std::vector<unsigned int>& keys, std::string& error) {
    BeiDouBridge::NativeKeyInput::Mask desired{};
    if (!ResolveOwnedKeys(keys, desired, error)) return false;
    // Replace only this producer's desired set without flickering unchanged keys.
    target.Request(desired, 0, currentNative.user, GetTickCount64());
    return true;
}

// The native-consumable boundary is shared; the tick adapter owns its own
// NativeItemUse slot and cancellation/dispatched facts.
bool RequestNativeItem(std::uint32_t itemId, BeiDouBridge::NativeItemUse& target, std::string& error) {
    if (itemId / 10000 != 200) {
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
        if (item.inventoryType != 2 || item.itemId != itemId) continue;
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
    target.Request({currentState->character.id, currentState->sceneGeneration, context, slot, itemId});
    return true;
}

bool BeiDouTickAdapter::SetHeldKeys(const std::vector<std::string>& names, std::string& error) {
    std::vector<unsigned int> keys;
    for (const auto& name : names) {
        if (name == "left")
            keys.push_back(VK_LEFT);
        else if (name == "right")
            keys.push_back(VK_RIGHT);
        else if (name == "up")
            keys.push_back(VK_UP);
        else if (name == "down")
            keys.push_back(VK_DOWN);
        else {
            error = "unsupported: direction";
            return false;
        }
    }
    // The tick engine, not an input pulse deadline, owns persistent movement.
    if (!ApplyOwnedKeys(tickInput.movement, keys, error)) return false;
    tickInput.MovementChanged(currentNative.user);
    return true;
}

bool BeiDouTickAdapter::SetActionIntent(const MapleControl::Action& request, std::string& error) {
    if (request.kind == MapleControl::ActionKind::Attack && BeiDouBridge::IsNativeKeyDownSkill(request.skillId)) {
        tickInput.ReleaseAction();
        error = "unsupported: native_keydown_skill_release";
        tickInput.result.reason = error;
        return false;
    }
    if (BeiDouBridge::NativeTickInput::SameIntent(tickInput.Intent(), request)) {
        tickInput.SetIntent(request, currentNative.user);
        return true;
    }
    if (request.kind == MapleControl::ActionKind::Stop) {
        tickInput.SetIntent(request, currentNative.user);
        return true;
    }
    if (!Supports(request.kind)) {
        error = "unsupported: tick_action";
        return false;
    }
    if (!previousState.ready || previousState.character.values[6] == 0) {
        error = "state_unavailable_or_dead";
        return false;
    }
    unsigned int key = 0;
    if (request.kind == MapleControl::ActionKind::Jump) {
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 53, key, error)) return false;
    } else if (request.kind == MapleControl::ActionKind::Pickup) {
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 50, key, error)) return false;
    } else if (request.kind == MapleControl::ActionKind::Attack && request.skillId == 0) {
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 52, key, error)) return false;
    }
    // Validate before replacing the existing input. Skill IDs never resolve or
    // mutate hotkeys. Item admission uses a temporary typed request, not native I/O.
    BeiDouBridge::NativeItemUse item;
    if (request.kind == MapleControl::ActionKind::UseItem && !RequestNativeItem(request.itemId, item, error))
        return false;
    const auto keys = key == 0 ? std::vector<unsigned int>{} : std::vector<unsigned int>{key};
    BeiDouBridge::NativeKeyInput::Mask desired{};
    if (!ResolveOwnedKeys(keys, desired, error)) return false;
    tickInput.SetIntent(request, currentNative.user);
    tickInput.action.Request(desired, 0, currentNative.user, GetTickCount64());
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
        auto character = state.character.MotionDocument();
        character["id"] = state.character.id;
        character["name"] = state.character.name;
        character["movement"] = state.character.movement.Document();
        character["action_idle"] = state.actionIdle == MapleControl::Fact::Unknown
                                       ? MapleControl::Value{}
                                       : MapleControl::Value(state.actionIdle == MapleControl::Fact::True);
        const std::array<const char*, 13> names{
            "level",  "job", "strength", "dexterity",      "intelligence", "luck",      "hp",
            "max_hp", "mp",  "max_mp",   "ability_points", "skill_points", "experience"};
        for (unsigned int index = 0; index < names.size(); ++index) {
            character[names[index]] = state.character.known[index] ? MapleControl::Value(state.character.values[index])
                                                                   : MapleControl::Value{};
        }
        out << character.Dump();
    } else
        out << "null";
    out << ",\"position\":";
    if (state.positionKnown)
        out << "{\"x\":" << state.x << ",\"y\":" << state.y << '}';
    else
        out << "null";
    out << ",\"character_updates\":";
    if (state.characterUpdatesKnown)
        out << state.characterUpdates;
    else
        out << "null";
    out << ",\"on_ground\":";
    if (state.onGround == MapleControl::Fact::Unknown)
        out << "null";
    else
        out << (state.onGround == MapleControl::Fact::True ? "true" : "false");
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
            auto document = monster.MotionDocument();
            document["object_id"] = monster.objectId;
            document["template_id"] =
                monster.templateKnown ? MapleControl::Value(monster.templateId) : MapleControl::Value{};
            document["name"] = monster.name.empty() ? MapleControl::Value{} : MapleControl::Value(monster.name);
            document["active"] = monster.active;
            out << document.Dump();
        }
        out << ']';
    } else
        out << "null";
    out << ",\"backend\":\"beidou\",\"capabilities\":{\"move\":true,\"jump\":true,\"attack\":true,\"pickup\":true,\"use_item\":true,\"stop\":true,\"skill\":true,\"events\":true,\"projectiles\":false},\"event_stream_status\":"
        << Quote(eventsPublished ? "ok" : "publish_failed") << ",\"inventory\":";
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
            auto document = drop.MotionDocument();
            document["object_id"] = drop.objectId;
            document["item_id"] = drop.itemKnown ? MapleControl::Value(drop.itemId) : MapleControl::Value{};
            document["money"] = drop.moneyKnown ? MapleControl::Value(drop.money) : MapleControl::Value{};
            document["landed"] = drop.landed == MapleControl::Fact::Unknown
                                     ? MapleControl::Value{}
                                     : MapleControl::Value(drop.landed == MapleControl::Fact::True);
            out << document.Dump();
        }
        out << ']';
    } else
        out << "null";
    out << ",\"players\":";
    if (state.playersKnown) {
        out << '[';
        bool separator = false;
        for (const auto& player : state.players) {
            if (separator) out << ',';
            separator = true;
            auto document = player.MotionDocument();
            document["reference"] = player.reference;
            document["character_id"] =
                player.characterIdKnown ? MapleControl::Value(player.characterId) : MapleControl::Value{};
            document["name"] = player.name.empty() ? MapleControl::Value{} : MapleControl::Value(player.name);
            document["level"] = player.levelKnown ? MapleControl::Value(player.level) : MapleControl::Value{};
            document["facing"] =
                player.facingKnown ? MapleControl::Value(player.facingLeft ? "Left" : "Right") : MapleControl::Value{};
            out << document.Dump();
        }
        out << ']';
    } else
        out << "null";
    out << ",\"players_complete\":";
    if (state.playersComplete == MapleControl::Fact::Unknown)
        out << "null";
    else
        out << (state.playersComplete == MapleControl::Fact::True ? "true" : "false");
    out << ",\"npcs\":";
    if (state.npcsKnown) {
        auto npcs = MapleControl::Value::Array();
        for (const auto& npc : state.npcs) {
            auto document = npc.MotionDocument();
            document["object_id"] = npc.objectId;
            document["template_id"] = npc.templateId;
            document["name"] = npc.name.empty() ? MapleControl::Value{} : MapleControl::Value(npc.name);
            npcs.Add(std::move(document));
        }
        out << npcs.Dump();
    } else
        out << "null";
    out << ",\"projectiles\":null,\"projectiles_complete\":null";
    out << ",\"held_keys\":[";
    bool separator = false;
    for (unsigned int key = 0; key < 256; ++key)
        if (nativeKeys.Held(key)) {
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
    out << ",\"script\":" << (latestScriptId.empty() ? "null" : tickRuntime.CurrentStatus(latestScriptId).Dump());
    out << ",\"scripts\":" << tickRuntime.Statuses().Dump();
    out << ",\"tick_profile\":" << tickRuntime.Profile().Dump();
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
    if (operation == "script" || operation == "cancel_script") {
        stream >> scriptId;
        valid = valid && scriptId.size() == 32
                && scriptId.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos && !(stream >> extra);
        if (operation == "script")
            valid = valid && generation == sceneGeneration && value <= 0xffffffffULL && previousState.ready
                    && previousState.character.values[6] > 0;
        else
            valid = valid && value == 0;
    } else
        valid = valid && operation == "stop" && value == 0 && !(stream >> extra);
    if (!valid) {
        rejectedId = id;
        rejectedReason = "invalid_or_stale_command";
        if (!tickRuntime.Running() && tickAdapter.Released()) {
            commandId = id;
            commandStatus = "rejected";
            commandReason = rejectedReason;
        }
        return;
    }
    if (operation == "stop") {
        commandId = id;
        commandStatus = "running";
        commandReason.clear();
        tickRuntime.CancelAll("stopped");
        tickAdapter.Release();
        scriptCommand = false;
        stopCommand = true;
        return;
    }
    if (operation == "cancel_script") {
        if (tickRuntime.CurrentStatus(scriptId).Type() == MapleControl::Value::Kind::Null) {
            rejectedId = id;
            rejectedReason = "script_session_mismatch";
            return;
        }
        commandId = id;
        commandStatus = "running";
        commandReason.clear();
        commandScriptId = scriptId;
        scriptCommand = true;
        stopCommand = false;
        tickRuntime.Cancel(scriptId, "cancelled");
        return;
    }
    if (!tickRuntime.Running() && !tickAdapter.Released()) {
        rejectedId = id;
        rejectedReason = "busy";
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
    // The tick runtime owns mode validation: an explicit non-tick @mode is
    // rejected there, and an omitted @mode means tick.
    std::string error;
    const bool started = sourceValid && tickRuntime.Start(scriptId, source, static_cast<std::uint32_t>(value), error);
    commandId = id;
    commandReason.clear();
    stopCommand = false;
    if (!started) {
        scriptCommand = false;
        commandStatus = "rejected";
        commandReason = !sourceValid ? "script_file_unavailable" : "script_load_error";
    } else {
        latestScriptId = commandScriptId = scriptId;
        commandStatus = "running";
        scriptCommand = true;
    }
}

bool DeliverTickInput() {
    const auto frame = sequence;
    const auto revision = tickInput.IntentRevision();
    auto beforeKeys = CaptureNativeAction(currentNative.user);
    for (auto* input : {&tickInput.movement, &tickInput.action}) {
        if (input == &tickInput.action) beforeKeys = CaptureNativeAction(currentNative.user);
        const auto delivered =
            input->Flush([input](unsigned int key, bool down,
                                 std::uint64_t epoch) { return SendOwnedKey(*input, key, down, epoch); },
                         [] { return characterUpdates; });
        // Native delivery may pump cancellation/replacement. No old frame work
        // may resume, and failed keyups remain owned by the real producer.
        if (sequence != frame || revision != tickInput.IntentRevision()) return false;
        if (delivered.failed && delivered.epoch == input->Epoch()) tickInput.result.reason = "input_route_unavailable";
    }
    const bool exited = currentNative.loginStage || currentNative.user == 0;
    tickInput.MovementFlushed(updatedCharacter, characterUpdates, exited);
    const auto now = GetTickCount64();
    const auto& intent = tickInput.Intent();
    const bool ordinaryKey = intent.kind == MapleControl::ActionKind::Jump
                             || intent.kind == MapleControl::ActionKind::Pickup
                             || (intent.kind == MapleControl::ActionKind::Attack && intent.skillId == 0);
    // The first keydown is delivered by NativeKeyInput. It stays down without a
    // pulse deadline. Jump has no synthetic repeat in this conservative bridge.
    if (ordinaryKey && tickInput.DispatchPending() && !tickInput.Dispatched() && tickInput.action.Dispatched()) {
        const auto request = tickInput.TakeDispatch(now);
        tickInput.NativeStarted(request, revision, beforeKeys, CaptureNativeAction(currentNative.user), true);
    }
    tickInput.RepeatDue(now, intent.kind == MapleControl::ActionKind::Pickup
                                     || intent.kind == MapleControl::ActionKind::Attack
                                 ? CaptureNativeRepeat()
                                 : BeiDouBridge::NativeRepeatSettings{});
    if (tickInput.DispatchPending() && tickInput.Dispatched() && ordinaryKey
        && (intent.kind != MapleControl::ActionKind::Attack
            || CaptureNativeAction(currentNative.user).idle == MapleControl::Fact::True)) {
        unsigned int key = 0;
        const unsigned int binding = intent.kind == MapleControl::ActionKind::Pickup ? 50 : 52;
        std::string error;
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, binding, key, error)
            || !tickInput.action.Held()[key]) {
            tickInput.ReleaseAction();
            tickInput.result.reason = "native_action_binding_changed";
        } else {
            std::uint32_t input = 0, manager = 0;
            if (ReadAt(0x00BEC33C, input) && input != 0 && ReadAt(0x00BEC20C, manager) && manager != 0) {
                const auto request = tickInput.TakeDispatch(now);
                const auto before = CaptureNativeAction(currentNative.user);
                auto flags = ((scanCodes[key] & 0x7F) | ((scanCodes[key] & 0x80) << 1)) << 16;
                flags |= inputModifiers(reinterpret_cast<InputSystem*>(input));
                const auto messageKey = key == VK_LCONTROL || key == VK_RCONTROL ? VK_CONTROL
                                        : key == VK_LSHIFT || key == VK_RSHIFT   ? VK_SHIFT
                                        : key == VK_LMENU || key == VK_RMENU     ? VK_MENU
                                                                                 : key;
                ++inputEvents;
                // This is an actual repeat keydown, not a new union ownership
                // transition and never an up/down pulse of the held key.
                dispatchInput(0x100, messageKey, flags);
                if (sequence != frame || revision != tickInput.IntentRevision()) return false;
                tickInput.NativeStarted(request, revision, before, CaptureNativeAction(currentNative.user), true);
            } else {
                tickInput.result.reason = "input_route_unavailable";
            }
        }
    }
    if (tickInput.DispatchPending() && intent.kind == MapleControl::ActionKind::UseItem
        && tickInput.ItemDispatchAllowed(now)) {
        const auto request = tickInput.TakeDispatch(now);
        std::string error;
        if (!RequestNativeItem(request.itemId, tickInput.item, error)) tickInput.result.reason = error;
    }
    if (tickInput.item.Pending()) {
        std::uint32_t context = 0;
        if (!ReadAt(0x00BE7918, context)) context = 0;
        const auto consumed = tickInput.ConsumeItem(
            previousState.characterKnown ? previousState.character.id : 0, sceneGeneration, context, GetTickCount64(),
            [](const BeiDouBridge::NativeItemUse::Item& item) {
                useItem(reinterpret_cast<ClientContext*>(item.context), item.slot, static_cast<int>(item.itemId));
            });
        if (sequence != frame || revision != tickInput.IntentRevision()) return false;
        if (consumed == BeiDouBridge::NativeItemUse::Consumption::ContextChanged)
            tickInput.result.reason = "item_context_changed";
    }
    if (tickInput.DispatchPending() && intent.kind == MapleControl::ActionKind::Attack && intent.skillId != 0
        && tickInput.action.Released() && tickInput.HeldKeysSettled()
        && (!tickInput.Dispatched() || CaptureNativeAction(currentNative.user).idle == MapleControl::Fact::True)) {
        const auto request = tickInput.TakeDispatch(now);
        BeiDouBridge::NativeSkillUse::Skill skill;
        skill.skillId = request.skillId;
        skill.character = previousState.character.id;
        skill.user = currentNative.user;
        skill.sceneGeneration = sceneGeneration;
        skill.inputEpoch = tickInput.action.Epoch();
        // No animation/pulse timeout. The current held intent owns this pending
        // direction/context transaction; replacement and release cancel it.
        skill.deadline = (std::numeric_limits<std::uint64_t>::max)();
        tickInput.skill.Request(skill);
        tickInput.result.skillRequested = true;
        tickInput.result.skill = tickInput.skill.Result();
    }
    if (tickInput.skill.Pending()) {
        BeiDouBridge::NativeSkillUse::Context context;
        context.character = previousState.character.id;
        context.user = currentNative.user;
        context.sceneGeneration = sceneGeneration;
        context.inputEpoch = tickInput.action.Epoch();
        context.now = now;
        context.updatedCharacter = updatedCharacter;
        context.characterUpdates = characterUpdates;
        context.facingKnown = previousState.facingKnown;
        context.facingLeft = previousState.facingLeft;
        const auto request = intent;
        const auto before = CaptureNativeAction(currentNative.user);
        const bool consumed = tickInput.skill.Consume(context, InvokeNativeSkill);
        if (sequence != frame || revision != tickInput.IntentRevision()) return false;
        tickInput.result.skill = tickInput.skill.Result();
        tickInput.result.reason = tickInput.result.skill.reason;
        tickInput.NativeStarted(request, revision, before, CaptureNativeAction(currentNative.user),
                                consumed && tickInput.result.skill.nativeResultKnown
                                    && tickInput.result.skill.nativeResult != 0,
                                tickInput.result.skill.nativeResultKnown);
    }
    tickInput.ActionFlushed(updatedCharacter, characterUpdates, exited);
    return true;
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
    NativeObservation::BindEquipmentContext(instanceId, previousState.characterKnown ? previousState.character.id : 0,
                                            sceneGeneration);

    const bool ready = previousState.ready;
    // CallUpdate may return without advancing its 30ms character step. Confirm the actual consumer.
    const bool characterExited = native.loginStage || native.user == 0;
    tickInput.Observe(native.user, updatedCharacter, characterUpdates, characterExited);
    tickInput.ObserveAction(CaptureNativeAction(native.user), characterExited || changed);
    if ((changed || !ready || previousState.character.values[6] == 0)
        && (tickInput.movement.Active() || tickInput.HasIntent() || tickInput.item.Pending()))
        tickAdapter.Release();

    ReadCommand();
    tickRuntime.Tick(changed);
    if (scriptCommand) {
        const auto script = tickRuntime.CurrentStatus(commandScriptId);
        if (script.Type() != MapleControl::Value::Kind::Null && Member(script, "status").Text() != "running") {
            commandStatus = Member(script, "status").Text();
            commandReason = Member(script, "reason").Text();
            scriptCommand = false;
        }
    }
    if (stopCommand && !tickRuntime.Running() && tickAdapter.Released()) {
        commandStatus = "completed";
        commandReason = "stopped";
        stopCommand = false;
    }
    NativeObservation::Tick(directory, instanceId, runId, sceneGeneration, sequence);
    BeiDouBridge::LoginAction::Tick(directory, instanceId, runId);
    if (now - lastPublishedAt >= 25) {
        NativeObservation::PollNotifications(*eventTransport, previousState);
        eventsPublished = eventTransport->Flush(previousState);
        if (!Publish(previousState)) {
            // This is a shared host transport failure, not a script failure.
            tickRuntime.CancelAll("state_publish_failed");
            tickAdapter.Release();
        }
        lastPublishedAt = now;
    }
    DeliverTickInput();
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
    std::array<char, MAX_PATH> data{};
    const DWORD dataLength = GetEnvironmentVariableA("MAPLE_DATA_ROOT", data.data(), static_cast<DWORD>(data.size()));
    if (dataLength > 0 && dataLength < data.size()) sceneDataRoot.assign(data.data(), dataLength);
    if (!CreateDirectoryA(directory.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return false;
    std::array<char, 128> run{};
    const DWORD runLength = GetEnvironmentVariableA("RUN_ID", run.data(), static_cast<DWORD>(run.size()));
    if (runLength < run.size()) runId.assign(run.data(), runLength);
    eventTransport.reset(new MapleControl::EventTransport(directory, runId));
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
