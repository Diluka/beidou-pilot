// SPDX-License-Identifier: AGPL-3.0-or-later
// Exercise the real map collections; resource-dependent spawn instantiation is a test seam.
#include "Gameplay/MapleMap/MapChars.h"
#include "Gameplay/MapleMap/MapNpcs.h"
#include "Gameplay/MapleMap/MapDrops.h"
#include "Gameplay/MapleMap/MapReactors.h"
#include "Gameplay/Physics/Physics.h"
#include "Data/ItemData.h"
#include <iostream>
#include <stdexcept>

namespace ms {
struct Spawned {
    int id;
};

Animation::Animation() = default;

bool Animation::update() {
    return false;
}

ItemData::ItemData(int32_t) {
    throw std::logic_error("unexpected item resource");
}

ItemData::operator bool() const {
    return false;
}

const Texture& ItemData::get_icon(bool) const {
    throw std::logic_error("unexpected item icon");
}

int8_t MapObject::sampled_update(const Physics&) {
    throw std::logic_error("unexpected object update");
}

int32_t MapObject::get_oid() const {
    return oid;
}

NpcSpawn::NpcSpawn(int32_t o, int32_t i, Point<int16_t> p, bool f, uint16_t h)
    : oid(o), id(i), position(p), flip(f), fh(h) {}

int32_t NpcSpawn::get_oid() const {
    return oid;
}

std::unique_ptr<MapObject> NpcSpawn::instantiate(const Physics&) const {
    throw Spawned{oid};
}

ReactorSpawn::ReactorSpawn(int32_t o, int32_t r, int8_t s, Point<int16_t> p) : oid(o), rid(r), state(s), position(p) {}

int32_t ReactorSpawn::get_oid() const {
    return oid;
}

std::unique_ptr<MapObject> ReactorSpawn::instantiate(const Physics&) const {
    throw Spawned{oid};
}

DropSpawn::DropSpawn(int32_t o, int32_t i, bool m, int32_t ow, Point<int16_t> p, Point<int16_t> d, int8_t t, int8_t md,
                     bool pd)
    : oid(o), id(i), meso(m), owner(ow), start(p), dest(d), droptype(t), mode(md), playerdrop(pd) {}

int32_t DropSpawn::get_oid() const {
    return oid;
}

int32_t DropSpawn::get_itemid() const {
    return id;
}

bool DropSpawn::is_meso() const {
    return meso;
}

std::unique_ptr<MapObject> DropSpawn::instantiate(const Animation&) const {
    throw Spawned{oid};
}

std::unique_ptr<MapObject> DropSpawn::instantiate(const Texture&) const {
    throw Spawned{oid};
}

CharSpawn::CharSpawn(int32_t c, const LookEntry& l, uint16_t lv, int16_t j, const std::string& n, int8_t s,
                     Point<int16_t> p)
    : cid(c), level(lv), job(j), name(n), stance(s), position(p), look(l) {}

int32_t CharSpawn::get_cid() const {
    return cid;
}

std::unique_ptr<MapObject> CharSpawn::instantiate() const {
    throw Spawned{cid};
}
}

int main() {
    ms::Physics physics;
    ms::LookEntry look{};
    ms::MapChars chars;
    ms::MapNpcs npcs;
    ms::MapDrops drops;
    ms::MapReactors reactors;
    int failures = 0;
    auto check = [&](const char* name, auto& map, auto spawn) {
        map.spawn(spawn(11));
        map.clear();
        try {
            map.update(physics);
        } catch (const ms::Spawned& s) {
            std::cerr << name << ": stale spawn " << s.id << " after clear\n";
            ++failures;
        }
        map.clear();
        map.spawn(spawn(22));
        try {
            map.update(physics);
            std::cerr << name << ": new spawn lost\n";
            ++failures;
        } catch (const ms::Spawned& s) {
            if (s.id != 22) {
                std::cerr << name << ": unexpected spawn " << s.id << '\n';
                ++failures;
            }
        }
    };
    check("chars", chars, [&](int id) { return ms::CharSpawn(id, look, 1, 0, "test", 0, {}); });
    check("npcs", npcs, [](int id) { return ms::NpcSpawn(id, 1, {}, false, 0); });
    check("drops", drops, [](int id) { return ms::DropSpawn(id, 1, true, 0, {}, {}, 0, 0, false); });
    check("reactors", reactors, [](int id) { return ms::ReactorSpawn(id, 1, 0, {}); });
    return failures ? 1 : 0;
}
