// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeMotion.h"
#include "NativeObservation.h"

#include <array>
#include <cmath>
#include <cstring>
#include <limits>

namespace NativeMotion {
namespace {
using NativeObservation::Read;
using NativeObservation::ReadError;

std::uintptr_t PrimaryVector(EntityKind kind, std::uintptr_t object) {
    struct Layout {
        std::array<std::uint32_t, 3> objectTables;
        std::uint32_t comOffset;
        std::uint32_t vectorTable;
        std::uint32_t comTable;
    };

    // Original-image factory/ctor chains: User 0x9CB916/0x9CB89A,
    // Mob 0x9BBCC4/0x9BBAEF, Npc 0x9C1CE6/0x9C1C9B.
    Layout layout{};
    switch (kind) {
    case EntityKind::LocalUser:
        layout = {{{0x00B3D20C, 0x00B3D1E8, 0}}, 0x11A4, 0x00B3EAA8, 0x00B3E9F8};
        break;
    case EntityKind::RemoteUser:
        layout = {{{0x00B3D898, 0x00B3D874, 0}}, 0x11A4, 0x00B3EAA8, 0x00B3E9F8};
        break;
    case EntityKind::Mob:
        layout = {{{0x00AF8270, 0x00AF824C, 0x00AF8248}}, 0x118, 0x00B3E678, 0x00B3E5C8};
        break;
    case EntityKind::Npc:
        layout = {{{0x00AFC9D8, 0x00AFC9B4, 0x00AFC9B0}}, 0x90, 0x00B3E7A8, 0x00B3E6F8};
        break;
    default:
        throw ReadError("native entity kind is unavailable");
    }
    if (object == 0) throw ReadError("native entity object is unavailable");
    const auto tables = Read<std::array<std::uint32_t, 2>>(object);
    if (tables[0] != layout.objectTables[0] || tables[1] != layout.objectTables[1]
        || (layout.objectTables[2] != 0 && Read<std::uint32_t>(object + 8) != layout.objectTables[2]))
        throw ReadError("native entity type is unavailable (V17 object mismatch)");
    // Stored interfaces are V+0xC. Never call the native getter or AddRef, and
    // never fall back to the local user, a secondary vector or template data.
    const auto com = Read<std::uint32_t>(object + layout.comOffset);
    if (com <= 0xC) throw ReadError("native primary VecCtrl pointer is unavailable");
    const auto vector = com - 0xC;
    if (Read<std::uint32_t>(vector) != layout.vectorTable || Read<std::uint32_t>(com) != layout.comTable)
        throw ReadError("native primary VecCtrl type is unavailable (V17 vector mismatch)");
    return vector;
}

// BeiDou.exe SHA256 1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df.
// V17 fuse 0x539338: same per-DWORD recurrence as SecureInt, with two
// contiguous key limbs followed by two cipher limbs and ONE chained checksum.
double ZtlDouble(std::uintptr_t address) {
    const auto data = Read<std::array<std::uint32_t, 5>>(address);
    std::array<std::uint32_t, 2> plain{};
    std::uint32_t checksum = 0xBAADF00D;
    for (std::size_t index = 0; index < plain.size(); ++index) {
        const auto cipher = data[index + 2];
        plain[index] = data[index] ^ ((cipher << 5) | (cipher >> 27));
        const auto mixed = data[index] ^ checksum;
        checksum = cipher + ((mixed >> 5) | (mixed << 27));
    }
    if (checksum != data[4]) throw ReadError("native motion double checksum unavailable");
    double value = 0;
    std::memcpy(&value, plain.data(), sizeof(value));
    if (!std::isfinite(value)) throw ReadError("native motion double is not finite");
    return value;
}

MapleControl::MotionVector Velocity(std::uintptr_t vector) {
    // Ground tangent projection (0x9B1646), air integration (0x9B2C3C), and
    // remote movement-path writeback (0x9B1719) all own these world-space fields.
    const auto x = ZtlDouble(vector + 0x50);
    const auto y = ZtlDouble(vector + 0x68);
    MapleControl::MotionVector result;
    result.source = MapleControl::MotionVector::Source::Native;
    result.x = x;
    result.y = y;
    return result;
}

// V17 0x6724FC, reconstructed as reads only. The native reader increments
// 0xBEDDBC and re-encrypts every 55 reads; it must never be called here.
// Compared with SecureValue, the eight-byte payload moves key/guards/checksum
// to backing offsets 8 / 9,10 / 12 respectively; the guard object stays 12 bytes.
double TSecDouble(std::uintptr_t address) {
    const auto guards = Read<std::array<unsigned char, 12>>(address);
    std::uint32_t pointer = 0;
    std::memcpy(&pointer, guards.data() + 8, sizeof(pointer));
    if (pointer == 0) throw ReadError("native motion attribute backing is unavailable");
    const auto encoded = Read<std::array<unsigned char, 14>>(pointer);
    unsigned char key = encoded[8];
    std::uint16_t checksum = 0x9A65;
    std::array<unsigned char, 8> plain{};
    for (std::size_t index = 0; index < plain.size(); ++index) {
        if (key == 0) key = 42;
        plain[index] = encoded[index] ^ key;
        key = static_cast<unsigned char>(key + encoded[index] + 42);
        checksum = static_cast<std::uint16_t>((checksum << 3) | ((checksum >> 13) + key));
    }
    std::uint16_t expected = 0;
    std::memcpy(&expected, encoded.data() + 12, sizeof(expected));
    if (guards[0] != encoded[9] || guards[4] != encoded[10] || checksum != expected)
        throw ReadError("native motion attribute checksum unavailable");
    double value = 0;
    std::memcpy(&value, plain.data(), sizeof(value));
    if (!std::isfinite(value)) throw ReadError("native motion attribute is not finite");
    return value;
}
}

MapleControl::MotionVector CaptureVelocity(EntityKind kind, std::uintptr_t object) {
    try {
        return Velocity(PrimaryVector(kind, object));
    } catch (const ReadError&) {
        // This boundary owns only the velocity fact; membership/position remain
        // usable when its primary vector is unavailable. Other failures propagate.
        return {};
    }
}

Observation Capture(std::uintptr_t user) {
    Observation result;
    std::uintptr_t vector = 0;
    try {
        vector = PrimaryVector(EntityKind::LocalUser, user);
    } catch (const ReadError& error) {
        for (const auto* group : {"native velocity: ", "native grounding: ", "native movement reference: "})
            result.unavailable.emplace_back(std::string(group) + error.what());
        return result;
    }

    try {
        result.velocity = Velocity(vector);
    } catch (const ReadError& error) {
        // Invalid velocity does not discard independently readable grounding/model.
        result.unavailable.emplace_back(std::string("native velocity: ") + error.what());
    }
    try {
        // 0x9B19D0 selects ground/air physics by this foothold pointer;
        // 0x9B4929 sets it on attachment and clears it on native jump departure.
        result.onGround =
            Read<std::uint32_t>(vector + 0x110) != 0 ? MapleControl::Fact::True : MapleControl::Fact::False;
    } catch (const ReadError& error) {
        // Grounding remains unknown, not false, on an unavailable pointer read.
        result.unavailable.emplace_back(std::string("native grounding: ") + error.what());
    }
    try {
        const auto attributes = Read<std::uint32_t>(vector + 0x1A8);
        if (attributes == 0) throw ReadError("native motion attributes are unavailable");
        const auto speedRatio = TSecDouble(attributes + 0x24);
        const auto jumpRatio = TSecDouble(attributes + 0x48);
        const auto space = Read<std::uint32_t>(0x00BEBFA0);
        if (space == 0) throw ReadError("native physics space is unavailable");
        const auto coefficients = Read<std::uint32_t>(space + 8);
        if (coefficients == 0) throw ReadError("native physics coefficients are unavailable");
        const auto walk = Read<double>(coefficients + 8);
        const auto gravity = Read<double>(coefficients + 0x60);
        const auto jump = Read<double>(coefficients + 0x70);
        if (!std::isfinite(walk) || !std::isfinite(gravity) || !std::isfinite(jump) || walk <= 0 || gravity <= 0
            || jump <= 0 || speedRatio <= 0 || jumpRatio <= 0 || speedRatio > (std::numeric_limits<int>::max)() / 100.0
            || jumpRatio > (std::numeric_limits<int>::max)() / 100.0)
            throw ReadError("native motion reference inputs are unavailable");

        // 0x9B2187: normal flat-ground speed = base walk * effective SPEED/100.
        // 0x9B1E63: normal launch vy = -base jump * effective JUMP/100.
        // 0x9B2D90 + 0x9B2BCB: gravity force/mass = base gravity under normal
        // field conditions. 0x9B3421 uses trapezoidal position integration.
        // The analytic continuous apex is a MODEL, not an observed tick height;
        // terrain, moving footholds, swimming/flying and special jumps are excluded.
        const auto launch = jump * jumpRatio;
        const auto maxSpeed = walk * speedRatio;
        const auto maxHeight = launch * launch / (2 * gravity);
        if (!std::isfinite(maxSpeed) || !std::isfinite(maxHeight) || maxSpeed <= 0 || maxHeight <= 0)
            throw ReadError("native motion reference result is unavailable");
        result.movement.known = true;
        result.movement.model = "v17_normal_continuous_v1";
        result.movement.effectiveSpeed = static_cast<int>(std::lround(speedRatio * 100));
        result.movement.effectiveJump = static_cast<int>(std::lround(jumpRatio * 100));
        result.movement.maxSpeed = maxSpeed;
        result.movement.maxJumpHeight = maxHeight;
    } catch (const ReadError& error) {
        // A missing model never invalidates successfully decoded native velocity.
        result.unavailable.emplace_back(std::string("native movement reference: ") + error.what());
    }
    return result;
}

}
