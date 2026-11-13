#include "stdafx.h"
#include "AgentBridge.h"
#include "Runtime.h"
#include "TickRuntime.h"
#include "NativeKeyUnion.h"
#include "NativeTickInput.h"
#include "TaskTransport.h"
#include "EventTransport.h"
#include "NativeKeyInput.h"
#include "NativeKeyBindings.h"
#include "NativeMouseInput.h"
#include "NativeCare.h"
#include "NativeItemUse.h"
#include "NativeSkillUse.h"
#include "NativeObservation.h"
#include "NativeMotion.h"
#include "LoginAction.h"

#include <array>
#include <algorithm>
#include <cstdint>
#include <cmath>
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
using InventoryInputReady = int(__thiscall*)(ClientContext*, int, int);
using SetNativeCursor = int(__thiscall*)(InputSystem*, int, int);
using GetNativeCursor = int(__thiscall*)(InputSystem*, POINT*);

auto originalUpdate = reinterpret_cast<ApplicationUpdate>(0x009F84D0);
auto originalKeyPressed = reinterpret_cast<KeyPressed>(0x0059A25A);
const auto dispatchInput = reinterpret_cast<InputMessage>(0x009F97B7);
const auto inputModifiers = reinterpret_cast<InputModifiers>(0x0059B1EB);
const auto activeSkill = reinterpret_cast<ActiveSkill>(0x00966F7A);
const auto useItem = reinterpret_cast<UseItem>(0x00A092FB);
const auto inventoryInputReady = reinterpret_cast<InventoryInputReady>(0x00485BF7);
const auto setNativeCursor = reinterpret_cast<SetNativeCursor>(0x0059A887);
const auto getNativeCursor = reinterpret_cast<GetNativeCursor>(0x0059A388);

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
BeiDouBridge::NativeTickInput tickInput;
BeiDouBridge::NativeKeyUnion nativeKeys{&keyInput, &tickInput.movement, &tickInput.action};
BeiDouBridge::NativeMouseInput mouseInput;
BeiDouBridge::NativeCare care;
bool careResult = false;
bool careTracking = false;
bool careKeyDispatched = false;
unsigned careMenuAction = 0;
BeiDouBridge::NativeItemUse itemUse;
BeiDouBridge::NativeSkillUse skillUse;
bool itemResult = false;
bool attackWindow = false;
ULONGLONG attackWindowUntil = 0;
std::array<unsigned int, 256> scanCodes{};
std::array<std::uint32_t, 256> nativeScanCodes{};
std::uint32_t nativeScanCodesOwner = 0;
bool scriptCommand = false;
bool stopCommand = false;
std::string commandScriptId;
MapleControl::ScriptMode commandScriptMode = MapleControl::ScriptMode::Coroutine;

struct ScriptSession {
    std::string id;
    MapleControl::ScriptMode mode;
    MapleControl::Value status;
};

std::vector<ScriptSession> scriptSessions;
bool haveSkillResult = false;
std::uint32_t lastSkillId = 0;
int lastSkillResult = 0;
std::uint64_t skillInvocationRevision = 0;
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
bool eventsPublished = false;

void BeginRelease(const std::string& status, const std::string& reason);
bool BeginNativeAction(const MapleControl::Action& action, std::string& error);
MapleControl::ActionResult NativeResult();
bool NativeRawKeys(const std::vector<std::string>& keys, unsigned int duration, std::string& error);
bool InvokeNativeSkill(std::uint32_t skillId, int& result, std::string& error);
bool NativeLogs(const std::string& scriptId, const std::vector<std::string>& lines);
BeiDouBridge::CareView CaptureCareView(const MapleControl::Action* action = nullptr, bool sceneHitTest = false);
bool SendMouse(BeiDouBridge::NativeMouseInput::Event event, const BeiDouBridge::NativeMouseInput::Target& target,
               std::uint64_t epoch);

class BeiDouAdapter final : public MapleControl::Adapter {
public:
    const char* Backend() const override { return "beidou"; }

    const MapleControl::State& Observe() const override { return previousState; }

    MapleControl::Observation ObserveDomain(const std::string& domain) const override {
        return NativeObservation::Collect(domain);
    }

    bool Supports(MapleControl::ActionKind kind) const override {
        return kind != MapleControl::ActionKind::Unequip && kind != MapleControl::ActionKind::Revive
               && kind != MapleControl::ActionKind::Activate;
    }

    bool Begin(const MapleControl::Action& action, std::string& error) override {
        return BeginNativeAction(action, error);
    }

    MapleControl::ActionResult Result() const override { return NativeResult(); }

    void Release() override { BeginRelease({}, {}); }

    bool Released() const override {
        return !attackWindow && keyInput.Released() && mouseInput.Released() && !care.Active() && !care.CleanupPending()
               && !itemUse.Pending();
    }

    bool ReleasePending() const override {
        // Releasing one UI pulse does not release the enclosing workflow.
        // Runtime must still cancel that workflow when its owner is preempted.
        return care.ReleasePending(keyInput.ReleasePending(), mouseInput.ReleasePending());
    }

    bool Logs(const std::string& scriptId, const std::vector<std::string>& lines) override {
        return NativeLogs(scriptId, lines);
    }

    bool SupportsRawKeys() const override { return true; }

    bool RawKeys(const std::vector<std::string>& keys, std::uint32_t duration, std::string& error) override {
        return NativeRawKeys(keys, duration, error);
    }

    bool SupportsSkill() const override { return true; }

    bool Skill(std::uint32_t id, MapleControl::SkillResult& result, std::string& error) override {
        if (!InvokeNativeSkill(id, result.nativeResult, error)) return false;
        result.dispatched = true;
        result.reason = "native_skill_requested";
        return true;
    }
};

class BeiDouTickAdapter final : public MapleControl::TickAdapter {
public:
    const char* Backend() const override { return "beidou"; }

    const MapleControl::State& Observe() const override { return previousState; }

