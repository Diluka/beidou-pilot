// SPDX-License-Identifier: AGPL-3.0-or-later
// The real headless IMG parser feeds the required Physics.img keys into
// V17PhysicsParameters; the expected values below are the literal #237 table,
// not a second copy of the production formula.
#include "ImgResourceFile.h"
#include "Gameplay/Physics/V17PhysicsParameters.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>

namespace {
void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

// Literal values observed from Data/Map/Physics.img (#237 C.2).
constexpr double Expected[ms::V17PhysicsParameters::Count] = {
    140000.0, 125.0, 80000.0, 60000.0, 120.0, 100000.0, 10000.0, 0.01, 120000.0, 140.0,
    120000.0, 200.0, 2000.0,  670.0,   555.0, 2.0,      0.05,    0.9,  0.35,
};

void Values(const nl::node& physics) {
    Check(!ms::V17PhysicsParameters::Available(), "parameters_start_unavailable");
    ms::V17PhysicsParameters::Init(physics);
    Check(ms::V17PhysicsParameters::Available(), "parameters_available_after_init");
    const auto& parameters = ms::V17PhysicsParameters::Get();
    for (std::size_t index = 0; index < ms::V17PhysicsParameters::Count; ++index)
        Check(parameters[index] == Expected[index], "coefficient_value_mismatch");
    Check(parameters.at(0x00) == 140000.0 && parameters.at(0x60) == 2000.0 && parameters.at(0x90) == 0.35,
          "offset_access_is_byte_offset");
    Check(parameters.walkForce() == 140000.0 && parameters.walkSpeed() == 125.0 && parameters.walkDrag() == 80000.0
              && parameters.floatDrag2() == 10000.0 && parameters.floatCoefficient() == 0.01
              && parameters.gravityAcc() == 2000.0 && parameters.fallSpeed() == 670.0 && parameters.jumpSpeed() == 555.0
              && parameters.minFriction() == 0.05 && parameters.maxFriction() == 2.0,
          "named_accessors_match_literal_table");
    std::cout << "ok\n";
}

void Uninitialized() {
    bool threw = false;
    try {
        ms::V17PhysicsParameters::Get();
    } catch (const std::logic_error&) {
        threw = true;
    }
    Check(threw, "uninitialized_get_throws");
    std::cout << "ok\n";
}

std::string ErrorOf(const nl::node& physics) {
    try {
        ms::V17PhysicsParameters::Init(physics);
    } catch (const std::runtime_error& error) {
        return error.what();
    }
    return {};
}

void Missing(const nl::node& physics) {
    const auto message = ErrorOf(physics);
    Check(message.find("missing key walkForce") != std::string::npos, "missing_key_is_a_resource_error");
    std::cout << "ok\n";
}

void NotReal(const nl::node& physics) {
    const auto message = ErrorOf(physics);
    Check(message.find("walkSpeed is not a real") != std::string::npos, "wrong_node_type_is_a_resource_error");
    std::cout << "ok\n";
}

void NotFinite(const nl::node& physics) {
    const auto message = ErrorOf(physics);
    Check(message.find("jumpSpeed is not finite") != std::string::npos, "non_finite_value_is_a_resource_error");
    std::cout << "ok\n";
}

void MissingResource() {
    Check(!static_cast<bool>(nl::node{}), "empty_node");
    const auto message = ErrorOf(nl::node{});
    Check(message.find("resource unavailable") != std::string::npos, "unavailable_table_is_a_resource_error");
    std::cout << "ok\n";
}
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "scenario_required\n";
        return 2;
    }
    const std::string scenario = argv[1];
    if (scenario == "uninitialized") {
        Uninitialized();
        return 0;
    }
    if (scenario == "missing-resource") {
        MissingResource();
        return 0;
    }
    if (argc != 3) {
        std::cerr << "directory_required\n";
        return 2;
    }
    // Real parser path: original-format IMG directory -> nl::file -> nl::node.
    auto file = load_img_directory(argv[2]);
    const nl::node physics = file.root()["Physics.img"];
    if (scenario == "values")
        Values(physics);
    else if (scenario == "missing")
        Missing(physics);
    else if (scenario == "not-real")
        NotReal(physics);
    else if (scenario == "not-finite")
        NotFinite(physics);
    else {
        std::cerr << "unknown_scenario\n";
        return 2;
    }
    return 0;
}
