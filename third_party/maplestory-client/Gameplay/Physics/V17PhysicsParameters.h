// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <array>
#include <cstddef>
#include <nlnx/node.hpp>

namespace ms
{
// The nineteen real values of Data/Map/Physics.img. Positions are the original
// coefficient-table byte offsets (the native loader copies the keys into that
// table in this order); the array index is offset / 8. Values are read once from
// this client's own resources and validated strictly: a missing or non-finite
// required key is a resource error, never a silent fallback to old constants.
class V17PhysicsParameters
{
public:
    enum Offset : std::size_t
    {
        WalkForce = 0x00,         // mass * px / s^2
        WalkSpeed = 0x08,         // px / s
        WalkDrag = 0x10,          // mass * px / s^2
        SlipForce = 0x18,         // special: slippery surfaces
        SlipSpeed = 0x20,         // special
        FloatDrag1 = 0x28,        // special: floating
        FloatDrag2 = 0x30,        // ordinary air horizontal force/drag
        FloatCoefficient = 0x38,  // ordinary air idle-drag coefficient
        SwimForce = 0x40,         // special
        SwimSpeed = 0x48,         // special
        FlyForce = 0x50,          // special
        FlySpeed = 0x58,          // special
        GravityAcc = 0x60,        // px / s^2
        FallSpeed = 0x68,         // px / s terminal
        JumpSpeed = 0x70,         // px / s
        MaxFriction = 0x78,       // dimensionless upper bound
        MinFriction = 0x80,       // dimensionless lower bound
        SwimSpeedDec = 0x88,      // special
        FlyJumpDec = 0x90,        // special
        Count = 19,
    };

    // Reads and validates all nineteen real nodes. Throws std::runtime_error with
    // the offending key when the resource is unavailable, malformed or non-finite.
    static void Init(nl::node physicsImg);
    static bool Available();
    static const V17PhysicsParameters& Get();

    // offset must be one of the Offset values; throws std::out_of_range otherwise.
    double at(std::size_t offset) const;
    double operator[](std::size_t index) const { return values[index]; }
    double walkForce() const { return values[WalkForce / 8]; }
    double walkSpeed() const { return values[WalkSpeed / 8]; }
    double walkDrag() const { return values[WalkDrag / 8]; }
    double floatDrag2() const { return values[FloatDrag2 / 8]; }
    double floatCoefficient() const { return values[FloatCoefficient / 8]; }
    double gravityAcc() const { return values[GravityAcc / 8]; }
    double fallSpeed() const { return values[FallSpeed / 8]; }
    double jumpSpeed() const { return values[JumpSpeed / 8]; }
    double minFriction() const { return values[MinFriction / 8]; }
    double maxFriction() const { return values[MaxFriction / 8]; }
    double swimSpeedDec() const { return values[SwimSpeedDec / 8]; }

private:
    static const char* KeyName(std::size_t index);

    std::array<double, Count> values{};
};
}
