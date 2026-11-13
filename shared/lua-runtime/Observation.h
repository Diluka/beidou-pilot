// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <initializer_list>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

namespace MapleControl {

// Small JSON output value: observations never parse arbitrary JSON in the game thread.
class Value {
public:
    enum class Kind { Null, Boolean, Number, String, Array, Object };
    Value() = default;

    Value(bool value) : kind(Kind::Boolean), boolean(value) {}

    Value(const char* value) : kind(Kind::String), text(value) {}

    Value(const std::string& value) : kind(Kind::String), text(value) {}

    Value(double value) : kind(Kind::Number), number(value) {}

    template <class T,
              typename std::enable_if<std::is_integral<T>::value && !std::is_same<T, bool>::value, int>::type = 0>
    Value(T value) : kind(Kind::Number), number(static_cast<double>(value)) {}

    static Value Object(std::initializer_list<std::pair<std::string, Value>> values = {});
    static Value Array(std::initializer_list<Value> values = {});
    Value& operator[](const std::string& key);
    void Add(Value value);
    std::string Dump() const;

    Kind Type() const { return kind; }

    bool Boolean() const { return boolean; }

    double Number() const { return number; }

    const std::string& Text() const { return text; }

    const std::vector<Value>& Elements() const { return array; }

    const std::vector<std::pair<std::string, Value>>& Members() const { return object; }

private:
    Kind kind = Kind::Null;
    bool boolean = false;
    double number = 0;
    std::string text;
    std::vector<Value> array;
    std::vector<std::pair<std::string, Value>> object;
};

// Dynamic velocity and model-derived mobility remain distinct observations.
// Coordinates are map pixels: right/down positive; velocity is pixels/second.
struct MotionVector {
    enum class Source { Unknown, Native };
    Source source = Source::Unknown;
    double x = 0;
    double y = 0;
    Value Document() const;
};

struct MovementReference {
    bool known = false;
    std::string model;
    int effectiveSpeed = 0;
    int effectiveJump = 0;
    double maxSpeed = 0;
    double maxJumpHeight = 0;
    Value Document() const;
};

struct Observation {
    std::string status = "ok";
    Value data;
    std::string error;
};

}