    MapleControl::Observation ObserveDomain(const std::string& domain) const override {
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

    bool Begin(const MapleControl::Action& action, std::string& error) override;
    bool SetHeldKeys(const std::vector<std::string>& keys, std::string& error) override;

    bool HeldKeysSettled() const override { return tickInput.HeldKeysSettled(); }

    MapleControl::ActionResult Result() const override { return tickInput.Result(); }

    void Release() override { tickInput.Release(currentNative.user); }

    void ReleaseAction() override { tickInput.ReleaseAction(); }

    bool Released() const override { return tickInput.Released(); }

    bool ReleasePending() const override { return tickInput.ReleasePending(); }

    bool Logs(const std::string& id, const std::vector<std::string>& lines) override { return NativeLogs(id, lines); }
};

BeiDouAdapter adapter;
MapleControl::Runtime runtime(adapter);
BeiDouTickAdapter tickAdapter;
MapleControl::TickRuntime tickRuntime(tickAdapter);
std::unique_ptr<MapleControl::TaskTransport> taskTransport;
std::unique_ptr<MapleControl::EventTransport> eventTransport;

template <typename T> bool ReadAt(std::uintptr_t address, T& value) {
    SIZE_T count = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(address), &value, sizeof(value), &count)
           && count == sizeof(value);
}

const MapleControl::Value& CareField(const MapleControl::Value& object, const std::string& name) {
    for (const auto& entry : object.Members())
        if (entry.first == name) return entry.second;
    static const MapleControl::Value unknown;
    return unknown;
}

int CareNumber(const MapleControl::Value& value) {
    if (value.Type() != MapleControl::Value::Kind::Number || !std::isfinite(value.Number())
        || std::floor(value.Number()) != value.Number() || value.Number() < -2147483648.0
        || value.Number() > 2147483647.0)
        throw NativeObservation::ReadError("Care numeric fact is unavailable");
    return static_cast<int>(value.Number());
}

std::uint32_t CareAddress(const MapleControl::Value& value) {
    if (value.Type() == MapleControl::Value::Kind::Null) return 0;
    if (value.Type() != MapleControl::Value::Kind::String)
        throw NativeObservation::ReadError("Care address is unavailable");
    std::size_t end = 0;
    const auto parsed = std::stoull(value.Text(), &end, 16);
    if (end != value.Text().size() || parsed > 0xffffffffULL)
        throw NativeObservation::ReadError("Care address is invalid");
    return static_cast<std::uint32_t>(parsed);
}

bool CareTrue(const MapleControl::Value& value) {
    return value.Type() == MapleControl::Value::Kind::Boolean && value.Boolean();
}

bool CareFalse(const MapleControl::Value& value) {
    return value.Type() == MapleControl::Value::Kind::Boolean && !value.Boolean();
}

