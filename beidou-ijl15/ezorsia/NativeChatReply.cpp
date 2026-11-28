// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Native whisper location reply.
//
// The client dispatches every decoded channel packet through one routine. The
// whisper opcode is part of the field packet set, so an incoming whisper passes
// that routine before the field handler. This module only reads the packet,
// recognizes the whisper-receive form, and answers a location question through
// the client's own send packet routine. It never changes the packet or the
// client's dispatch order.
#include "stdafx.h"
#include "NativeChatReply.h"
#include "AgentBridge.h"
#include "NativeChatQueue.h"
#include "NativeBuffs.h"
#include "NativeObservation.h"

#include "../../shared/img/ImgResources.h"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <sstream>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace BeiDouBridge {
namespace NativeChatReply {
namespace {

// Decoded packet view matching the client's CInPacket layout used by the
// existing receive hook. The decoded buffer starts with a four-byte channel
// frame header; the two-byte opcode follows it and the payload starts at
// Data + 6.
struct InPacket {
    bool loopback;
    int state;
    void* data;
    unsigned long size;
    unsigned short rawSeq;
    unsigned short dataLen;
    unsigned short unknown;
    unsigned int offset;
    void* unknownTail;
};

// Client V17 receive opcode verified by the existing receive hook.
constexpr unsigned short kWhisperReceiveOpcode = 0x0087;
constexpr unsigned char kWhisperReceiveFlag = 0x02 | 0x10; // whisper | receive

constexpr std::uint32_t kMinimumReplyIntervalMilliseconds = 1500;
constexpr std::size_t kLogLimitBytes = 1024 * 1024;

std::uint32_t lastReplyAt = 0;
bool repliedOnce = false;
// Summon flow: @过来 queues a location lookup, then the result is turned into a
// follow (same map) or a travel route (same channel, other map) on the next tick.
bool summonPending = false;
bool summonResultReady = false;
unsigned char summonResultType = 0;
std::uint32_t summonResultField = 0;
std::uint64_t summonRequestAt = 0;
std::string summonRequesterGbk;
std::string summonRequesterUtf8;
// Caller of the travel in progress, used to report the bot outcome later.
std::string summonCallerGbk;

std::string DataRoot() {
    std::array<char, MAX_PATH> value{};
    const DWORD length = GetEnvironmentVariableA("MAPLE_DATA_ROOT", value.data(), static_cast<DWORD>(value.size()));
    if (length == 0 || length >= value.size()) return {};
    return std::string(value.data(), length);
}

std::string BridgeDirectory() {
    std::array<char, MAX_PATH> value{};
    const DWORD length = GetEnvironmentVariableA("MAPLE_BRIDGE_DIR", value.data(), static_cast<DWORD>(value.size()));
    if (length == 0 || length >= value.size()) return {};
    return std::string(value.data(), length);
}

std::string GbkToUtf8(const std::string& text) {
    if (text.empty()) return {};
    const int wideCount =
        MultiByteToWideChar(936, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (wideCount <= 0) return {};
    std::wstring wide(wideCount, L'\0');
    MultiByteToWideChar(936, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), &wide[0], wideCount);
    const int utf8Count = WideCharToMultiByte(CP_UTF8, 0, wide.data(), wideCount, nullptr, 0, nullptr, nullptr);
    if (utf8Count <= 0) return {};
    std::string result(utf8Count, '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide.data(), wideCount, &result[0], utf8Count, nullptr, nullptr);
    return result;
}

std::string Utf8ToGbk(const std::string& text) {
    if (text.empty()) return {};
    const int wideCount =
        MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (wideCount <= 0) return {};
    std::wstring wide(wideCount, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), &wide[0], wideCount);
    const int gbkCount = WideCharToMultiByte(936, 0, wide.data(), wideCount, nullptr, 0, nullptr, nullptr);
    if (gbkCount <= 0) return {};
    std::string result(gbkCount, '\0');
    WideCharToMultiByte(936, 0, wide.data(), wideCount, &result[0], gbkCount, nullptr, nullptr);
    return result;
}

std::string Timestamp() {
    SYSTEMTIME now{};
    GetLocalTime(&now);
    std::array<char, 64> text{};
    sprintf_s(text.data(), text.size(), "%04d-%02d-%02d %02d:%02d:%02d.%03d", static_cast<int>(now.wYear),
              static_cast<int>(now.wMonth), static_cast<int>(now.wDay), static_cast<int>(now.wHour),
              static_cast<int>(now.wMinute), static_cast<int>(now.wSecond), static_cast<int>(now.wMilliseconds));
    return std::string(text.data());
}

void AppendLog(const std::string& line) {
    const std::string directory = BridgeDirectory();
    if (directory.empty()) return;
    const std::string path = directory + "\\chat.log";
    WIN32_FILE_ATTRIBUTE_DATA attributes{};
    if (GetFileAttributesExA(path.c_str(), GetFileExInfoStandard, &attributes) && attributes.nFileSizeHigh == 0
        && attributes.nFileSizeLow > kLogLimitBytes) {
        DeleteFileA(path.c_str());
    }
    HANDLE file = CreateFileA(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    const std::string record = line + "\r\n";
    DWORD written = 0;
    WriteFile(file, record.data(), static_cast<DWORD>(record.size()), &written, nullptr);
    CloseHandle(file);
}

struct MapNames {
    std::string mapName;
    std::string streetName;
};

// String/Map.img groups map ids under region nodes (victoria, ossyria, ...),
// so the map id node is a descendant of the image root, not a direct child.
bool FindMapNode(const BeidouImgDirectory* image, std::uint32_t first, std::uint32_t count, const std::string& key,
                 BeidouImgNodeInfo& found) {
    for (std::uint32_t index = first; index < first + count; ++index) {
        BeidouImgNodeInfo node{};
        if (!beidou_img_directory_node(image, index, &node)) continue;
        std::size_t nameLength = 0;
        const char* name = beidou_img_directory_string(image, node.name_string_id, &nameLength);
        if (name != nullptr && std::string(name, nameLength) == key) {
            found = node;
            return true;
        }
        if (node.type == BEIDOU_IMG_NODE_NONE && node.child_count > 0
            && FindMapNode(image, node.children, node.child_count, key, found))
            return true;
    }
    return false;
}

// Reads mapName/streetName from the local String/Map resource. The IMG decoder
// returns UTF-8 text. A missing resource, id or property yields an empty name
// and the caller falls back to the map id.
MapNames ReadMapNames(std::uint32_t mapId) {
    MapNames result;
    const std::string root = DataRoot();
    if (root.empty() || mapId == 0) {
        AppendLog(Timestamp() + " map name lookup skipped: data root or map id unavailable");
        return result;
    }
    const std::string path = root + "\\String\\Map.img";
    std::array<char, 512> message{};
    BeidouImgDirectory* opened = nullptr;
    if (!beidou_img_file_open(path.c_str(), &opened, message.data(), message.size())) {
        AppendLog(Timestamp() + " map name lookup failed: cannot open " + path + " :: " + std::string(message.data()));
        return result;
    }
    const std::unique_ptr<BeidouImgDirectory, decltype(&beidou_img_directory_close)> image(opened,
                                                                                           beidou_img_directory_close);
    BeidouImgNodeInfo imageRoot{};
    if (!beidou_img_directory_node(image.get(), 0, &imageRoot)) {
        AppendLog(Timestamp() + " map name lookup failed: image root unavailable");
        return result;
    }
    BeidouImgNodeInfo mapNode{};
    if (!FindMapNode(image.get(), imageRoot.children, imageRoot.child_count, std::to_string(mapId), mapNode)) {
        AppendLog(Timestamp() + " map name lookup failed: map id not found in " + path);
        return result;
    }
    for (std::uint32_t child = mapNode.children; child < mapNode.children + mapNode.child_count; ++child) {
        BeidouImgNodeInfo property{};
        if (!beidou_img_directory_node(image.get(), child, &property)) continue;
        if (property.type != BEIDOU_IMG_NODE_STRING) continue;
        std::size_t propertyNameLength = 0;
        const char* propertyName =
            beidou_img_directory_string(image.get(), property.name_string_id, &propertyNameLength);
        std::size_t valueLength = 0;
        const char* value = beidou_img_directory_string(image.get(), property.value_string_id, &valueLength);
        if (propertyName == nullptr || value == nullptr) continue;
        const std::string propertyString(propertyName, propertyNameLength);
        if (propertyString == "mapName")
            result.mapName.assign(value, valueLength);
        else if (propertyString == "streetName")
            result.streetName.assign(value, valueLength);
    }
    return result;
}

std::string MapDescription(std::uint32_t mapId) {
    static std::unordered_map<std::uint32_t, std::string> cache;
    const auto cached = cache.find(mapId);
    if (cached != cache.end()) return cached->second;
    const MapNames names = ReadMapNames(mapId);
    std::string description;
    if (!names.mapName.empty() && !names.streetName.empty() && names.streetName != names.mapName)
        description = names.mapName + " (" + names.streetName + ")";
    else if (!names.mapName.empty())
        description = names.mapName;
    else if (!names.streetName.empty())
        description = names.streetName;
    else
        description = "map " + std::to_string(mapId);
    cache[mapId] = description;
    return description;
}

// Reads one skill's display name from the local String/Skill resource. Names
// are cached per skill id; the IMG decoder returns UTF-8 text.
std::string ReadSkillName(std::uint32_t skillId) {
    static std::unordered_map<std::uint32_t, std::string> cache;
    const auto cached = cache.find(skillId);
    if (cached != cache.end()) return cached->second;
    std::string name;
    const std::string root = DataRoot();
    if (!root.empty() && skillId != 0) {
        const std::string path = root + "\\String\\Skill.img";
        std::array<char, 512> message{};
        BeidouImgDirectory* opened = nullptr;
        if (beidou_img_file_open(path.c_str(), &opened, message.data(), message.size())) {
            const std::unique_ptr<BeidouImgDirectory, decltype(&beidou_img_directory_close)> image(
                opened, beidou_img_directory_close);
            BeidouImgNodeInfo imageRoot{};
            BeidouImgNodeInfo skillNode{};
            if (beidou_img_directory_node(image.get(), 0, &imageRoot)
                && FindMapNode(image.get(), imageRoot.children, imageRoot.child_count, std::to_string(skillId),
                               skillNode)) {
                for (std::uint32_t child = skillNode.children; child < skillNode.children + skillNode.child_count;
                     ++child) {
                    BeidouImgNodeInfo property{};
                    if (!beidou_img_directory_node(image.get(), child, &property)) continue;
                    if (property.type != BEIDOU_IMG_NODE_STRING) continue;
                    std::size_t propertyNameLength = 0;
                    const char* propertyName =
                        beidou_img_directory_string(image.get(), property.name_string_id, &propertyNameLength);
                    std::size_t valueLength = 0;
                    const char* value =
                        beidou_img_directory_string(image.get(), property.value_string_id, &valueLength);
                    if (propertyName != nullptr && value != nullptr
                        && std::string(propertyName, propertyNameLength) == "name")
                        name.assign(value, valueLength);
                }
            }
        }
    }
    cache[skillId] = name;
    return name;
}

bool ContainsKeyword(const std::string& text, const char* keyword) {
    return text.find(keyword) != std::string::npos;
}

// Answers only questions about the local character's location. The bridge is
// built with /execution-charset:.936, so the Chinese keywords below are CP936
// bytes; match them against the raw CP936 message body instead of its UTF-8
// projection. ASCII matching ignores case so the keyword list stays small.
bool AsksLocation(const std::string& cp936) {
    // Only short lines can be a location question. Longer lines are ordinary
    // chat or help text that merely contains words like 位置/@位置 and must not
    // trigger a location reply.
    if (cp936.size() > 40) return false;
    static const char* const keywords[] = {"在哪", "哪里", "哪儿",  "什么地方", "什么图",    "哪张图",  "哪个图",
                                           "位置", "坐标", "where", "location", "which map", "what map"};
    std::string lowered = cp936;
    for (char& character : lowered)
        if (character >= 'A' && character <= 'Z') character = static_cast<char>(character - 'A' + 'a');
    for (const char* keyword : keywords) {
        std::string loweredKeyword(keyword);
        for (char& character : loweredKeyword)
            if (character >= 'A' && character <= 'Z') character = static_cast<char>(character - 'A' + 'a');
        if (ContainsKeyword(lowered, loweredKeyword.c_str())) return true;
    }
    return false;
}

bool ReadString(const unsigned char* data, std::size_t size, std::size_t& offset, std::string& value) {
    if (offset + 2 > size) return false;
    const std::size_t length =
        static_cast<std::size_t>(data[offset]) | (static_cast<std::size_t>(data[offset + 1]) << 8);
    offset += 2;
    if (offset + length > size) return false;
    value.assign(reinterpret_cast<const char*>(data + offset), length);
    offset += length;
    return true;
}

bool SendWhisper(const std::string& target, const std::string& message) {
    return NativeChatQueue::Enqueue(NativeChatQueue::Channel::Whisper, message, target);
}

// ---------------------------------------------------------------------------
// Chat commands: whispered lines starting with @ are parsed by the bridge.
// Read-only queries are answered directly; control commands are forwarded to
// the bot mailbox so the single tick controller stays the only actor.
// ---------------------------------------------------------------------------

std::string ReadFileText(const std::string& path) {
    HANDLE file = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return {};
    std::array<char, 16384> buffer{};
    DWORD read = 0;
    ReadFile(file, buffer.data(), static_cast<DWORD>(buffer.size() - 1), &read, nullptr);
    CloseHandle(file);
    return std::string(buffer.data(), read);
}

std::string ReadBotConfig(const char* key) {
    const std::string content = ReadFileText("Z:\\work\\bot\\config.conf");
    const std::string prefix = std::string(key) + "=";
    std::size_t start = content.find(prefix);
    if (start == std::string::npos) return {};
    start += prefix.size();
    std::size_t end = content.find_first_of("\r\n", start);
    if (end == std::string::npos) end = content.size();
    return content.substr(start, end - start);
}

std::string ReadBotStateText(const char* key) {
    const std::string content = ReadFileText("Z:\\work\\bot\\state.json");
    const std::string prefix = std::string("\"") + key + "\":\"";
    std::size_t start = content.find(prefix);
    if (start == std::string::npos) return {};
    start += prefix.size();
    std::size_t end = content.find('"', start);
    if (end == std::string::npos) return {};
    return content.substr(start, end - start);
}

std::uint64_t NowMilliseconds() {
    FILETIME time{};
    GetSystemTimeAsFileTime(&time);
    const auto ticks = (static_cast<std::uint64_t>(time.dwHighDateTime) << 32) | time.dwLowDateTime;
    return (ticks - 116444736000000000ULL) / 10000;
}

// Writes one bot mailbox command into the first free slot. Content is UTF-8 so
// the Lua bot can match the target name against observed players.
bool WriteBotCommand(const std::string& kind, const std::string& targetUtf8) {
    for (int slot = 1; slot <= 8; ++slot) {
        const std::string path = "Z:\\work\\bot\\queue\\slot" + std::to_string(slot) + ".cmd";
        WIN32_FILE_ATTRIBUTE_DATA attributes{};
        if (GetFileAttributesExA(path.c_str(), GetFileExInfoStandard, &attributes)) continue;
        if (GetFileAttributesExA((path + ".processing").c_str(), GetFileExInfoStandard, &attributes)) continue;
        std::string content =
            "id=chat_" + std::to_string(NowMilliseconds()) + "\nkind=" + kind + "\nttl=0\nsource=host\n";
        if (!targetUtf8.empty() && (kind == "follow" || kind == "travel")) content += "target=" + targetUtf8 + "\n";
        const std::string temporary = path + ".tmp";
        HANDLE file =
            CreateFileA(temporary.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file == INVALID_HANDLE_VALUE) return false;
        DWORD written = 0;
        WriteFile(file, content.data(), static_cast<DWORD>(content.size()), &written, nullptr);
        CloseHandle(file);
        if (!MoveFileExA(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING)) {
            DeleteFileA(temporary.c_str());
            return false;
        }
        return true;
    }
    return false;
}

const MapleControl::Value* Member(const MapleControl::Value& object, const char* key) {
    for (const auto& entry : object.Members())
        if (entry.first == key) return &entry.second;
    return nullptr;
}

// Generates /work/bot/route.summon.json from the native world-map route so the
// bot travel mode can walk the legs through the client's own portal map.
bool WriteSummonRoute(std::uint32_t from, std::uint32_t goal) {
    const auto observation =
        NativeObservation::WorldRoute(DataRoot(), static_cast<std::int64_t>(from), static_cast<std::int64_t>(goal));
    if (observation.status != "ok") return false;
    const auto* legs = Member(observation.data, "legs");
    if (legs == nullptr || legs->Type() != MapleControl::Value::Kind::Array) return false;
    std::ostringstream route;
    route << "{\"from\":" << from << ",\"goal\":" << goal << ",\"legs\":[";
    bool first = true;
    for (const auto& leg : legs->Elements()) {
        const auto* map = Member(leg, "from");
        const auto* portal = Member(leg, "portal");
        const auto* portalAt = Member(leg, "portal_at");
        if (map == nullptr || portal == nullptr || portalAt == nullptr) return false;
        if (portalAt->Elements().empty() || portalAt->Elements()[0].Elements().size() < 2) return false;
        const auto& point = portalAt->Elements()[0].Elements();
        if (!first) route << ",";
        first = false;
        route << "{\"map\":" << static_cast<std::uint32_t>(map->Number()) << ",\"portal\":\"" << portal->Text()
              << "\",\"x\":" << static_cast<int>(point[0].Number()) << ",\"y\":" << static_cast<int>(point[1].Number())
              << "}";
    }
    route << "]}";
    const std::string path = "Z:\\work\\bot\\route.summon.json";
    HANDLE file = CreateFileA(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    const std::string content = route.str();
    DWORD written = 0;
    const bool complete = WriteFile(file, content.data(), static_cast<DWORD>(content.size()), &written, nullptr) != 0
                          && written == content.size();
    CloseHandle(file);
    return complete;
}

// Experience needed to reach the next level (server ExpTable, V0.83). The index
// is the current level; the server caps the requirement above level 200.
const std::uint32_t kExpTable[] = {
    15,         15,         34,         57,         92,         135,        372,        560,        840,
    1144,       1242,       1573,       2144,       2800,       3640,       4700,       5893,       7360,
    9144,       11120,      13477,      16268,      19320,      22880,      27008,      31477,      36600,
    42444,      48720,      55813,      63800,      86784,      98208,      110932,     124432,     139372,
    155865,     173280,     192400,     213345,     235372,     259392,     285532,     312928,     342624,
    374760,     408336,     445544,     483532,     524160,     567772,     598886,     631704,     666321,
    702836,     741351,     781976,     824828,     870028,     917625,     967995,     1021041,    1076994,
    1136013,    1198266,    1263930,    1333194,    1406252,    1483314,    1564600,    1650340,    1740778,
    1836173,    1936794,    2042930,    2154882,    2272970,    2397528,    2528912,    2667496,    2813674,
    2967863,    3130502,    3302053,    3483005,    3673873,    3875201,    4087562,    4311559,    4547832,
    4797053,    5059931,    5337215,    5629694,    5938202,    6263614,    6606860,    6968915,    7350811,
    7753635,    8178534,    8626718,    9099462,    9598112,    10124088,   10678888,   11264090,   11881362,
    12532461,   13219239,   13943653,   14707765,   15513750,   16363902,   17260644,   18206527,   19204245,
    20256637,   21366700,   22537594,   23772654,   25075395,   26449526,   27898960,   29427822,   31040466,
    32741483,   34535716,   36428273,   38424542,   40530206,   42751262,   45094030,   47565183,   50171755,
    52921167,   55821246,   58880250,   62106888,   65510344,   69100311,   72887008,   76881216,   81094306,
    85594273,   90225770,   95170142,   100385466,  105886589,  111689174,  117809740,  124265714,  131075474,
    138258410,  145834970,  153826726,  162256430,  171148082,  180526997,  190419876,  200854885,  211861732,
    223471711,  223471711,  248635353,  262260570,  276632449,  291791906,  307782102,  324648562,  342439302,
    361204976,  380999008,  401877754,  423900654,  447130410,  471633156,  497478653,  524740482,  553496261,
    583827855,  615821622,  649568646,  685165008,  722712050,  762316670,  804091623,  848155844,  894634784,
    943660770,  995373379,  1049919840, 1107455447, 1168144006, 1232158297, 1299680571, 1370903066, 1446028554,
    1525246918, 1608855764, 1697021059,
};

// Formats the experience percentage with two decimals, e.g. "36.75".
std::string ExperiencePercent(std::uint32_t level, std::uint32_t experience) {
    constexpr std::size_t count = sizeof(kExpTable) / sizeof(kExpTable[0]);
    if (level >= count) return {};
    const std::uint32_t needed = kExpTable[level];
    if (needed == 0) return {};
    std::uint64_t scaled = static_cast<std::uint64_t>(experience) * 10000 / needed;
    if (scaled > 10000) scaled = 10000;
    const std::string fraction = scaled % 100 < 10 ? "0" + std::to_string(scaled % 100) : std::to_string(scaled % 100);
    return std::to_string(scaled / 100) + "." + fraction;
}

// Returns true when the whisper was a chat command and has been handled.
// Chinese command words below are CP936 literals (bridge execution charset) and
// are compared against the raw CP936 message body; English aliases are lowercased.
bool HandleChatCommand(const std::string& sender, const std::string& message, const std::string& senderUtf8) {
    if (message.size() < 2 || message[0] != '@') return false;
    std::string command = message.substr(1);
    while (!command.empty()
           && (command.back() == ' ' || command.back() == '\r' || command.back() == '\n' || command.back() == '\t'))
        command.pop_back();
    // The verb is the first token; a trailing token is an optional argument
    // (only follow uses one: the player to follow).
    const std::size_t space = command.find(' ');
    std::string verb = space == std::string::npos ? command : command.substr(0, space);
    std::string argument = space == std::string::npos ? std::string() : command.substr(space + 1);
    std::size_t argumentBegin = 0;
    while (argumentBegin < argument.size() && (argument[argumentBegin] == ' ' || argument[argumentBegin] == '\t'))
        ++argumentBegin;
    argument = argument.substr(argumentBegin);
    while (!argument.empty() && (argument.back() == ' ' || argument.back() == '\t')) argument.pop_back();
    std::string lowered = verb;
    for (char& character : lowered)
        if (character >= 'A' && character <= 'Z') character = static_cast<char>(character - 'A' + 'a');
    const auto reply = [&](const std::string& gbkText) {
        if (!gbkText.empty()) SendWhisper(sender, gbkText);
    };
    const std::uint32_t mapId = AgentBridge::CurrentMapId();
    if (verb == "位置" || lowered == "where") {
        reply("我在" + Utf8ToGbk(MapDescription(mapId)));
        AppendLog(Timestamp() + " chat command from " + senderUtf8 + ": where");
        return true;
    }
    if (verb == "状态" || lowered == "status" || lowered == "state") {
        // 状态分多条回复：单条悄悄话有长度上限，队列会自动按间隔发送。
        const std::string mode = ReadBotStateText("mode");
        const auto stats = AgentBridge::CurrentCharacterStats();
        std::string head =
            "模式 " + (mode.empty() ? std::string("未知") : mode) + " 地图 " + Utf8ToGbk(MapDescription(mapId));
        if (stats.known)
            head += " HP " + std::to_string(stats.hp) + "/" + std::to_string(stats.maxHp) + " MP "
                    + std::to_string(stats.mp) + "/" + std::to_string(stats.maxMp);
        reply(head);
        std::string progress = "等级 " + std::to_string(stats.level) + " 经验 " + std::to_string(stats.experience);
        const std::string percent = ExperiencePercent(stats.level, stats.experience);
        if (!percent.empty()) progress += " (" + percent + "%)";
        const auto character = NativeObservation::Collect("character");
        if (character.status == "ok") {
            const auto* mesos = Member(character.data, "mesos");
            if (mesos != nullptr && mesos->Type() == MapleControl::Value::Kind::Number)
                progress += " 金币 " + std::to_string(static_cast<std::uint64_t>(mesos->Number()));
            else
                progress += " 金币 未知";
        } else {
            progress += " 金币 未知";
        }
        reply(progress);
        const auto inventory = NativeObservation::Collect("inventory");
        if (inventory.status == "ok") {
            std::uint32_t capacity = 0;
            std::uint32_t consumed = 0;
            std::uint32_t potions = 0;
            std::uint32_t ammo = 0;
            const auto* capacities = Member(inventory.data, "capacities");
            if (capacities != nullptr) {
                const auto* capacity2 = Member(*capacities, "2");
                if (capacity2 != nullptr && capacity2->Type() == MapleControl::Value::Kind::Number)
                    capacity = static_cast<std::uint32_t>(capacity2->Number());
            }
            const auto* items = Member(inventory.data, "items");
            if (items != nullptr && items->Type() == MapleControl::Value::Kind::Array) {
                for (const auto& item : items->Elements()) {
                    const auto* type = Member(item, "inventory_type");
                    const auto* identifier = Member(item, "item_id");
                    if (type == nullptr || identifier == nullptr) continue;
                    if (static_cast<std::uint32_t>(type->Number()) != 2) continue;
                    ++consumed;
                    const auto id = static_cast<std::uint32_t>(identifier->Number());
                    const auto* quantity = Member(item, "quantity");
                    const auto count = quantity != nullptr && quantity->Type() == MapleControl::Value::Kind::Number
                                           ? static_cast<std::uint32_t>(quantity->Number())
                                           : 1;
                    if (id >= 2000000 && id < 2060000)
                        potions += count;
                    else if (id >= 2060000 && id < 2080000)
                        ammo += count;
                }
            }
            reply("背包 消耗 " + std::to_string(consumed) + "/" + std::to_string(capacity) + " 药品 "
                  + std::to_string(potions) + " 弹药 " + std::to_string(ammo));
        } else {
            reply("背包观察不可用");
        }
        reply(BeiDouBridge::NativeBuffs::Summary());
        reply("点券暂不支持观察");
        AppendLog(Timestamp() + " chat command from " + senderUtf8 + ": status");
        return true;
    }
    if (verb == "帮助" || lowered == "help") {
        // The server rejects whispers over 127 characters, so one line cannot
        // carry every command with its usage; the shared queue paces the parts.
        reply("指令：@位置 @状态 @技能 @帮助 @跟随 @过来 @打猎 @停止");
        reply("用法：@跟随 [玩家名] 省略跟随你；@过来 跨图召唤；动作类仅主人可用");
        AppendLog(Timestamp() + " chat command from " + senderUtf8 + ": help");
        return true;
    }
    if (verb == "技能" || lowered == "skill" || lowered == "skills") {
        const auto stats = AgentBridge::CurrentCharacterStats();

        struct LearnedSkill {
            std::uint32_t id = 0;
            std::uint32_t level = 0;
        };

        std::vector<LearnedSkill> learned;
        const auto character = NativeObservation::Collect("character");
        if (character.status == "ok") {
            const auto* skills = Member(character.data, "skills");
            if (skills != nullptr && skills->Type() == MapleControl::Value::Kind::Object) {
                for (const auto& member : skills->Members()) {
                    const auto id = static_cast<std::uint32_t>(std::strtoul(member.first.c_str(), nullptr, 10));
                    if (id == 0) continue;
                    // Beginner skills sit in the job-0 segment (e.g. 1000xxx);
                    // only first to fourth job skills are reported.
                    if (id / 10000 == 0) continue;
                    const auto* level = Member(member.second, "level");
                    if (level == nullptr || level->Type() != MapleControl::Value::Kind::Number) continue;
                    learned.push_back({id, static_cast<std::uint32_t>(level->Number())});
                }
            }
        }
        std::sort(learned.begin(), learned.end(),
                  [](const LearnedSkill& left, const LearnedSkill& right) { return left.id < right.id; });
        reply("技能点 " + std::to_string(stats.skillPoints) + " 已学 " + std::to_string(learned.size()) + " 个");
        if (learned.empty()) {
            reply("暂无转职技能");
        } else {
            std::string line;
            for (const auto& skill : learned) {
                std::string name = Utf8ToGbk(ReadSkillName(skill.id));
                if (name.empty()) name = "技能" + std::to_string(skill.id);
                const std::string entry = name + " Lv." + std::to_string(skill.level);
                if (line.empty()) {
                    line = entry;
                } else if (line.size() + entry.size() + 3 > 100) {
                    reply(line);
                    line = entry;
                } else {
                    line += "、" + entry;
                }
            }
            if (!line.empty()) reply(line);
        }
        AppendLog(Timestamp() + " chat command from " + senderUtf8 + ": skills");
        return true;
    }

    if (verb == "过来" || lowered == "come" || lowered == "summon") {
        const std::string owner = ReadBotConfig("owner_name");
        if (!owner.empty() && owner != senderUtf8) {
            reply("只有主人可以召唤我");
            AppendLog(Timestamp() + " summon rejected from non-owner " + senderUtf8);
            return true;
        }
        if (summonPending) {
            reply("正在处理上一个召唤请求");
            return true;
        }
        if (!NativeChatQueue::Enqueue(NativeChatQueue::Channel::Find, sender)) {
            reply("召唤请求排队失败");
            return true;
        }
        summonPending = true;
        summonRequestAt = GetTickCount64();
        summonRequesterGbk = sender;
        summonRequesterUtf8 = senderUtf8;
        AppendLog(Timestamp() + " summon: location lookup for " + senderUtf8);
        return true;
    }
    const char* kind = nullptr;
    std::string label;
    if (verb == "跟随" || lowered == "follow" || lowered == "come") {
        kind = "follow";
        label = "跟随";
    } else if (verb == "打猎" || lowered == "hunt") {
        kind = "hunt";
        label = "打猎";
    } else if (verb == "停止" || lowered == "stop" || verb == "停下" || lowered == "stay") {
        // 停下 and stay are kept as compatible aliases; both mean stop and wait.
        kind = "stop";
        label = "停止";
    }
    if (kind == nullptr) {
        reply("未知指令，发送 @帮助 查看");
        AppendLog(Timestamp() + " chat command from " + senderUtf8 + " unknown: " + command);
        return true;
    }
    const std::string owner = ReadBotConfig("owner_name");
    // owner_name 为空表示不限制（任何私聊均可触发操作指令）；非空时只接受该角色名。
    if (!owner.empty() && owner != senderUtf8) {
        reply("只有主人可以下达操作指令");
        AppendLog(Timestamp() + " chat command rejected from non-owner " + senderUtf8);
        return true;
    }
    std::string target = senderUtf8;
    if (kind == std::string("follow") && !argument.empty()) {
        const std::string nameUtf8 = GbkToUtf8(argument);
        if (!nameUtf8.empty()) target = nameUtf8;
    }
    if (!WriteBotCommand(kind, target)) {
        reply("指令队列已满，稍后重试");
        AppendLog(Timestamp() + " chat command failed: mailbox full for " + senderUtf8);
        return true;
    }
    if (kind == std::string("follow") && target != senderUtf8)
        reply("收到：" + label + " " + Utf8ToGbk(target));
    else
        reply("收到：" + label);
    AppendLog(Timestamp() + " chat command from " + senderUtf8 + ": " + kind);
    return true;
}

void HandleReceiveWhisper(const unsigned char* data, std::size_t size) {
    std::size_t offset = 6;
    if (offset >= size) return;
    const unsigned char flag = data[offset];
    offset += 1;
    if (flag != kWhisperReceiveFlag) return;
    std::string sender;
    if (!ReadString(data, size, offset, sender)) return;
    if (offset + 2 > size) return;
    offset += 2; // channel and admin flag; not needed for the reply
    std::string message;
    if (!ReadString(data, size, offset, message)) return;
    const std::string senderUtf8 = GbkToUtf8(sender);
    const std::string messageUtf8 = GbkToUtf8(message);
    AppendLog(Timestamp() + " whisper from " + (senderUtf8.empty() ? sender : senderUtf8) + ": " + messageUtf8);
    if (!senderUtf8.empty() && HandleChatCommand(sender, message, senderUtf8)) return;
    if (!AsksLocation(message)) return;
    const std::uint32_t mapId = AgentBridge::CurrentMapId();
    if (mapId == 0) {
        AppendLog(Timestamp() + " location reply skipped: current map unknown");
        return;
    }
    const std::uint32_t now = static_cast<std::uint32_t>(GetTickCount());
    if (repliedOnce && now - lastReplyAt < kMinimumReplyIntervalMilliseconds) {
        AppendLog(Timestamp() + " location reply skipped: rate limited");
        return;
    }
    // The literal prefix is CP936 at build time; the map text from the IMG
    // decoder is UTF-8, so convert that half and concatenate CP936 bytes.
    const std::string description = Utf8ToGbk(MapDescription(mapId));
    if (description.empty()) {
        AppendLog(Timestamp() + " location reply skipped: map name encoding failed");
        return;
    }
    const std::string replyGbk = "我在" + description;
    if (!SendWhisper(sender, replyGbk)) {
        AppendLog(Timestamp() + " location reply skipped: send failed");
        return;
    }
    lastReplyAt = now;
    repliedOnce = true;
    AppendLog(Timestamp() + " location reply sent to " + senderUtf8 + ": " + GbkToUtf8(replyGbk) + " [map "
              + std::to_string(mapId) + "]");
}

void HandleLocationResult(const unsigned char* data, std::size_t size) {
    if (!summonPending || summonResultReady) return;
    std::size_t offset = 7;
    std::string name;
    if (!ReadString(data, size, offset, name)) return;
    if (offset + 5 > size) return;
    const unsigned char type = data[offset];
    offset += 1;
    std::uint32_t field = 0;
    std::memcpy(&field, data + offset, sizeof(field));
    summonResultType = type;
    summonResultField = field;
    summonResultReady = true;
    AppendLog(Timestamp() + " summon: location result type=" + std::to_string(type) + " field "
              + std::to_string(field));
}

} // namespace

void OnPacket(void* packet) {
    if (packet == nullptr) return;
    const auto* incoming = static_cast<const InPacket*>(packet);
    if (incoming->data == nullptr || incoming->size < 8) return;
    const auto* data = static_cast<const unsigned char*>(incoming->data);
    unsigned short opcode = 0;
    std::memcpy(&opcode, data + 4, sizeof(opcode));
    if (opcode != kWhisperReceiveOpcode) return;
    if (incoming->size < 7) return;
    if (data[6] == 0x09) {
        __try {
            HandleLocationResult(data, static_cast<std::size_t>(incoming->size));
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            return;
        }
        return;
    }
    __try {
        HandleReceiveWhisper(data, static_cast<std::size_t>(incoming->size));
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return;
    }
}

std::string TrimText(std::string text) {
    while (!text.empty() && (text.back() == '\r' || text.back() == '\n' || text.back() == ' ' || text.back() == '\t'))
        text.pop_back();
    std::size_t begin = 0;
    while (begin < text.size() && (text[begin] == ' ' || text[begin] == '\t')) ++begin;
    return text.substr(begin);
}

std::string SummonFailureText(const std::string& reason) {
    if (reason == "landing_mismatch") return "路线中的跳跃点无法通过";
    if (reason == "unexpected_map") return "路线经过的地图不符合预期";
    if (reason == "route_missing" || reason == "route_unavailable") return "路线数据不可用";
    if (reason == "world_unavailable") return "当前游戏状态不可用";
    return reason;
}

// Reports the bot's travel outcome (written to summon-result.txt) to the caller.
void ReportSummonOutcome() {
    const std::string path = "Z:\\work\\bot\\summon-result.txt";
    WIN32_FILE_ATTRIBUTE_DATA attributes{};
    if (!GetFileAttributesExA(path.c_str(), GetFileExInfoStandard, &attributes)) return;
    const std::string reason = TrimText(ReadFileText(path));
    DeleteFileA(path.c_str());
    if (summonCallerGbk.empty()) return;
    if (reason == "arrived") {
        SendWhisper(summonCallerGbk, "我已经到你身边了");
        AppendLog(Timestamp() + " summon: arrived, caller notified");
    } else {
        SendWhisper(summonCallerGbk, "召唤失败：" + SummonFailureText(reason));
        AppendLog(Timestamp() + " summon: travel failed, reason " + reason);
    }
    summonCallerGbk.clear();
}

void Tick() {
    ReportSummonOutcome();
    if (summonPending && !summonResultReady && GetTickCount64() - summonRequestAt > 8000) {
        summonPending = false;
        SendWhisper(summonRequesterGbk, "无法确认你的位置（查询超时）");
        AppendLog(Timestamp() + " summon: location lookup timed out for " + summonRequesterUtf8);
        summonRequesterGbk.clear();
        summonRequesterUtf8.clear();
        return;
    }
    if (!summonResultReady) return;
    summonResultReady = false;
    summonPending = false;
    const std::string requesterGbk = summonRequesterGbk;
    const std::string requesterUtf8 = summonRequesterUtf8;
    summonRequesterGbk.clear();
    summonRequesterUtf8.clear();
    const auto reply = [&](const std::string& gbk) {
        if (!gbk.empty()) SendWhisper(requesterGbk, gbk);
    };
    const std::uint32_t currentMap = AgentBridge::CurrentMapId();
    if (summonResultType == 1) {
        // Same channel: field is the requester's map id.
        const std::uint32_t targetMap = summonResultField;
        if (targetMap == currentMap) {
            if (WriteBotCommand("follow", requesterUtf8))
                reply("我就在你旁边，开始跟随");
            else
                reply("指令队列已满，稍后重试");
            AppendLog(Timestamp() + " summon: requester on same map, follow queued for " + requesterUtf8);
        } else if (WriteSummonRoute(currentMap, targetMap)) {
            if (WriteBotCommand("travel", requesterUtf8)) {
                summonCallerGbk = requesterGbk;
                reply("你在地图 " + std::to_string(targetMap) + "（" + Utf8ToGbk(MapDescription(targetMap))
                      + "），正在前往");
                AppendLog(Timestamp() + " summon: travel queued to map " + std::to_string(targetMap));
            } else {
                reply("指令队列已满，稍后重试");
            }
        } else {
            reply("无法找到从当前地图到你的路线");
            AppendLog(Timestamp() + " summon: no route from " + std::to_string(currentMap) + " to "
                      + std::to_string(targetMap));
        }
    } else if (summonResultType == 3) {
        reply("你在另一个频道，跨频道无法寻路，请来到我所在的频道");
        AppendLog(Timestamp() + " summon: requester on another channel");
    } else if (summonResultType == 0) {
        reply("你在交易中心，无法寻路");
        AppendLog(Timestamp() + " summon: requester in ITC");
    } else if (summonResultType == 2) {
        reply("你在现金商店，无法寻路");
        AppendLog(Timestamp() + " summon: requester in cash shop");
    } else {
        reply("无法确认你的位置");
        AppendLog(Timestamp() + " summon: unknown location result type " + std::to_string(summonResultType));
    }
}

} // namespace NativeChatReply
} // namespace BeiDouBridge
