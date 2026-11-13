// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Observation.h"

#include <cmath>
#include <iomanip>
#include <sstream>

namespace MapleControl {
namespace {
std::string Quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char byte : value) {
        if (byte == '"' || byte == '\\')
            out << '\\' << byte;
        else if (byte < 32)
            out << "\\u00" << std::hex << std::setfill('0') << std::setw(2) << static_cast<unsigned int>(byte)
                << std::dec;
        else
            out << byte;
    }
    out << '"';
    return out.str();
}
}

Value MotionVector::Document() const {
    if (source == Source::Unknown) return {};
    return Value::Object({{"x", x}, {"y", y}, {"source", "native"}});
}

Value MovementReference::Document() const {
    if (!known) return {};
    return Value::Object({{"kind", "model"},
                          {"model", model},
                          {"conditions", "stationary_flat_ground_normal"},
                          {"effective_speed", effectiveSpeed},
                          {"effective_jump", effectiveJump},
                          {"max_speed", maxSpeed},
                          {"max_jump_height", maxJumpHeight}});
}

Value Value::Object(std::initializer_list<std::pair<std::string, Value>> values) {
    Value result;
    result.kind = Kind::Object;
    result.object = values;
    return result;
}

Value Value::Array(std::initializer_list<Value> values) {
    Value result;
    result.kind = Kind::Array;
    result.array = values;
    return result;
}

Value& Value::operator[](const std::string& key) {
    if (kind == Kind::Null) kind = Kind::Object;
    for (auto& entry : object)
        if (entry.first == key) return entry.second;
    object.emplace_back(key, Value{});
    return object.back().second;
}

void Value::Add(Value value) {
    if (kind == Kind::Null) kind = Kind::Array;
    array.push_back(std::move(value));
}

std::string Value::Dump() const {
    switch (kind) {
    case Kind::Null:
        return "null";
    case Kind::Boolean:
        return boolean ? "true" : "false";
    case Kind::String:
        return Quote(text);
    case Kind::Number: {
        if (!std::isfinite(number)) return "null";
        std::ostringstream out;
        out << std::setprecision(17) << number;
        return out.str();
    }
    case Kind::Array: {
        std::string out = "[";
        bool separator = false;
        for (const auto& entry : array) {
            if (separator) out += ',';
            out += entry.Dump();
            separator = true;
        }
        return out + ']';
    }
    case Kind::Object: {
        std::string out = "{";
        bool separator = false;
        for (const auto& entry : object) {
            if (separator) out += ',';
            out += Quote(entry.first) + ':' + entry.second.Dump();
            separator = true;
        }
        return out + '}';
    }
    }
    return "null";
}

}