BeiDouBridge::CareView CaptureCareView(const MapleControl::Action* action, bool sceneHitTest) {
    using Value = MapleControl::Value;
    BeiDouBridge::CareView view;
    view.nativeUser = currentNative.user;
    view.characterId = previousState.characterKnown ? previousState.character.id : 0;
    view.sceneGeneration = previousState.sceneGeneration;
    try {
        const auto ui = NativeObservation::Ui();
        const auto& unavailable = CareField(ui, "unavailable");
        if (unavailable.Type() != Value::Kind::Array || !unavailable.Elements().empty()) return view;
        const auto& dialog = CareField(ui, "dialog");
        for (const auto* field : {"script_dialog_open", "focused_talk_dialog_open", "registered_talk_dialog_open"})
            if (!CareFalse(CareField(dialog, field))) view.blocked = true;
        const auto& camera = CareField(dialog, "camera_viewport");
        const auto cameraX = CareNumber(CareField(camera, "left"));
        const auto cameraY = CareNumber(CareField(camera, "top"));
        view.width = CareNumber(CareField(camera, "right")) - cameraX;
        view.height = CareNumber(CareField(camera, "bottom")) - cameraY;
        view.gameFocused =
            CareField(CareField(dialog, "keyboard_handler"), "type_name").Text() == "CWndMan::IUIMsgHandler";
        view.focusedWindow = CareAddress(CareField(CareField(dialog, "focused_window"), "address"));
        const auto manager = NativeObservation::Read<std::uint32_t>(0x00BEC20C);
        if (manager == 0 || NativeObservation::Read<std::uint32_t>(manager) != 0x00B3F13C) return view;
        view.dragObject = NativeObservation::Read<std::uint32_t>(manager + 0x98);
        if (view.dragObject != 0 && NativeObservation::Read<std::uint32_t>(view.dragObject) == 0xAF34D8) {
            view.dragInventoryType = NativeObservation::Read<int>(view.dragObject + 0x18);
            view.dragSlot = NativeObservation::Read<int>(view.dragObject + 0x1C);
        }
        const auto& windows = CareField(ui, "windows");
        if (windows.Type() != Value::Kind::Array) return view;
        for (const auto& record : windows.Elements()) {
            BeiDouBridge::CareWindow window;
            window.address = CareAddress(CareField(record, "address"));
            window.identity = CareField(record, "instance_ref").Text();
            window.name = CareField(record, "type_name").Text();
            window.name = window.name == "CUIItem"    ? "inventory"
                          : window.name == "CUIStat"  ? "stats"
                          : window.name == "CUISkill" ? "skills"
                                                      : "";
            const auto& tables = CareField(record, "vtables").Elements();
            if (tables.empty()) return view;
            const auto table = CareAddress(tables[0]);
            window.sceneLayer = table == 0xB3F13C || table == 0xB37BBC || table == 0xB3BA80;
            if (table == 0xAFE110 || table == 0xAF0AF8) view.blocked = true;
            const auto& rect = CareField(record, "game_rect");
            window.geometryKnown = rect.Type() == Value::Kind::Object;
            if (window.geometryKnown) {
                window.rect.x = CareNumber(CareField(rect, "left"));
                window.rect.y = CareNumber(CareField(rect, "top"));
                window.rect.width = CareNumber(CareField(rect, "right")) - window.rect.x;
                window.rect.height = CareNumber(CareField(rect, "bottom")) - window.rect.y;
                if (window.rect.width != CareNumber(CareField(record, "width"))
                    || window.rect.height != CareNumber(CareField(record, "height")))
                    return view;
            }
            for (const auto& control : CareField(record, "buttons").Elements()) {
                BeiDouBridge::CareButton button;
                button.id = CareNumber(CareField(control, "control_id"));
                button.rect = {CareNumber(CareField(control, "layout_x")), CareNumber(CareField(control, "layout_y")),
                               CareNumber(CareField(control, "width")), CareNumber(CareField(control, "height"))};
                const auto& enabled = CareField(control, "enabled");
                button.enabledKnown = enabled.Type() == Value::Kind::Boolean;
                button.enabled = enabled.Boolean();
                window.buttons.push_back(button);
            }
            const auto& skills = CareField(record, "skills");
            if (skills.Type() == Value::Kind::Object) {
                window.firstIndex = CareNumber(CareField(skills, "first_index"));
                window.selectedTab = CareNumber(CareField(skills, "selected_tab"));
                window.tabCount = CareNumber(CareField(skills, "tab_count"));
                const auto& ids = CareField(skills, "ids");
                window.skillsKnown = ids.Type() == Value::Kind::Array;
                for (const auto& id : ids.Elements()) window.skills.push_back(CareNumber(id));
            }
            const auto& inventory = CareField(record, "inventory");
            if (inventory.Type() == Value::Kind::Object) {
                window.inventoryKnown = CareField(inventory, "expanded").Type() == Value::Kind::Boolean;
                window.expanded = CareTrue(CareField(inventory, "expanded"));
                window.firstSlot = CareNumber(CareField(inventory, "first_slot"));
                window.inventoryType = CareNumber(CareField(inventory, "selected_type"));
            }
            view.windows.push_back(window);
        }
        std::string expectedWindow;
        if (action != nullptr) {
            expectedWindow = action->kind == MapleControl::ActionKind::AllocateAp   ? "stats"
                             : action->kind == MapleControl::ActionKind::AllocateSp ? "skills"
                             : action->kind == MapleControl::ActionKind::Equip      ? "inventory"
                                                                                    : action->reference;
        }
        const bool windowMissing =
            std::none_of(view.windows.begin(), view.windows.end(),
                         [&](const BeiDouBridge::CareWindow& window) { return window.name == expectedWindow; });
        const bool wantsScene = windowMissing || (action != nullptr && action->direction == "close");
        // Recheck hit testing at root-click delivery; other UI steps avoid a full scene scan.
        if (sceneHitTest || (!view.gameFocused && wantsScene)) {
            const auto scene = NativeObservation::Scene();
            view.sceneKnown =
                CareFalse(CareField(scene, "pending_dynamic")) && CareField(scene, "npcs").Type() == Value::Kind::Array;
            for (const auto& npc : CareField(scene, "npcs").Elements())
                view.npcs.emplace_back(CareNumber(CareField(npc, "x")) - cameraX,
                                       CareNumber(CareField(npc, "y")) - cameraY);
        }
        if (action != nullptr && action->kind == MapleControl::ActionKind::AllocateSp) {
            const auto character = NativeObservation::Character();
            const auto& errors = CareField(character, "unavailable");
            view.skillsKnown =
                CareTrue(CareField(character, "skills_complete"))
                && CareNumber(CareField(character, "character_id")) == static_cast<int>(previousState.character.id)
                && errors.Type() == Value::Kind::Array && errors.Elements().empty();
            const auto& skill = CareField(CareField(character, "skills"), std::to_string(action->allocation.skillId));
            if (skill.Type() != Value::Kind::Null) {
                const int level = CareNumber(CareField(skill, "level"));
                if (level < 0) return BeiDouBridge::CareView{};
                view.skillLevel = static_cast<unsigned>(level);
                const auto& maximum = CareField(skill, "master_level");
                if (maximum.Type() != Value::Kind::Null) {
                    const auto value = CareNumber(maximum);
                    if (value < 0) return BeiDouBridge::CareView{};
                    view.skillMaximum = static_cast<unsigned>(value);
                }
            }
        }
        if (action != nullptr && action->kind == MapleControl::ActionKind::Equip) {
            // CUIItem's button-down route (0x0081D450) queries this read-only
            // predicate with (500, 0): request lock, live HP and native game time
            // since the last request. A released mouse does not imply readiness.
            const auto context = NativeObservation::Read<std::uint32_t>(0x00BE7918);
            const auto clock = NativeObservation::Read<std::uint32_t>(0x00BE7B38);
            if (context != 0 && clock != 0 && NativeObservation::Read<std::uint32_t>(context + 0x20B8) != 0) {
                view.inventoryInputKnown = true;
                view.inventoryInputReady = inventoryInputReady(reinterpret_cast<ClientContext*>(context), 500, 0) != 0;
            }
            const auto inventory = NativeObservation::Inventory();
            const auto& errors = CareField(inventory, "unavailable");
            view.inventoryKnown = CareTrue(CareField(inventory, "checksums_valid"))
                                  && errors.Type() == Value::Kind::Array && errors.Elements().empty();
            for (const auto* list : {"items", "equipped"})
                for (const auto& entry : CareField(inventory, list).Elements()) {
                    if (CareNumber(CareField(entry, "inventory_type")) != 1) continue;
                    BeiDouBridge::CareEquipment equipment;
                    equipment.itemId = CareNumber(CareField(entry, "item_id"));
                    const auto& properties = CareField(entry, "equipment");
                    equipment.reference = CareField(properties, "object_ref").Text();
                    const auto& ordinary = CareField(properties, "ordinary");
                    equipment.ordinaryKnown = ordinary.Type() == Value::Kind::Boolean;
                    equipment.ordinary = ordinary.Boolean();
                    for (const auto& slot : CareField(properties, "body_slots").Elements())
                        equipment.bodySlots.push_back(CareNumber(slot));
                    view.inventory.emplace(CareNumber(CareField(entry, "slot")), equipment);
                }
        }
        view.known = true;
    } catch (const std::exception&) {
        view.known = false;
    }
    return view;
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
    if (key == VK_LBUTTON && mouseInput.Owned()) return mouseInput.Held() ? 1 : 0;
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

bool SendOwnedKey(BeiDouBridge::NativeKeyInput& source, bool legacy, unsigned int key, bool down, std::uint64_t epoch) {
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
    if (legacy && down && careResult && care.Active() && inputModifiers(reinterpret_cast<InputSystem*>(input)) != 0)
        return false;
    if (legacy && down && careResult && care.Active() && careMenuAction != 0) {
        unsigned int currentKey = 0;
        std::string error;
        if (!BindingKey(BeiDouBridge::NativeBindingType::Menu, careMenuAction, currentKey, error) || currentKey != key)
            return false;
    }
    if (legacy && down && careResult && care.Active()) careKeyDispatched = true;
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

bool SendKey(unsigned int key, bool down, std::uint64_t epoch) {
    return SendOwnedKey(keyInput, true, key, down, epoch);
}

void BeginRelease(const std::string& status, const std::string& reason) {
    if (care.Active())
        care.Cancel(previousState, CaptureCareView(&care.Request()), GetTickCount64(), "care_cancelled",
                    mouseInput.Released());
    if (!mouseInput.Released()) mouseInput.Release();
    attackWindow = false;
    skillUse.Cancel("native_skill_cancelled");
    if (semanticResult.skillRequested) semanticResult.skill = skillUse.Result();
    itemUse.Cancel();
    keyInput.Release();
    pendingStatus = status;
    pendingReason = reason;
}

bool SendMouse(BeiDouBridge::NativeMouseInput::Event event, const BeiDouBridge::NativeMouseInput::Target& target,
               std::uint64_t epoch) {
    using Event = BeiDouBridge::NativeMouseInput::Event;
    std::uint32_t input = 0, manager = 0;
    if (!ReadAt(0x00BEC33C, input) || input == 0 || !ReadAt(0x00BEC20C, manager) || manager == 0) return false;
    std::uint32_t managerType = 0;
    if (!ReadAt(manager, managerType) || managerType != 0x00B3F13C) return false;
    if (event == Event::Up) {
        const bool cancel = mouseInput.Cancelled() || !previousState.ready || currentNative.user != target.character
                            || sceneGeneration != target.scene;
        if (cancel && target.window != 0) {
            bool known = false;
            const bool present = NativeObservation::WindowActive(target.window, known);
            if (!known) return false;
            if (present) {
                const auto view = CaptureCareView(&care.Request());
                int x = 0, y = 0;
                if (!BeiDouBridge::NativeCare::CancelPoint(view, target.window, x, y)) return false;
                auto* nativeInput = reinterpret_cast<InputSystem*>(input);
                POINT position{};
                if (!setNativeCursor(nativeInput, x, y)) return false;
                std::uint32_t currentInput = 0;
                if (epoch != mouseInput.Epoch() || !ReadAt(0x00BEC33C, currentInput) || currentInput != input)
                    return false;
                if (!getNativeCursor(nativeInput, &position) || position.x != x || position.y != y) return false;
                ++inputEvents;
                dispatchInput(WM_MOUSEMOVE, 0, 0);
                if (epoch != mouseInput.Epoch()) return false;
            }
        }
        ++inputEvents;
        dispatchInput(BeiDouBridge::NativeMouseInput::Message(event), 0, 0);
        return true;
    }
    if (epoch != mouseInput.Epoch() || !previousState.ready || currentNative.user != target.character
        || sceneGeneration != target.scene)
        return false;
    const auto view = CaptureCareView(&care.Request(), target.window == 0);
    if (!BeiDouBridge::NativeCare::AllowsTarget(view, target)) return false;
    auto* nativeInput = reinterpret_cast<InputSystem*>(input);
    if (inputModifiers(nativeInput) != 0 || originalKeyPressed(nativeInput, VK_LBUTTON)
        || originalKeyPressed(nativeInput, VK_RBUTTON))
        return false;
    POINT actual{};
    if (event == Event::Position) {
        if (!setNativeCursor(nativeInput, target.x, target.y)) return false;
        if (epoch != mouseInput.Epoch()) return true;
        std::uint32_t currentInput = 0;
        if (!ReadAt(0x00BEC33C, currentInput) || currentInput != input) return false;
        if (!getNativeCursor(nativeInput, &actual) || actual.x != target.x || actual.y != target.y) return false;
        ++inputEvents;
        dispatchInput(WM_MOUSEMOVE, 0, 0);
        return true;
    }
    if (!getNativeCursor(nativeInput, &actual) || actual.x != target.x || actual.y != target.y) return false;
    if (event == Event::Down && target.point && !care.DispatchPoint(previousState, view, target, GetTickCount64()))
        return false;
    if ((event == Event::Down || event == Event::DoubleDown) && target.equipment
        && !care.DispatchEquipment(previousState, view, target))
        return false;
    mouseInput.MarkDispatched(epoch);
    ++inputEvents;
    if (event == Event::Wheel)
        dispatchInput(BeiDouBridge::NativeMouseInput::Message(event), static_cast<unsigned int>(target.wheel) << 16, 0);
    else
        dispatchInput(BeiDouBridge::NativeMouseInput::Message(event), MK_LBUTTON, 0);
    return true;
}

bool ApplyOwnedKeys(BeiDouBridge::NativeKeyInput& target, const std::vector<unsigned int>& keys,
                    unsigned int durationMs, std::string& error) {
    std::array<bool, 256> desired{};
    if (keys.empty()) {
        target.Request(desired, durationMs, currentNative.user, GetTickCount64());
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
    // Replace only this producer's desired set without flickering unchanged keys.
    target.Request(desired, durationMs, currentNative.user, GetTickCount64());
    return true;
}

bool ApplyDesiredKeys(const std::vector<unsigned int>& keys, unsigned int durationMs, std::string& error) {
    if (!ApplyOwnedKeys(keyInput, keys, durationMs, error)) return false;
    pendingStatus.clear();
    pendingReason.clear();
    return true;
}

// Both engines use the same real ordinary-consumable boundary, but each owns
// its own NativeItemUse slot and cancellation/dispatched facts.
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
    if (!ApplyOwnedKeys(tickInput.movement, keys, 0, error)) return false;
    tickInput.MovementChanged(currentNative.user);
    return true;
}

bool BeiDouTickAdapter::Begin(const MapleControl::Action& request, std::string& error) {
    if (!Supports(request.kind)) {
        error = "unsupported: tick_action";
        return false;
    }
    if (!previousState.ready || previousState.character.values[6] == 0) {
        error = "state_unavailable_or_dead";
        return false;
    }
    if (!Released()) {
        error = "busy";
        return false;
    }
    tickInput.result = MapleControl::ActionResult{};
    tickInput.itemResult = false;
    if (request.kind == MapleControl::ActionKind::UseItem) {
        if (!RequestNativeItem(request.itemId, tickInput.item, error)) return false;
        tickInput.itemResult = true;
        tickInput.result.reason = "item_use_requested";
        return true;
    }
    unsigned int key = 0;
    if (request.kind == MapleControl::ActionKind::Jump) {
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 53, key, error)) return false;
    } else if (request.kind == MapleControl::ActionKind::Pickup) {
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 50, key, error)) return false;
    } else if (request.skillId == 0) {
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 52, key, error)) return false;
    }
    const auto duration = request.durationMs == 0 ? 60 : request.durationMs;
    const std::vector<unsigned int> keys = key == 0 ? std::vector<unsigned int>{} : std::vector<unsigned int>{key};
    if (!ApplyOwnedKeys(tickInput.action, keys, duration, error)) return false;
    tickInput.actionWindow = true;
    tickInput.actionUntil = GetTickCount64() + duration;
    if (request.kind == MapleControl::ActionKind::Attack && request.skillId != 0) {
        BeiDouBridge::NativeSkillUse::Skill skill;
        skill.skillId = request.skillId;
        skill.character = previousState.character.id;
        skill.user = currentNative.user;
        skill.sceneGeneration = sceneGeneration;
        skill.inputEpoch = tickInput.action.Epoch();
        skill.deadline = tickInput.actionUntil;
        // Direction is exclusively the tick state machine's persistent input.
        tickInput.skill.Request(skill);
        tickInput.result.skillRequested = true;
        tickInput.result.skill = tickInput.skill.Result();
    }
    tickInput.result.reason = "native_action_requested";
    return true;
}

