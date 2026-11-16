// SPDX-License-Identifier: AGPL-3.0-or-later
#include "V17PhysicsParameters.h"

#include <cmath>
#include <stdexcept>
#include <string>

namespace ms
{
namespace
{
const char* const KEY_NAMES[V17PhysicsParameters::Count] = {
    "walkForce",    "walkSpeed",   "walkDrag",      "slipForce", "slipSpeed",   "floatDrag1",
    "floatDrag2",   "floatCoefficient", "swimForce", "swimSpeed", "flyForce",    "flySpeed",
    "gravityAcc",   "fallSpeed",   "jumpSpeed",     "maxFriction", "minFriction", "swimSpeedDec",
    "flyJumpDec",
};

V17PhysicsParameters& Instance()
{
    static V17PhysicsParameters parameters;
    return parameters;
}

bool& Initialized()
{
    static bool initialized = false;
    return initialized;
}
}

const char* V17PhysicsParameters::KeyName(std::size_t index)
{
    return index < Count ? KEY_NAMES[index] : "?";
}

void V17PhysicsParameters::Init(nl::node physicsImg)
{
    if (!physicsImg)
        throw std::runtime_error("Physics.img: resource unavailable");

    V17PhysicsParameters parsed;
    for (std::size_t index = 0; index < Count; ++index)
    {
        const auto key = KeyName(index);
        const nl::node value = physicsImg[key];
        if (!value)
            throw std::runtime_error(std::string("Physics.img: missing key ") + key);
        if (value.data_type() != nl::node::type::real)
            throw std::runtime_error(std::string("Physics.img: key ") + key + " is not a real");
        const double real = value.get_real();
        if (!std::isfinite(real))
            throw std::runtime_error(std::string("Physics.img: key ") + key + " is not finite");
        parsed.values[index] = real;
    }

    Instance() = parsed;
    Initialized() = true;
}

bool V17PhysicsParameters::Available()
{
    return Initialized();
}

const V17PhysicsParameters& V17PhysicsParameters::Get()
{
    if (!Initialized())
        throw std::logic_error("Physics.img parameters used before initialization");
    return Instance();
}

double V17PhysicsParameters::at(std::size_t offset) const
{
    if (offset % 8 != 0 || offset >= Count * 8)
        throw std::out_of_range("Physics.img coefficient offset out of range");
    return values[offset / 8];
}
}
