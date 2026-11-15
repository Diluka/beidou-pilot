// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Observation.h"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace MapleControl {

// Unknown is kept separate from a known false value in both Lua and host results.
enum class Fact { Unknown, False, True };

// Native player inputs owned by the tick engine. Movement is a held-input
// direction, not an action; every other kind is a held action intent.
enum class ActionKind { Jump, Attack, UseItem, Pickup, Stop };

struct Character : MovableObject {
    std::uint32_t id = 0;
    std::string name;
    // level, job, str, dex, int, luk, hp, max_hp, mp, max_mp, ap, sp, exp
    std::array<std::uint32_t, 13> values{};
    std::array<bool, 13> known{};
    MovementReference movement;
};

struct Monster : MovableObject {
    std::uint32_t objectId = 0;
    std::uint32_t templateId = 0;
    bool templateKnown = false;
    std::string name;
    bool active = false;
    int hpPercent = 0;
    std::uint64_t hpSequence = 0; // Zero means no server HP observation for this native object.
};

struct Item {
    int inventoryType = 0;
    int slot = 0;
    std::uint32_t itemId = 0;
    int quantity = 0;
    bool quantityKnown = false;
};

struct Drop : MovableObject {
    std::uint32_t objectId = 0;
    std::uint32_t itemId = 0;
    bool itemKnown = false;
    std::uint32_t money = 0;
    bool moneyKnown = false;
    Fact landed = Fact::Unknown;
};

// Another character this client already knows in the current scene. The
// reference is opaque per backend and only meaningful within one scene
// generation; fields the backend cannot expose stay unknown.
struct OtherPlayer : MovableObject {
    std::string reference;
    std::uint32_t characterId = 0;
    bool characterIdKnown = false;
    std::string name;
    std::uint16_t level = 0;
    bool levelKnown = false;
    bool facingKnown = false;
    bool facingLeft = false;
};

struct Npc : MovableObject {
    std::uint32_t objectId = 0;
    std::uint32_t templateId = 0;
    std::string name;
};

// Visual projectiles may have no server object ID; do not invent a stable one.
struct Projectile : MovableObject {};

struct State {
    std::string instanceId;
    std::uint64_t sequence = 0;
    std::uint64_t observedAtMs = 0; // Unix milliseconds, supplied by the host.
    std::uint64_t sceneGeneration = 0;
    bool inGame = false; // false means the host has positively observed leaving the game.
    bool ready = false;
    bool mapKnown = false;
    std::uint32_t mapId = 0;
    bool characterKnown = false;
    Character character;
    // Snapshot projection of the local player's current native position.
    bool positionKnown = false;
    double x = 0;
    double y = 0;
    bool facingKnown = false;
    bool facingLeft = false;
    bool characterUpdatesKnown = false;
    std::uint64_t characterUpdates = 0;
    bool monstersKnown = false;
    std::vector<Monster> monsters;
    bool inventoryKnown = false;
    std::vector<Item> inventory;
    bool dropsKnown = false;
    std::vector<Drop> drops;
    bool playersKnown = false;
    std::vector<OtherPlayer> players;
    bool npcsKnown = false;
    std::vector<Npc> npcs;
    bool projectilesKnown = false;
    std::vector<Projectile> projectiles;
    // Only native supported flying objects are covered, not every game hazard.
    Fact projectilesComplete = Fact::Unknown;
    // True only when the backend can account for every player packet in this scene.
    Fact playersComplete = Fact::Unknown;
    Fact settled = Fact::Unknown;
    Fact onGround = Fact::Unknown;
    Fact attacking = Fact::Unknown;
    // Native character action lock; independent of physical rest or held input.
    Fact actionIdle = Fact::Unknown;
    Fact dead = Fact::Unknown;
    Fact reviveRequestable = Fact::Unknown;
};

struct Action {
    ActionKind kind = ActionKind::Stop;
    std::uint32_t itemId = 0;
    std::uint32_t skillId = 0; // Attack: zero holds the ordinary attack input, otherwise request one skill.
    std::string sessionId;
};

struct SkillResult {
    bool dispatched = false;
    int nativeResult = 0;
    std::string reason;
    bool nativeResultKnown = true;
};

struct ActionResult {
    bool dispatched = false;
    bool controlReleased = false;
    Fact settled = Fact::Unknown;
    std::string effect = "unknown";
    std::string reason;
    bool skillRequested = false;
    SkillResult skill;
    std::string sessionId;
};

// Each host supplies only native execution and its current state. The tick
// scheduler, state projection and public semantic API are compiled once per host.
class Adapter {
public:
    virtual ~Adapter() = default;
    virtual const State& Observe() const = 0;

    virtual Observation ObserveDomain(const std::string&) const {
        return {"unsupported", {}, "unsupported_observation_domain"};
    }

    virtual bool Supports(ActionKind kind) const = 0;

    virtual bool SupportsSkill() const { return false; }

    virtual ActionResult Result() const = 0;
    virtual bool Logs(const std::string& scriptId, const std::vector<std::string>& lines) = 0;
};

}