MapleControl::Value CoroutineStatus(const MapleControl::Status& status) {
    using MapleControl::Value;
    auto tasks = Value::Array();
    for (const auto& task : status.tasks)
        tasks.Add(Value::Object({{"name", task.name},
                                 {"revision", task.revision},
                                 {"priority", task.priority},
                                 {"status", task.status},
                                 {"wait", task.wait},
                                 {"reason", task.reason.empty() ? Value{} : Value(task.reason)},
                                 {"error", task.error.empty() ? Value{} : Value(task.error)}}));
    const auto& control = status.control;
    return Value::Object(
        {{"id", status.id},
         {"mode", "coroutine"},
         {"status", status.status},
         {"control_released", !runtime.Running() && adapter.Released()},
         {"reason", status.reason.empty() ? Value{} : Value(status.reason)},
         {"error", status.error.empty() ? Value{} : Value(status.error)},
         {"resumes", status.resumes},
         {"budget_yields", status.budgetYields},
         {"last_resume_us", status.lastResumeUs},
         {"max_resume_us", status.maxResumeUs},
         {"tasks", std::move(tasks)},
         {"control", Value::Object({{"owner", control.owner.empty() ? Value{} : Value(control.owner)},
                                    {"pending", control.pending.empty() ? Value{} : Value(control.pending)},
                                    {"from", control.from.empty() ? Value{} : Value(control.from)},
                                    {"to", control.to.empty() ? Value{} : Value(control.to)},
                                    {"reason", control.reason.empty() ? Value{} : Value(control.reason)}})}});
}

