// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Local temporary-stat (buff) tracking.
//
// The server sends GIVE_BUFF (0x20) with two 64-bit stat masks followed by one
// value/buff-id/duration triple per set stat, in BuffStat declaration order, and
// CANCEL_BUFF (0x21) with the same masks. Reading those packets gives the bot
// its own buffs, which are otherwise not observable from the client state.
#include "stdafx.h"
#include "NativeBuffs.h"

#include <cstring>
#include <mutex>
#include <string>
#include <vector>

namespace BeiDouBridge {
namespace NativeBuffs {
namespace {

struct BuffStatDef {
    const char* name;
    const char* label;
    std::uint64_t value;
    bool first;
};

// BuffStat declaration order from the server's BuffStat.java; duplicate mask
// values are read once because the packet cannot distinguish them.
const BuffStatDef kBuffStats[] = {
    {"MORPH", "变身", 0x0000000000000002ULL, true},
    {"RECOVERY", "恢复", 0x0000000000000004ULL, true},
    {"MAPLE_WARRIOR", "冒险岛勇士", 0x0000000000000008ULL, true},
    {"STANCE", "稳如泰山", 0x0000000000000010ULL, true},
    {"SHARP_EYES", "鹰眼", 0x0000000000000020ULL, true},
    {"MANA_REFLECTION", "魔力反射", 0x0000000000000040ULL, true},
    {"SHADOW_CLAW", "SHADOW_CLAW", 0x0000000000000100ULL, true},
    {"INFINITY", "无限", 0x0000000000000200ULL, true},
    {"HOLY_SHIELD", "神圣护盾", 0x0000000000000400ULL, true},
    {"HAMSTRING", "断筋", 0x0000000000000800ULL, true},
    {"BLIND", "致盲", 0x0000000000001000ULL, true},
    {"CONCENTRATE", "集中", 0x0000000000002000ULL, true},
    {"PUPPET", "替身", 0x0000000000004000ULL, true},
    {"ECHO_OF_HERO", "英雄回声", 0x0000000000008000ULL, true},
    {"MESO_UP_BY_ITEM", "金币术", 0x0000000000010000ULL, true},
    {"GHOST_MORPH", "GHOST_MORPH", 0x0000000000020000ULL, true},
    {"AURA", "灵气", 0x0000000000040000ULL, true},
    {"CONFUSE", "CONFUSE", 0x0000000000080000ULL, true},
    {"COUPON_EXP1", "经验加成", 0x0000000000100000ULL, true},
    {"EXP_BUFF", "经验加成", 0x0000000040000000ULL, true},
    {"COUPON_EXP2", "经验加成", 0x0000000000200000ULL, true},
    {"COUPON_EXP3", "经验加成", 0x0000000000400000ULL, true},
    {"COUPON_DRP1", "掉落率", 0x0000000000800000ULL, true},
    {"COUPON_DRP2", "掉落率", 0x0000000001000000ULL, true},
    {"ITEM_UP_BY_ITEM", "道具掉落", 0x0000000000100000ULL, true},
    {"RESPECT_PIMMUNE", "RESPECT_PIMMUNE", 0x0000000000200000ULL, true},
    {"RESPECT_MIMMUNE", "RESPECT_MIMMUNE", 0x0000000000400000ULL, true},
    {"DEFENSE_ATT", "防御攻击", 0x0000000000800000ULL, true},
    {"DEFENSE_STATE", "防御状态", 0x0000000001000000ULL, true},
    {"HPREC", "HP恢复", 0x0000000002000000ULL, true},
    {"MPREC", "MP恢复", 0x0000000004000000ULL, true},
    {"BERSERK_FURY", "狂暴", 0x0000000008000000ULL, true},
    {"DIVINE_BODY", "神圣之躯", 0x0000000010000000ULL, true},
    {"SPARK", "火花", 0x0000000020000000ULL, true},
    {"MAP_CHAIR", "椅子", 0x0000000040000000ULL, true},
    {"FINALATTACK", "终极攻击", 0x0000000080000000ULL, true},
    {"WATK", "攻击力", 0x0000000100000000ULL, true},
    {"WDEF", "防御力", 0x0000000200000000ULL, true},
    {"MATK", "魔攻", 0x0000000400000000ULL, true},
    {"MDEF", "魔防", 0x0000000800000000ULL, true},
    {"ACC", "命中", 0x0000001000000000ULL, true},
    {"AVOID", "回避", 0x0000002000000000ULL, true},
    {"HANDS", "命中", 0x0000004000000000ULL, true},
    {"SPEED", "移动速度", 0x0000008000000000ULL, true},
    {"JUMP", "跳跃", 0x0000010000000000ULL, true},
    {"MAGIC_GUARD", "魔法盾", 0x0000020000000000ULL, true},
    {"DARKSIGHT", "暗器", 0x0000040000000000ULL, true},
    {"BOOSTER", "加速", 0x0000080000000000ULL, true},
    {"POWERGUARD", "稳如泰山", 0x0000100000000000ULL, true},
    {"HYPERBODYHP", "力量激发", 0x0000200000000000ULL, true},
    {"HYPERBODYMP", "魔力激发", 0x0000400000000000ULL, true},
    {"INVINCIBLE", "无敌", 0x0000800000000000ULL, true},
    {"SOULARROW", "灵魂之箭", 0x0001000000000000ULL, true},
    {"STUN", "STUN", 0x0002000000000000ULL, true},
    {"POISON", "POISON", 0x0004000000000000ULL, true},
    {"SEAL", "SEAL", 0x0008000000000000ULL, true},
    {"DARKNESS", "DARKNESS", 0x0010000000000000ULL, true},
    {"COMBO", "连击", 0x0020000000000000ULL, true},
    {"SUMMON", "SUMMON", 0x0020000000000000ULL, true},
    {"WK_CHARGE", "属性攻击", 0x0040000000000000ULL, true},
    {"DRAGONBLOOD", "龙之血", 0x0080000000000000ULL, true},
    {"HOLY_SYMBOL", "神圣祈祷", 0x0100000000000000ULL, true},
    {"MESOUP", "金钱提升", 0x0200000000000000ULL, true},
    {"SHADOWPARTNER", "影子伙伴", 0x0400000000000000ULL, true},
    {"PICKPOCKET", "扒窃", 0x0800000000000000ULL, true},
    {"MESOGUARD", "金钱护盾", 0x1000000000000000ULL, true},
    {"EXP_INCREASE", "经验增加", 0x2000000000000000ULL, true},
    {"WEAKEN", "虚弱", 0x4000000000000000ULL, true},
    {"MAP_PROTECTION", "地图保护", 0x8000000000000000ULL, true},
    {"SLOW", "减速", 0x0000000200000000ULL, false},
    {"ELEMENTAL_RESET", "元素重置", 0x0000000200000000ULL, false},
    {"MAGIC_SHIELD", "魔法盾", 0x0000000400000000ULL, false},
    {"MAGIC_RESISTANCE", "魔法抵抗", 0x0000000800000000ULL, false},
    {"WIND_WALK", "疾风步", 0x0000000400000000ULL, false},
    {"ARAN_COMBO", "连击", 0x0000001000000000ULL, false},
    {"COMBO_DRAIN", "连击吸血", 0x0000002000000000ULL, false},
    {"COMBO_BARRIER", "连击屏障", 0x0000004000000000ULL, false},
    {"BODY_PRESSURE", "身体压制", 0x0000008000000000ULL, false},
    {"SMART_KNOCKBACK", "击退", 0x0000010000000000ULL, false},
    {"BERSERK", "狂暴", 0x0000020000000000ULL, false},
    {"ENERGY_CHARGE", "能量充能", 0x0004000000000000ULL, false},
    {"DASH2", "冲刺", 0x0008000000000000ULL, false},
    {"DASH", "冲刺", 0x0010000000000000ULL, false},
    {"MONSTER_RIDING", "骑乘", 0x0020000000000000ULL, false},
    {"SPEED_INFUSION", "加速", 0x0040000000000000ULL, false},
    {"HOMING_BEACON", "追踪", 0x0080000000000000ULL, false},
};

constexpr unsigned short kGiveBuffOpcode = 0x0020;
constexpr unsigned short kCancelBuffOpcode = 0x0021;
constexpr std::size_t kMaxSummaryLabels = 4;

struct BuffEntry {
    std::string name;
    std::string label;
    std::uint32_t buffId = 0;
    std::uint32_t durationMs = 0;
    std::uint64_t startedAt = 0;
    int value = 0;
};

std::mutex cacheMutex;
std::vector<BuffEntry> cachedBuffs;

std::uint64_t NowMilliseconds() {
    FILETIME time{};
    GetSystemTimeAsFileTime(&time);
    const auto ticks = (static_cast<std::uint64_t>(time.dwHighDateTime) << 32) | time.dwLowDateTime;
    return (ticks - 116444736000000000ULL) / 10000;
}

bool ReadU8(const unsigned char* data, std::size_t size, std::size_t& offset, unsigned char& value) {
    if (offset + 1 > size) return false;
    value = data[offset];
    offset += 1;
    return true;
}

bool ReadU16(const unsigned char* data, std::size_t size, std::size_t& offset, std::uint16_t& value) {
    if (offset + 2 > size) return false;
    std::memcpy(&value, data + offset, sizeof(value));
    offset += 2;
    return true;
}

bool ReadU32(const unsigned char* data, std::size_t size, std::size_t& offset, std::uint32_t& value) {
    if (offset + 4 > size) return false;
    std::memcpy(&value, data + offset, sizeof(value));
    offset += 4;
    return true;
}

bool ReadU64(const unsigned char* data, std::size_t size, std::size_t& offset, std::uint64_t& value) {
    if (offset + 8 > size) return false;
    std::memcpy(&value, data + offset, sizeof(value));
    offset += 8;
    return true;
}

void HandleGiveBuff(const unsigned char* data, std::size_t size) {
    std::size_t offset = 6;
    std::uint64_t firstMask = 0;
    std::uint64_t secondMask = 0;
    if (!ReadU64(data, size, offset, firstMask) || !ReadU64(data, size, offset, secondMask)) return;
    const std::uint64_t now = NowMilliseconds();
    std::lock_guard<std::mutex> lock(cacheMutex);
    std::uint64_t seen = 0;
    for (const auto& definition : kBuffStats) {
        const std::uint64_t mask = definition.first ? firstMask : secondMask;
        if ((mask & definition.value) == 0) continue;
        if ((seen & definition.value) != 0) continue;
        seen |= definition.value;
        std::uint16_t value = 0;
        std::uint32_t buffId = 0;
        std::uint32_t duration = 0;
        if (!ReadU16(data, size, offset, value) || !ReadU32(data, size, offset, buffId)
            || !ReadU32(data, size, offset, duration))
            return;
        bool found = false;
        for (auto& buff : cachedBuffs) {
            if (buff.name == definition.name) {
                buff.buffId = buffId;
                buff.durationMs = duration;
                buff.startedAt = now;
                buff.value = value;
                found = true;
                break;
            }
        }
        if (!found)
            cachedBuffs.push_back(
                BuffEntry{definition.name, definition.label, buffId, duration, now, static_cast<int>(value)});
    }
}

void HandleCancelBuff(const unsigned char* data, std::size_t size) {
    std::size_t offset = 6;
    std::uint64_t firstMask = 0;
    std::uint64_t secondMask = 0;
    if (!ReadU64(data, size, offset, firstMask) || !ReadU64(data, size, offset, secondMask)) return;
    std::lock_guard<std::mutex> lock(cacheMutex);
    for (const auto& definition : kBuffStats) {
        const std::uint64_t mask = definition.first ? firstMask : secondMask;
        if ((mask & definition.value) == 0) continue;
        for (auto iterator = cachedBuffs.begin(); iterator != cachedBuffs.end();) {
            if (iterator->name == definition.name)
                iterator = cachedBuffs.erase(iterator);
            else
                ++iterator;
        }
    }
}

} // namespace

void OnPacket(void* packet) {
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

    auto* incoming = static_cast<InPacket*>(packet);
    if (incoming == nullptr || incoming->data == nullptr || incoming->size < 6) return;
    const auto* data = static_cast<const unsigned char*>(incoming->data);
    unsigned short opcode = 0;
    std::memcpy(&opcode, data + 4, sizeof(opcode));
    if (opcode != kGiveBuffOpcode && opcode != kCancelBuffOpcode) return;
    __try {
        if (opcode == kGiveBuffOpcode)
            HandleGiveBuff(data, static_cast<std::size_t>(incoming->size));
        else
            HandleCancelBuff(data, static_cast<std::size_t>(incoming->size));
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return;
    }
}

MapleControl::Value Snapshot() {
    const std::uint64_t now = NowMilliseconds();
    std::lock_guard<std::mutex> lock(cacheMutex);
    auto result = MapleControl::Value::Array();
    for (auto iterator = cachedBuffs.begin(); iterator != cachedBuffs.end();) {
        const std::uint64_t elapsed = now > iterator->startedAt ? now - iterator->startedAt : 0;
        if (iterator->durationMs != 0 && elapsed >= iterator->durationMs) {
            iterator = cachedBuffs.erase(iterator);
            continue;
        }
        const std::uint64_t remaining = iterator->durationMs != 0 ? iterator->durationMs - elapsed : 0;
        auto entry = MapleControl::Value::Object();
        entry["stat"] = iterator->name;
        entry["label"] = iterator->label;
        entry["value"] = iterator->value;
        entry["buff_id"] = iterator->buffId;
        entry["duration_ms"] = iterator->durationMs;
        entry["remaining_ms"] = static_cast<std::uint32_t>(remaining);
        result.Add(std::move(entry));
        ++iterator;
    }
    return result;
}

std::string Summary() {
    const std::uint64_t now = NowMilliseconds();
    std::lock_guard<std::mutex> lock(cacheMutex);
    std::string labels;
    std::size_t count = 0;
    for (const auto& buff : cachedBuffs) {
        const std::uint64_t elapsed = now > buff.startedAt ? now - buff.startedAt : 0;
        if (buff.durationMs != 0 && elapsed >= buff.durationMs) continue;
        ++count;
        if (labels.empty())
            labels = buff.label;
        else if (count <= kMaxSummaryLabels + 1)
            labels += "/" + buff.label;
    }
    std::string text = "buff " + std::to_string(count) + " 个";
    if (!labels.empty()) text += "：" + labels;
    return text;
}

} // namespace NativeBuffs
} // namespace BeiDouBridge
