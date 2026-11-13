// SPDX-License-Identifier: AGPL-3.0-or-later
#include "NativeMotion.h"
#include "NativeObservation.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>

namespace {
// External V17 layout fixtures, not observations from a running client.
// Source: BeiDou.exe SHA256 1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df.
// 0x539338: key[2],cipher[2],one chained checksum; 0x6724FC:
// 12-byte guard, eight cipher bytes, key@8, identity@9,10, checksum@12.
// These pre-encoded vectors are fixed independently of the production decoder;
// the test does not recreate its cipher/checksum implementation.
const std::array<std::uint32_t, 5> Right128{{0x13579BDF, 0x2468ACE0, 0xF89ABCDE, 0x03204527, 0xE86C570D}};
const std::array<std::uint32_t, 5> Left128{{0x13579BDF, 0x2468ACE0, 0xF89ABCDE, 0x07204527, 0xEC6C570D}};
const std::array<std::uint32_t, 5> Up360{{0x13579BDF, 0x2468ACE0, 0xF89ABCDE, 0x0720F127, 0xEC6D030D}};
const std::array<std::uint32_t, 5> Zero{{0x13579BDF, 0x2468ACE0, 0xF89ABCDE, 0x01234567, 0xE66F574D}};
const std::array<std::uint32_t, 5> NotFinite{{0x13579BDF, 0x2468ACE0, 0xF89ABCDE, 0x02DC8567, 0xE828974D}};
const std::array<unsigned char, 14> Ratio100{
    {0x2A, 0x7E, 0x26, 0x76, 0x16, 0x56, 0x26, 0x19, 0x00, 0xA5, 0xC3, 0x77, 0x6E, 0xF7}};
const std::array<unsigned char, 14> Speed140{
    {0x4C, 0xC6, 0xF6, 0xD6, 0xD6, 0xD6, 0x46, 0x1F, 0x00, 0xA5, 0xC3, 0x77, 0xFC, 0x7F}};
const std::array<unsigned char, 14> Jump123{
    {0x84, 0x9F, 0x40, 0x71, 0xB2, 0x2C, 0x2B, 0x12, 0x00, 0xA5, 0xC3, 0x77, 0xF0, 0xF7}};
const std::array<unsigned char, 14> RatioZero{
    {0x2A, 0x7E, 0x26, 0x76, 0x16, 0x56, 0xD6, 0xD6, 0x00, 0xA5, 0xC3, 0x77, 0xFB, 0xF7}};
const std::array<unsigned char, 14> RatioNaN{
    {0x2A, 0x7E, 0x26, 0x76, 0x16, 0x56, 0x2E, 0x51, 0x00, 0xA5, 0xC3, 0x77, 0xEE, 0xF7}};

constexpr std::uint32_t User = 0x100000;
constexpr std::uint32_t Vector = 0x200000;
constexpr std::uint32_t Attributes = 0x300000;
constexpr std::uint32_t Space = 0x400000;
constexpr std::uint32_t Coefficients = 0x500000;
constexpr std::uint32_t SpeedBacking = 0x600000;
constexpr std::uint32_t JumpBacking = 0x600100;
std::map<std::uintptr_t, unsigned char> memory;
std::uintptr_t unexpectedFailure = 0;
std::vector<std::uintptr_t> reads;

void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

void Near(double actual, double expected, const std::string& message) {
    Check(std::abs(actual - expected) < 1e-9, message);
}

template <class T> void Put(std::uintptr_t address, const T& value) {
    const auto bytes = reinterpret_cast<const unsigned char*>(&value);
    for (std::size_t index = 0; index < sizeof(value); ++index) memory[address + index] = bytes[index];
}

void Attribute(std::uintptr_t address, std::uint32_t backing, const std::array<unsigned char, 14>& encoded) {
    std::array<unsigned char, 12> guard{};
    guard[0] = 0xA5;
    guard[4] = 0xC3;
    std::memcpy(guard.data() + 8, &backing, sizeof(backing));
    Put(address, guard);
    Put(backing, encoded);
}

void Fixture(bool enhanced = false) {
    memory.clear();
    unexpectedFailure = 0;
    reads.clear();
    Put(User, std::array<std::uint32_t, 2>{{0x00B3D20C, 0x00B3D1E8}});
    Put(Vector, std::uint32_t{0x00B3EAA8});
    Put(Vector + 0x0C, std::uint32_t{0x00B3E9F8});
    Put(User + 0x11A4, Vector + 0x0C);
    Put(Vector + 0x50, Right128);
    Put(Vector + 0x68, Up360);
    Put(Vector + 0x110, std::uint32_t{0x700000});
    Put(Vector + 0x1A8, Attributes);
    Attribute(Attributes + 0x24, SpeedBacking, enhanced ? Speed140 : Ratio100);
    Attribute(Attributes + 0x48, JumpBacking, enhanced ? Jump123 : Ratio100);
    Put(0x00BEBFA0, Space);
    Put(Space + 8, Coefficients);
    // Deliberately different from any headless defaults: the real helper must
    // consume this client's coefficient object, not reproduce another backend.
    Put(Coefficients + 8, 128.5);
    Put(Coefficients + 0x60, 1920.0);
    Put(Coefficients + 0x68, 1234.0); // terminal fall speed, NOT gravity
    Put(Coefficients + 0x70, 576.0);
    Put(0x00BEDDBC, std::uint32_t{54}); // next native TSec read would re-encrypt
    // user+0x2B64, vector+0x1A0 and character mass are intentionally absent:
    // unproven aliases/current terrain do not supply this normal reference.
}

void Unavailable(const NativeMotion::Observation& value, const std::string& prefix, const std::string& cause) {
    const auto unknownGroups =
        static_cast<std::size_t>((value.velocity.source == MapleControl::MotionVector::Source::Unknown)
                                 + (value.onGround == MapleControl::Fact::Unknown) + !value.movement.known);
    Check(value.unavailable.size() == unknownGroups, "exactly one diagnostic per unavailable fact group");
    const auto matching = [&](const std::string& reason) { return reason.find(prefix) == 0; };
    Check(std::count_if(value.unavailable.begin(), value.unavailable.end(), matching) == 1,
          "diagnostic identifies its unavailable fact group");
    const auto found = std::find_if(value.unavailable.begin(), value.unavailable.end(), matching);
    Check(found->find(cause) != std::string::npos, "diagnostic preserves the original read failure cause");
}

void Unknown(const NativeMotion::Observation& value) {
    Check(value.velocity.source == MapleControl::MotionVector::Source::Unknown, "velocity must remain unknown");
    Check(!value.movement.known, "model must remain unknown");
    Check(value.onGround == MapleControl::Fact::Unknown, "grounding must remain unknown");
    Check(value.velocity.Document().Type() == MapleControl::Value::Kind::Null, "unknown velocity serializes null");
    Check(value.movement.Document().Type() == MapleControl::Value::Kind::Null, "unknown model serializes null");
    Unavailable(value, "native velocity: ", "unavailable");
    Unavailable(value, "native grounding: ", "unavailable");
    Unavailable(value, "native movement reference: ", "unavailable");
}

void Normal() {
    Fixture();
    const auto before = memory;
    auto value = NativeMotion::Capture(User);
    Check(memory == before, "observation must not mutate counters, guards, cipher or native state");
    Check(value.unavailable.empty(), "known native facts do not carry unavailable diagnostics");
    Check(value.velocity.source == MapleControl::MotionVector::Source::Native, "decoded velocity is native");
    Near(value.velocity.x, 128.25, "world x velocity is px/s without per-tick conversion");
    Near(value.velocity.y, -360.5, "upward world y velocity is negative");
    Check(value.onGround == MapleControl::Fact::True, "grounding uses the foothold pointer, not vy");
    Check(value.movement.known && value.movement.model == "v17_normal_continuous_v1", "normal continuous model");
    Check(value.movement.effectiveSpeed == 100 && value.movement.effectiveJump == 100, "effective native attributes");
    Near(value.movement.maxSpeed, 128.5, "base SPEED100 reference");
    Near(value.movement.maxJumpHeight, 86.4, "continuous ordinary jump reference from native launch/gravity");
    const auto document = value.movement.Document().Dump();
    Check(document.find("\"kind\":\"model\"") != std::string::npos, "reference is explicitly model-derived");
    Check(document.find("\"conditions\":\"stationary_flat_ground_normal\"") != std::string::npos,
          "normal reference conditions are explicit");
    Check(value.velocity.Document().Dump().find("\"source\":\"native\"") != std::string::npos,
          "native velocity provenance is projected");

    Fixture(true);
    value = NativeMotion::Capture(User);
    Check(value.movement.effectiveSpeed == 140 && value.movement.effectiveJump == 123, "ratio-to-stat rounding");
    Near(value.movement.maxSpeed, 179.9, "SPEED140 scales the native loaded walk coefficient");
    Near(value.movement.maxJumpHeight, 86.4 * 1.23 * 1.23, "JUMP123 scales launch speed, not height linearly");
    Put(Coefficients + 0x60, 960.0);
    Put(Coefficients + 0x68, 4321.0);
    value = NativeMotion::Capture(User);
    Near(value.movement.maxJumpHeight, 172.8 * 1.23 * 1.23, "gravity is +0x60, not terminal-speed +0x68");
    Put(Vector + 0x50, Left128);
    Put(Vector + 0x68, Zero);
    Put(Vector + 0x110, std::uint32_t{0});
    value = NativeMotion::Capture(User);
    Near(value.velocity.x, -128.25, "leftward native velocity remains signed");
    Near(value.velocity.y, 0, "authenticated zero velocity is known");
    Check(value.onGround == MapleControl::Fact::False, "zero vy does not invent a foothold");
}

void Missing() {
    memory.clear();
    Unknown(NativeMotion::Capture(0));
    Unknown(NativeMotion::Capture(User));
    Put(User + 0x11A4, std::uint32_t{0});
    Unknown(NativeMotion::Capture(User));
    Put(User + 0x11A4, std::uint32_t{4});
    Unknown(NativeMotion::Capture(User));

    Fixture();
    memory.erase(Vector + 0x50);
    auto value = NativeMotion::Capture(User);
    Check(value.velocity.source == MapleControl::MotionVector::Source::Unknown && value.movement.known
              && value.onGround == MapleControl::Fact::True,
          "missing velocity preserves independent model/grounding");
    Unavailable(value, "native velocity: ", "fixture native memory is unavailable");
    Fixture();
    memory.erase(Vector + 0x110);
    value = NativeMotion::Capture(User);
    Check(value.onGround == MapleControl::Fact::Unknown && value.movement.known
              && value.velocity.source == MapleControl::MotionVector::Source::Native,
          "missing grounding is not false and does not erase velocity/model");
    Unavailable(value, "native grounding: ", "fixture native memory is unavailable");
    for (const auto address : {std::uintptr_t{Vector + 0x1A8}, std::uintptr_t{0x00BEBFA0}, std::uintptr_t{Space + 8},
                               std::uintptr_t{Coefficients + 0x60}, std::uintptr_t{JumpBacking + 13}}) {
        Fixture();
        memory.erase(address);
        value = NativeMotion::Capture(User);
        Check(!value.movement.known && value.onGround == MapleControl::Fact::True
                  && value.velocity.source == MapleControl::MotionVector::Source::Native,
              "missing model read preserves velocity and ground truth");
        Unavailable(value, "native movement reference: ", "fixture native memory is unavailable");
    }
    for (const auto address : {Vector + 0x1A8, Space + 8, std::uint32_t{0x00BEBFA0}, Attributes + 0x24 + 8}) {
        Fixture();
        Put(address, std::uint32_t{0});
        value = NativeMotion::Capture(User);
        Check(!value.movement.known && value.velocity.source == MapleControl::MotionVector::Source::Native,
              "null native model pointer is unknown, not a fallback reference");
        Unavailable(value, "native movement reference: ", "unavailable");
    }
    Fixture();
    memory.erase(Vector + 0x50);
    memory.erase(Vector + 0x110);
    memory.erase(0x00BEBFA0);
    Unknown(NativeMotion::Capture(User));
}

void Checksums() {
    for (const auto address :
         {Vector + 0x50, Vector + 0x58, Vector + 0x60, Vector + 0x68, Vector + 0x74, Vector + 0x78}) {
        Fixture();
        memory.at(address) ^= 1;
        const auto value = NativeMotion::Capture(User);
        Check(value.velocity.source == MapleControl::MotionVector::Source::Unknown && value.movement.known
                  && value.onGround == MapleControl::Fact::True,
              "every native velocity limb/checksum must authenticate before publishing a pair");
        Unavailable(value, "native velocity: ", "checksum");
    }
    for (const auto address : {SpeedBacking, SpeedBacking + 12, JumpBacking + 8, JumpBacking + 12, Attributes + 0x24,
                               Attributes + 0x48 + 4}) {
        Fixture();
        memory.at(address) ^= 1;
        const auto value = NativeMotion::Capture(User);
        Check(!value.movement.known && value.velocity.source == MapleControl::MotionVector::Source::Native
                  && value.onGround == MapleControl::Fact::True,
              "attribute payload/key/checksum and both guard identities authenticate independently");
        Unavailable(value, "native movement reference: ", "checksum");
    }
}

void Numeric() {
    Fixture();
    Put(Vector + 0x50, NotFinite);
    auto value = NativeMotion::Capture(User);
    Check(value.velocity.source == MapleControl::MotionVector::Source::Unknown && value.movement.known,
          "checksum-valid non-finite velocity is unknown");
    for (const auto& encoded : {RatioZero, RatioNaN}) {
        Fixture();
        Attribute(Attributes + 0x48, JumpBacking, encoded);
        value = NativeMotion::Capture(User);
        Check(!value.movement.known && value.velocity.source == MapleControl::MotionVector::Source::Native,
              "nonpositive/non-finite effective jump cannot invent a reference");
    }
    for (const auto number :
         {0.0, -1.0, std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()}) {
        Fixture();
        Put(Coefficients + 0x60, number);
        value = NativeMotion::Capture(User);
        Check(!value.movement.known && value.onGround == MapleControl::Fact::True,
              "missing valid native gravity leaves only the model unknown");
    }
    Fixture();
    Put(Coefficients + 0x70, std::numeric_limits<double>::max());
    Check(!NativeMotion::Capture(User).movement.known, "overflowed analytic apex remains unknown");
}

struct EntityFixture {
    NativeMotion::EntityKind kind;
    std::uint32_t object;
    std::uint32_t vector;
    std::array<std::uint32_t, 3> objectTables;
    std::uint32_t comOffset;
    std::uint32_t vectorTable;
    std::uint32_t comTable;
    std::array<std::uint32_t, 5> vx;
    std::array<std::uint32_t, 5> vy;
    double x;
    double y;
};

// Explicit original-image layout facts, not imported from production constants.
// Every actor owns a different address and velocity, even in the same snapshot.
const std::array<EntityFixture, 4> Entities{{
    {NativeMotion::EntityKind::LocalUser,
     User,
     Vector,
     {{0xB3D20C, 0xB3D1E8, 0}},
     0x11A4,
     0xB3EAA8,
     0xB3E9F8,
     Right128,
     Up360,
     128.25,
     -360.5},
    {NativeMotion::EntityKind::RemoteUser,
     0x110000,
     0x210000,
     {{0xB3D898, 0xB3D874, 0}},
     0x11A4,
     0xB3EAA8,
     0xB3E9F8,
     Left128,
     Zero,
     -128.25,
     0},
    {NativeMotion::EntityKind::Mob,
     0x120000,
     0x220000,
     {{0xAF8270, 0xAF824C, 0xAF8248}},
     0x118,
     0xB3E678,
     0xB3E5C8,
     Zero,
     Right128,
     0,
     128.25},
    {NativeMotion::EntityKind::Npc,
     0x130000,
     0x230000,
     {{0xAFC9D8, 0xAFC9B4, 0xAFC9B0}},
     0x90,
     0xB3E7A8,
     0xB3E6F8,
     Up360,
     Left128,
     -360.5,
     -128.25},
}};

void EntityMemory() {
    Fixture();
    Put(0x00BEBF98, User);
    for (const auto& entity : Entities) {
        Put(entity.object, entity.objectTables);
        Put(entity.object + entity.comOffset, entity.vector + 0x0C);
        Put(entity.vector, entity.vectorTable);
        Put(entity.vector + 0x0C, entity.comTable);
        Put(entity.vector + 0x20, Left128); // position is NOT velocity
        Put(entity.vector + 0x38, Right128);
        Put(entity.vector + 0x50, entity.vx);
        Put(entity.vector + 0x68, entity.vy);
        if (entity.kind == NativeMotion::EntityKind::Mob || entity.kind == NativeMotion::EntityKind::Npc) {
            // Tempting but wrong User offset and a valid, different secondary
            // vector must not be used when the primary is absent or damaged.
            Put(entity.object + 0x11A4, Vector + 0x0C);
            const auto secondary = entity.vector + 0x80000;
            Put(entity.object + entity.comOffset + 4, secondary + 0x0C);
            Put(secondary, entity.vectorTable);
            Put(secondary + 0x0C, entity.comTable);
            Put(secondary + 0x50, Right128);
            Put(secondary + 0x68, Right128);
        }
    }
}

void NativeVelocity(const MapleControl::MotionVector& value, double x, double y) {
    Check(value.source == MapleControl::MotionVector::Source::Native, "own verified vector has native provenance");
    Near(value.x, x, "entity owns its own native world vx");
    Near(value.y, y, "entity owns its own native world vy");
    Check(value.Document().Dump().find("\"source\":\"native\"") != std::string::npos, "native provenance is public");
}

void UnknownVelocity(const MapleControl::MotionVector& value) {
    Check(value.source == MapleControl::MotionVector::Source::Unknown, "failed primary vector is unknown");
    Check(value.Document().Type() == MapleControl::Value::Kind::Null, "missing motion is not a zero vector");
}

void EntityKinds() {
    EntityMemory();
    const auto before = memory;
    for (const auto& entity : Entities) {
        reads.clear();
        const auto value = NativeMotion::CaptureVelocity(entity.kind, entity.object);
        NativeVelocity(value, entity.x, entity.y);
        for (const auto forbidden :
             {std::uintptr_t{0x00BEBFA0}, std::uintptr_t{entity.vector + 0x110}, std::uintptr_t{entity.vector + 0x1A8}})
            Check(std::find(reads.begin(), reads.end(), forbidden) == reads.end(),
                  "entity velocity reads neither grounding nor character ability fields");
    }
    Check(memory == before, "all entity captures are immutable native reads");
    NativeVelocity(NativeMotion::Capture(User).velocity, 128.25, -360.5);
    Unknown(NativeMotion::Capture(Entities[1].object)); // local-only model is not a remote model
    for (const auto& entity : Entities) {
        Put(entity.vector + 0x50, Zero);
        Put(entity.vector + 0x68, Zero);
        NativeVelocity(NativeMotion::CaptureVelocity(entity.kind, entity.object), 0, 0);
    }
}

void EntityTypes() {
    for (const auto& entity : Entities) {
        EntityMemory();
        const auto before = memory;
        std::vector<std::uintptr_t> types{entity.object, entity.object + 4, entity.vector, entity.vector + 0x0C};
        if (entity.objectTables[2] != 0) types.push_back(entity.object + 8);
        for (const auto address : types) {
            memory = before;
            memory.at(address) ^= 1;
            UnknownVelocity(NativeMotion::CaptureVelocity(entity.kind, entity.object));
            if (entity.kind == NativeMotion::EntityKind::LocalUser) Unknown(NativeMotion::Capture(entity.object));
        }
        for (const auto pointer : {0U, 4U, 12U, 0xDEADU}) {
            memory = before;
            Put(entity.object + entity.comOffset, pointer);
            UnknownVelocity(NativeMotion::CaptureVelocity(entity.kind, entity.object));
        }
        memory = before;
        memory.erase(entity.object + entity.comOffset);
        UnknownVelocity(NativeMotion::CaptureVelocity(entity.kind, entity.object));
        memory = before;
        for (const auto& other : Entities)
            if (other.kind != entity.kind) UnknownVelocity(NativeMotion::CaptureVelocity(other.kind, entity.object));
        UnknownVelocity(NativeMotion::CaptureVelocity(entity.kind, 0));
    }
    UnknownVelocity(NativeMotion::CaptureVelocity(static_cast<NativeMotion::EntityKind>(999), User));
}

void EntityPayloads() {
    for (const auto& entity : Entities) {
        EntityMemory();
        const auto before = memory;
        for (const auto offset : {0x50, 0x58, 0x60, 0x68, 0x74, 0x78}) {
            memory = before;
            memory.at(entity.vector + offset) ^= 1;
            UnknownVelocity(NativeMotion::CaptureVelocity(entity.kind, entity.object));
        }
        for (const auto offset : {0x50, 0x68}) {
            memory = before;
            memory.erase(entity.vector + offset);
            UnknownVelocity(NativeMotion::CaptureVelocity(entity.kind, entity.object));
            memory = before;
            Put(entity.vector + offset, NotFinite);
            UnknownVelocity(NativeMotion::CaptureVelocity(entity.kind, entity.object));
        }
        memory = before;
        unexpectedFailure = entity.vector + 0x50;
        bool propagated = false;
        try {
            NativeMotion::CaptureVelocity(entity.kind, entity.object);
        } catch (const std::logic_error&) {
            propagated = true;
        }
        Check(propagated, "per-entity sensor recovers only a native ReadError");
    }
}

void NpcPool() {
    EntityMemory();
    const auto npc = Entities[3].object;
    constexpr std::uint32_t Pool = 0x900000, Node = 0x910000, Definition = 0x920000, Name = 0x930004;
    Put(0x00BED780, Pool);
    Put(Pool, std::uint32_t{0x00AFC9F8});
    Put(Pool + 0x24, std::array<std::uint32_t, 3>{{1, Node, Node}});
    Put(Node + 4, std::uint32_t{0});
    Put(Node + 0x10, npc);
    Put(npc + 0xA4, std::uint32_t{777});
    Put(npc + 0xA8, Definition);
    Put(npc + 0x150, std::array<std::int32_t, 2>{{-1773, 408}});
    Put(Definition, std::uint32_t{9010000});
    Put(Definition + 4, Name);
    Put(Name - 4, std::uint32_t{3});
    Put(Name, std::array<unsigned char, 4>{{'N', 'p', 'c', 0}});
    const auto before = memory;
    std::vector<MapleControl::Npc> output;
    NativeObservation::Npcs(output);
    Check(output.size() == 1 && output[0].objectId == 777 && output[0].templateId == 9010000,
          "typed NPC uses native member/object/template identities without invented IDs");
    Check(output[0].name == "Npc" && output[0].positionKnown && output[0].x == -1773 && output[0].y == 408,
          "typed NPC retains existing integer position cache and metadata");
    NativeVelocity(output[0].velocity, -360.5, -128.25);
    Check(memory == before, "typed NPC collection never mutates membership or native vectors");
    Put(npc + 0x90, std::uint32_t{0});
    NativeObservation::Npcs(output);
    Check(output.size() == 1 && output[0].x == -1773, "damaged vector does not erase a verified NPC position");
    UnknownVelocity(output[0].velocity);
    Put(Pool + 0x24, std::array<std::uint32_t, 3>{{0, 0, 0}});
    NativeObservation::Npcs(output);
    Check(output.empty(), "only an observed native empty NPC pool becomes an empty collection");
    Put(0x00BED780, std::uint32_t{0});
    bool unavailable = false;
    try {
        NativeObservation::Npcs(output);
    } catch (const NativeObservation::ReadError&) {
        unavailable = true;
    }
    Check(unavailable, "an unavailable NPC pool cannot masquerade as an observed empty pool");
}

void PlayerPool() {
    EntityMemory();
    const auto user = Entities[1].object;
    constexpr std::uint32_t Pool = 0x900000, Buckets = 0x910000, Node = 0x920000, Wrapper = 0x930000;
    Put(0x00BEBFA8, Pool);
    Put(Pool, std::uint32_t{0x00B3D778});
    Put(Pool + 8, User);
    Put(User + 0x11A8, std::uint32_t{10});
    Put(Pool + 0x0C, std::uint32_t{0x00B3D7A0});
    Put(Pool + 0x10, Buckets);
    Put(Pool + 0x14, std::uint32_t{1});
    Put(Pool + 0x18, std::uint32_t{1});
    Put(Buckets, Node);
    Put(Node, std::uint32_t{0x00B3D7A8});
    Put(Node + 4, std::uint32_t{0});
    Put(Node + 8, std::uint32_t{20});
    Put(Node + 0x10, Wrapper);
    Put(Wrapper, std::uint32_t{0x00B3D7A4});
    Put(Wrapper + 0x10, user);
    Put(user + 0x11A8, std::uint32_t{20});
    Put(user + 0x11AC, std::uint32_t{0});
    Put(user + 0x116C, std::int32_t{-47});
    Put(user + 0x1170, std::int32_t{88});
    Put(user + 0x570, std::uint32_t{1});
    Put(user + 0x2AE0, static_cast<unsigned char>(11));
    std::vector<MapleControl::OtherPlayer> output;
    NativeObservation::Players(output);
    Check(output.size() == 1 && output[0].characterId == 20 && output[0].reference == "20",
          "typed player retains native map membership and reference");
    Check(output[0].positionKnown && output[0].x == -47 && output[0].y == 88, "remote cached position is preserved");
    NativeVelocity(output[0].velocity, -128.25, 0);
    Put(user + 0x11A4, std::uint32_t{0});
    NativeObservation::Players(output);
    Check(output.size() == 1 && output[0].x == -47, "missing remote vector preserves its own position");
    UnknownVelocity(output[0].velocity);
    Put(0x00BEBFA8, std::uint32_t{0});
    bool unavailable = false;
    try {
        NativeObservation::Players(output);
    } catch (const NativeObservation::ReadError&) {
        unavailable = true;
    }
    Check(unavailable, "an unreadable player pool is not a successfully observed empty pool");
}

void BoundaryFailure() {
    Fixture();
    unexpectedFailure = Vector + 0x50;
    bool propagated = false;
    try {
        NativeMotion::Capture(User);
    } catch (const std::logic_error&) {
        propagated = true;
    }
    Check(propagated, "only recoverable native ReadError may become unknown, not arbitrary exceptions");
}
}