void RefreshScriptStatuses() {
    const auto* coroutine = runtime.CurrentStatus();
    for (auto& session : scriptSessions) {
        if (session.mode == MapleControl::ScriptMode::Tick)
            session.status = tickRuntime.CurrentStatus(session.id);
        else if (coroutine != nullptr && coroutine->id == session.id)
            session.status = CoroutineStatus(*coroutine);
    }
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
    out << ",\"backend\":\"beidou\",\"capabilities\":{\"move\":true,\"face\":true,\"jump\":true,\"attack\":true,\"attack_move\":true,\"pickup\":true,\"use_item\":true,\"equip\":true,\"unequip\":false,\"allocate_ap\":true,\"allocate_sp\":true,\"window\":true,\"revive\":false,\"activate\":false,\"stop\":true,\"raw_keys\":true,\"skill\":true,\"monster_hp_percent\":false,\"events\":true,\"projectiles\":false},\"event_stream_status\":"
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
    if (mouseInput.Held()) {
        if (separator) out << ',';
        out << VK_LBUTTON;
    }
    out << "],\"command\":{\"id\":" << (commandId.empty() ? "null" : Quote(commandId))
        << ",\"status\":" << Quote(commandStatus)
        << ",\"reason\":" << (commandReason.empty() ? "null" : Quote(commandReason)) << "},\"rejected_command\":";
    if (rejectedReason.empty())
        out << "null";
    else
        out << "{\"id\":" << (rejectedId.empty() ? "null" : Quote(rejectedId))
            << ",\"status\":\"rejected\",\"reason\":" << Quote(rejectedReason) << '}';
    RefreshScriptStatuses();
    out << ",\"script\":" << (scriptSessions.empty() ? "null" : scriptSessions.back().status.Dump());
    auto scripts = MapleControl::Value::Array();
    for (const auto& session : scriptSessions) scripts.Add(session.status);
    out << ",\"scripts\":" << scripts.Dump();
    out << ",\"tick_profile\":" << tickRuntime.Profile().Dump();
    out << ",\"last_skill\":";
    if (haveSkillResult)
        out << "{\"skill_id\":" << lastSkillId << ",\"native_result\":" << lastSkillResult
            << ",\"dispatched\":true,\"reason\":\"native_skill_requested\"}";
    else
        out << "null";
    const auto actionResult = NativeResult();
    out << ",\"action_result\":{\"dispatched\":" << (actionResult.dispatched ? "true" : "false")
        << ",\"control_released\":" << (actionResult.controlReleased ? "true" : "false") << ",\"settled\":";
    if (actionResult.settled == MapleControl::Fact::Unknown)
        out << "null";
    else
        out << (actionResult.settled == MapleControl::Fact::True ? "true" : "false");
    out << ",\"effect\":" << Quote(actionResult.effect) << ",\"reason\":" << Quote(actionResult.reason);
    if (actionResult.skillRequested) {
        out << ",\"skill_dispatched\":" << (actionResult.skill.dispatched ? "true" : "false")
            << ",\"skill_native_result\":";
        if (actionResult.skill.nativeResultKnown)
            out << actionResult.skill.nativeResult;
        else
            out << "null";
        out << ",\"skill_reason\":" << Quote(actionResult.skill.reason);
    }
    if (actionResult.allocation.Type() != MapleControl::Value::Kind::Null)
        out << ",\"allocation\":" << actionResult.allocation.Dump();
    if (!actionResult.sessionId.empty()) out << ',' << Quote("session_id") << ':' << Quote(actionResult.sessionId);
    if (actionResult.equipment.Type() != MapleControl::Value::Kind::Null)
        out << ',' << Quote("equipment") << ':' << actionResult.equipment.Dump();
    if (actionResult.ui.Type() != MapleControl::Value::Kind::Null) out << ",\"ui\":" << actionResult.ui.Dump();
    out << '}';
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
        if (!runtime.Running() && !tickRuntime.Running() && adapter.Released() && tickAdapter.Released()) {
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
        runtime.Cancel("stopped");
        tickRuntime.CancelAll("stopped");
        tickAdapter.Release();
        scriptCommand = false;
        stopCommand = true;
        BeginRelease({}, {});
        return;
    }
    if (operation == "cancel_script") {
        const auto session = std::find_if(scriptSessions.begin(), scriptSessions.end(),
                                          [&scriptId](const ScriptSession& entry) { return entry.id == scriptId; });
        if (session == scriptSessions.end()) {
            rejectedId = id;
            rejectedReason = "script_session_mismatch";
            return;
        }
        commandId = id;
        commandStatus = "running";
        commandReason.clear();
        commandScriptId = scriptId;
        commandScriptMode = session->mode;
        scriptCommand = true;
        stopCommand = false;
        if (session->mode == MapleControl::ScriptMode::Tick)
            tickRuntime.Cancel(scriptId, "cancelled");
        else if (runtime.CurrentStatus() != nullptr && runtime.CurrentStatus()->id == scriptId)
            runtime.Cancel("cancelled");
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
    const auto mode = sourceValid ? MapleControl::ParseScriptMode(source, error) : MapleControl::ScriptMode::Invalid;
    const bool busy = mode == MapleControl::ScriptMode::Coroutine
                          ? runtime.Running() || !adapter.Released()
                          : mode == MapleControl::ScriptMode::Tick && !tickRuntime.Running() && !tickAdapter.Released();
    const bool duplicate = std::any_of(scriptSessions.begin(), scriptSessions.end(),
                                       [&scriptId](const ScriptSession& entry) { return entry.id == scriptId; });
    if (busy || duplicate) {
        rejectedId = id;
        rejectedReason = busy ? "busy" : "script_session_exists";
        return;
    }
    // Preserve the last admitted coroutine status before Runtime.Start replaces
    // its single report, including when the new chunk is later rejected.
    RefreshScriptStatuses();
    const bool started = mode == MapleControl::ScriptMode::Tick
                             ? tickRuntime.Start(scriptId, source, static_cast<std::uint32_t>(value), error)
                             : mode == MapleControl::ScriptMode::Coroutine
                                   && runtime.Start(scriptId, source, static_cast<std::uint32_t>(value), error);
    commandId = id;
    commandReason.clear();
    stopCommand = false;
    if (!started) {
        scriptCommand = false;
        commandStatus = "rejected";
        commandReason = !sourceValid ? "script_file_unavailable" : "script_load_error";
    } else {
        scriptSessions.push_back({scriptId, mode, {}});
        RefreshScriptStatuses();
        commandScriptId = scriptId;
        commandScriptMode = mode;
        commandStatus = "running";
        scriptCommand = true;
    }
}

bool DeliverTickInput() {
    const auto frame = sequence;
    tickInput.ExpireAction(GetTickCount64());
    for (auto* input : {&tickInput.movement, &tickInput.action}) {
        const auto delivered =
            input->Flush([input](unsigned int key, bool down,
                                 std::uint64_t epoch) { return SendOwnedKey(*input, false, key, down, epoch); },
                         [] { return characterUpdates; });
        // Native delivery may have pumped a new frame, including cancellation
        // and a new action. Never run the superseded frame's remaining work.
        if (sequence != frame) return false;
        if (delivered.failed && delivered.epoch == input->Epoch()) {
            tickInput.result.reason = "input_route_unavailable";
            // The producer retains failed keyups and retries them. Rejection is
            // an action-level fact, not cancellation of unrelated tick sessions.
        }
    }
    tickInput.MovementFlushed(updatedCharacter, characterUpdates, currentNative.loginStage || currentNative.user == 0);
    if (tickInput.item.Pending()) {
        std::uint32_t context = 0;
        if (!ReadAt(0x00BE7918, context)) context = 0;
        const auto consumed = tickInput.item.Consume(
            previousState.characterKnown ? previousState.character.id : 0, sceneGeneration, context,
            [](const BeiDouBridge::NativeItemUse::Item& item) {
                useItem(reinterpret_cast<ClientContext*>(item.context), item.slot, static_cast<int>(item.itemId));
            });
        if (sequence != frame) return false;
        if (consumed == BeiDouBridge::NativeItemUse::Consumption::ContextChanged)
            tickInput.result.reason = "item_context_changed";
    }
    if (tickInput.skill.Pending() && tickInput.actionWindow) {
        BeiDouBridge::NativeSkillUse::Context context;
        context.character = previousState.character.id;
        context.user = currentNative.user;
        context.sceneGeneration = sceneGeneration;
        context.inputEpoch = tickInput.action.Epoch();
        context.now = GetTickCount64();
        context.updatedCharacter = updatedCharacter;
        context.characterUpdates = characterUpdates;
        context.facingKnown = previousState.facingKnown;
        context.facingLeft = previousState.facingLeft;
        const bool consumed = tickInput.skill.Consume(context, InvokeNativeSkill);
        if (sequence != frame) return false;
        tickInput.result.skill = tickInput.skill.Result();
        if (!consumed) {
            tickInput.result.reason = tickInput.result.skill.reason;
            tickInput.actionWindow = false;
            tickInput.action.Release();
        }
    }
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
    if (careTracking) {
        const auto view = CaptureCareView(&care.Request());
        care.ObserveCleanup(previousState, view);
        care.ConvergeCancellation(previousState, view, now, keyInput.Released() && mouseInput.Released());
        if (!care.Active() && !care.CleanupPending() && keyInput.Released() && mouseInput.Released()) {
            care.FinishScope();
            careTracking = false;
        }
    }

    // CallUpdate may return without advancing its 30ms character step. Confirm the actual consumer.
    const bool oldCharacterExited =
        native.loginStage || (native.field == 0 && native.stats == 0 && native.user == 0)
        || (previousState.characterKnown && previousState.positionKnown && native.user != keyInput.ReleaseCharacter());
    const bool oldMouseContextExited = native.loginStage || native.user == 0 || native.user != mouseInput.Character()
                                       || sceneGeneration != mouseInput.Scene();
    mouseInput.ConfirmRelease(updatedCharacter, characterUpdates, oldMouseContextExited);
    if (keyInput.ConfirmRelease(updatedCharacter, characterUpdates, oldCharacterExited)) {
        if (!pendingStatus.empty()) {
            commandStatus = pendingStatus;
            commandReason = pendingReason;
        }
        pendingStatus.clear();
        pendingReason.clear();
    }
    const bool ready = previousState.ready;
    if (attackWindow && (changed || !ready || previousState.character.values[6] == 0 || now >= attackWindowUntil)) {
        skillUse.Cancel(now >= attackWindowUntil ? "native_skill_expired" : "native_skill_context_changed");
        BeginRelease({}, {});
    }
    if (keyInput.Active() && (changed || !ready || previousState.character.values[6] == 0))
        BeginRelease({}, {});
    else if (keyInput.Active() && now >= keyInput.Deadline()) {
        if (careResult && care.Active())
            keyInput.Release();
        else
            BeginRelease({}, {});
    }
    if (!mouseInput.Released() && (changed || !ready || native.user != mouseInput.Character())) BeginRelease({}, {});

    const bool tickCharacterExited = native.loginStage || native.user == 0;
    tickInput.Observe(native.user, updatedCharacter, characterUpdates, tickCharacterExited);
    if ((changed || !ready || previousState.character.values[6] == 0)
        && (tickInput.movement.Active() || tickInput.actionWindow || tickInput.item.Pending()))
        tickAdapter.Release();
    tickInput.ExpireAction(now);

    ReadCommand();
    runtime.Tick(changed);
    tickRuntime.Tick(changed);
    if (!taskTransport->Tick(runtime, previousState)) runtime.Cancel("task_result_write_failed");
    if (care.Active()) {
        const auto view = CaptureCareView(&care.Request());
        care.Tick(
            previousState, view, now, keyInput.Released() && mouseInput.Released(),
            [now](const BeiDouBridge::NativeMouseInput::Target& target) { return mouseInput.Request(target, now); },
            [](unsigned intent) {
                std::string error;
                unsigned int key = 0;
                // Resolve V17 window menu actions through the current key map.
                careMenuAction = intent == 'S' ? 2 : intent == 'K' ? 3 : 1;
                return BindingKey(BeiDouBridge::NativeBindingType::Menu, careMenuAction, key, error)
                       && ApplyDesiredKeys({key}, 60, error);
            });
        if (!care.Active() && !keyInput.Released()) keyInput.Release();
        if ((!care.Active() || care.StopMouse()) && !mouseInput.Released()) mouseInput.Release();
    }
    if (careTracking && care.CleanupPending() && keyInput.Released() && !mouseInput.Held()) {
        const auto view = CaptureCareView(&care.Request());
        if (care.CanEscape(view)) {
            std::string error;
            care.EscapeSent();
            ApplyDesiredKeys({VK_ESCAPE}, 60, error);
        }
    }
    if (scriptCommand) {
        RefreshScriptStatuses();
        const auto session = std::find_if(scriptSessions.begin(), scriptSessions.end(), [](const ScriptSession& entry) {
            return entry.id == commandScriptId && entry.mode == commandScriptMode;
        });
        if (session != scriptSessions.end()) {
            const auto& status = CareField(session->status, "status").Text();
            if (status != "running") {
                commandStatus = status;
                commandReason = CareField(session->status, "reason").Text();
                scriptCommand = false;
            }
        }
    }
    if (stopCommand && !runtime.Running() && !tickRuntime.Running() && adapter.Released() && tickAdapter.Released()) {
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
            if (runtime.Running())
                runtime.Cancel("state_publish_failed");
            else if (keyInput.Active() || itemUse.Pending())
                BeginRelease({}, {});
            // This is a shared host transport failure, not a script failure.
            tickRuntime.CancelAll("state_publish_failed");
            tickAdapter.Release();
        }
        lastPublishedAt = now;
    }
    if (!DeliverTickInput()) return;
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
        return;
    }
    if (!mouseInput.Flush(now, SendMouse, [] { return characterUpdates; })) {
        if (care.Active())
            care.Cancel(previousState, CaptureCareView(&care.Request()), now, "care_mouse_delivery_failed", false);
        runtime.Cancel("native_mouse_failed");
        BeginRelease({}, {});
        return;
    }
    if (skillUse.Pending() && attackWindow) {
        if (keyInput.Held()[VK_LEFT] || keyInput.Held()[VK_RIGHT])
            skillUse.DirectionDelivered(keyInput.Epoch(), characterUpdates);
        BeiDouBridge::NativeSkillUse::Context context;
        context.character = previousState.character.id;
        context.user = currentNative.user;
        context.sceneGeneration = sceneGeneration;
        context.inputEpoch = keyInput.Epoch();
        context.now = GetTickCount64();
        context.updatedCharacter = updatedCharacter;
        context.characterUpdates = characterUpdates;
        context.facingKnown = previousState.facingKnown;
        context.facingLeft = previousState.facingLeft;
        const bool consumed = skillUse.Consume(context, InvokeNativeSkill);
        if (semanticResult.skillRequested) semanticResult.skill = skillUse.Result();
        if (!consumed) {
            semanticResult.reason = skillUse.Result().reason;
            runtime.Cancel("native_skill_failed");
            BeginRelease({}, {});
        }
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
bool BeginNativeAction(const MapleControl::Action& action, std::string& error) {
    semanticResult = MapleControl::ActionResult{};
    semanticResult.sessionId = action.sessionId;
    if (action.kind == MapleControl::ActionKind::Stop) {
        careResult = false;
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
    careResult = false;
    careTracking = false;
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
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 53, key, error)) return false;
        break;
    case MapleControl::ActionKind::Attack:
        if (action.skillId != 0) break;
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 52, key, error)) return false;
        break;
    case MapleControl::ActionKind::Pickup:
        if (!BindingKey(BeiDouBridge::NativeBindingType::Action, 50, key, error)) return false;
        break;
    case MapleControl::ActionKind::UseItem: {
        if (!RequestNativeItem(action.itemId, itemUse, error)) return false;
        itemResult = true;
        semanticResult.reason = "item_use_requested";
        return true;
    }
    case MapleControl::ActionKind::Unequip:
        error = "unsupported: unequip";
        return false;
    case MapleControl::ActionKind::Activate:
        error = "unsupported: activate";
        return false;
    case MapleControl::ActionKind::AllocateAp:
    case MapleControl::ActionKind::AllocateSp:
    case MapleControl::ActionKind::Equip:
    case MapleControl::ActionKind::Window: {
        std::uint32_t input = 0;
        if (!ReadAt(0x00BEC33C, input) || input == 0) {
            error = "input_route_unavailable";
            return false;
        }
        auto* nativeInput = reinterpret_cast<InputSystem*>(input);
        if (inputModifiers(nativeInput) != 0 || originalKeyPressed(nativeInput, VK_LBUTTON)
            || originalKeyPressed(nativeInput, VK_RBUTTON)) {
            error = "care_external_input_active";
            return false;
        }
        mouseInput.ResetReport();
        careKeyDispatched = false;
        careMenuAction = 0;
        careResult = care.Begin(action, previousState, CaptureCareView(&action), GetTickCount64());
        careTracking = careResult;
        if (!careResult) error = "care_action_in_progress";
        return careResult;
    }
    case MapleControl::ActionKind::Revive:
        error = "unsupported: revive";
        return false;
    case MapleControl::ActionKind::Stop:
        break;
    }
    std::vector<unsigned int> keys;
    if (key != 0) keys.push_back(key);
    if (action.kind == MapleControl::ActionKind::Attack && !action.direction.empty())
        keys.push_back(action.direction == "left" ? VK_LEFT : VK_RIGHT);
    if (!ApplyDesiredKeys(keys, duration, error)) return false;
    if (action.kind == MapleControl::ActionKind::Attack && action.skillId != 0) {
        attackWindow = true;
        attackWindowUntil = keys.empty() ? GetTickCount64() + duration : keyInput.Deadline();
        BeiDouBridge::NativeSkillUse::Skill request;
        request.skillId = action.skillId;
        request.character = currentState->character.id;
        request.user = currentNative.user;
        request.sceneGeneration = sceneGeneration;
        request.inputEpoch = keyInput.Epoch();
        request.deadline = attackWindowUntil;
        request.direction = action.direction.empty() ? 0 : action.direction == "left" ? -1 : 1;
        skillUse.Request(request);
        semanticResult.skillRequested = true;
        semanticResult.skill = skillUse.Result();
    }
    semanticResult.reason = "native_action_requested";
    return true;
}

MapleControl::ActionResult NativeResult() {
    if (careResult) {
        auto result = care.Result();
        result.dispatched = care.Request().kind == MapleControl::ActionKind::Window
                                ? mouseInput.Dispatched() || careKeyDispatched
                            : care.Request().kind == MapleControl::ActionKind::Equip ? mouseInput.EquipmentDispatched()
                                                                                     : mouseInput.PointDispatched();
        result.controlReleased = adapter.Released();
        return result;
    }
    auto result = semanticResult;
    result.dispatched = itemResult ? itemUse.Dispatched()
                                   : (keyInput.Dispatched() && result.reason != "already_facing")
                                         || (result.skillRequested && result.skill.nativeResultKnown);
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
    careResult = false;
    careTracking = false;
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
    const auto invocation = ++skillInvocationRevision;
    result = activeSkill(reinterpret_cast<ClientPlayer*>(player), static_cast<int>(skillId), 0, nullptr);
    if (invocation == skillInvocationRevision) {
        haveSkillResult = true;
        lastSkillId = skillId;
        lastSkillResult = result;
    }
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
