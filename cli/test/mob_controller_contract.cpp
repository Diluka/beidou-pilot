// Exercise the production handler body with a minimal in-memory scene seam.
#include <cstdint>
#include <map>
#include <iostream>
#include <stdexcept>

namespace ms {
struct Mob {
    int mode = 0;

    void set_control(int8_t m) { mode = m; }
};
template <class T> using Optional = T*;

struct Objects {
    std::map<int, Mob> values;

    Mob* get(int oid) {
        auto i = values.find(oid);
        return i == values.end() ? nullptr : &i->second;
    }
};

struct MobSpawn {
    int oid;
    int mode;
};

struct Mobs {
    Objects objects;

    Objects* get_mobs() { return &objects; }

    void set_control(int oid, bool control) {
        if (auto m = objects.get(oid)) m->set_control(control);
    }

    void spawn(MobSpawn s) { objects.values[s.oid].mode = s.mode; }
};

struct Stage {
    Mobs mobs;

    static Stage& get() {
        static Stage s;
        return s;
    }

    Mobs& get_mobs() { return mobs; }
};

struct State {
    uint64_t unknown_mob_controllers = 0;
};

State& headless_state() {
    static State s;
    return s;
}

struct InPacket {
    int8_t mode;
    int oid;
    bool payload;

    int8_t read_byte() { return mode; }

    int read_int() { return oid; }

    bool available() { return payload; }
};

MobSpawn parse_mob_spawn(InPacket&, int oid, int8_t mode) {
    return {oid, mode};
}

struct SpawnMobControllerHandler {
    void handle(InPacket&) const;
};

// HANDLER_BODY
}

int main() {
    using namespace ms;
    auto& mobs = Stage::get().mobs;
    mobs.objects.values[11] = {};
    SpawnMobControllerHandler h;
    InPacket known{2, 11, true};
    h.handle(known);
    if (mobs.objects.values.at(11).mode != 2) return 1;
    InPacket known_oid_only{1, 11, false};
    h.handle(known_oid_only);
    if (mobs.objects.values.at(11).mode != 2) return 5;
    InPacket unknown{1, 22, true};
    h.handle(unknown);
    if (mobs.objects.values.count(22) || headless_state().unknown_mob_controllers != 1) return 2;
    InPacket oid_only{1, 33, false};
    h.handle(oid_only);
    if (mobs.objects.values.count(33) || headless_state().unknown_mob_controllers != 1) return 3;
    InPacket relinquish{0, 11, false};
    h.handle(relinquish);
    if (mobs.objects.values.at(11).mode != 0 || headless_state().unknown_mob_controllers != 1) return 4;
}