namespace NativeObservation {
// NativeMotion uses only this process-memory boundary replacement. The real
// ObserveWorld collectors are also compiled (without the unrelated Windows PCH).
// Their ASCII-only metadata fixtures use the byte/encoding boundaries below;
// no movement, secure decoder, pool or typed projection is replaced.
void Copy(std::uintptr_t address, void* output, std::size_t size) {
    reads.push_back(address);
    if (unexpectedFailure != 0 && address == unexpectedFailure) throw std::logic_error("unexpected boundary failure");
    auto bytes = static_cast<unsigned char*>(output);
    for (std::size_t index = 0; index < size; ++index) {
        const auto found = memory.find(address + index);
        if (found == memory.end()) throw ReadError("fixture native memory is unavailable");
        bytes[index] = found->second;
    }
}

std::vector<unsigned char> Bytes(std::uintptr_t address, std::size_t size) {
    std::vector<unsigned char> value(size);
    Copy(address, value.data(), size);
    return value;
}

std::string Utf8(const std::string& value) {
    Check(std::all_of(value.begin(), value.end(), [](unsigned char byte) { return byte < 128; }),
          "this offline encoding boundary supports ASCII metadata fixtures only");
    return value;
}
}

int main(int argc, char** argv) {
    Check(argc == 2, "one native-motion contract case is required");
    const std::string test = argv[1];
    if (test == "normal")
        Normal();
    else if (test == "missing")
        Missing();
    else if (test == "checksums")
        Checksums();
    else if (test == "numeric")
        Numeric();
    else if (test == "boundary")
        BoundaryFailure();
    else if (test == "entities")
        EntityKinds();
    else if (test == "entity_types")
        EntityTypes();
    else if (test == "entity_payloads")
        EntityPayloads();
    else if (test == "npcs")
        NpcPool();
    else if (test == "players")
        PlayerPool();
    else
        Check(false, "unknown native-motion contract case");
}
