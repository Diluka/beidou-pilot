// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"

#include <cstdint>

namespace BeiDouBridge {

struct NativeActionState {
    MapleControl::Fact idle = MapleControl::Fact::Unknown;
    std::int32_t index = -1;
};

// BeiDou.exe V17 SHA256
// 1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df.
// 0x96A04F passes user+0x88 to Avatar::GetOneTimeAction (0x451B6A)
// and tests > -1. Its appearance remapping preserves the sign. Avatar's
// frame-boundary branch 0x452817 clears Avatar+0x4EC to -1. This is a
// one-time action fact, not attacking, grounding or a guessed pulse timeout.
template <class Read> NativeActionState ReadNativeActionState(std::uintptr_t user, const Read& read) {
    std::uint32_t first = 0, second = 0, index = 0;
    if (user == 0 || !read(user, first) || first != 0x00B3D20C || !read(user + 4, second) || second != 0x00B3D1E8
        || !read(user + 0x574, index))
        return {};
    NativeActionState result;
    result.index = static_cast<std::int32_t>(index);
    result.idle = result.index < 0 ? MapleControl::Fact::True : MapleControl::Fact::False;
    return result;
}

// Exact leaf classifier 0x4FB08F in the same image. These skills retain a
// native scan-code-dependent key-down state (user+0x3134/+0x3138); their keyup
// calls 0x95BEDF. A skill_id call with scan=0 cannot promise that release path.
// Reject rather than remap a user key or leave a charge running after clear.
inline bool IsNativeKeyDownSkill(std::uint32_t skillId) {
    switch (skillId) {
    case 0x111AE9:
    case 0x12A189:
    case 0x142829:
    case 0x205D29:
    case 0x21E3C9:
    case 0x236A69:
    case 0x2F9F6C:
    case 0x312609:
    case 0x4DD5CC:
    case 0x4F5C6A:
    case 0x4FAA8C:
    case 0xC80EDA:
    case 0xD7511E:
    case 0xE66C4B:
    case 0x1518A28:
    case 0x151FF59:
        return true;
    default:
        return false;
    }
}

struct NativeRepeatSettings {
    bool known = false;
    std::uint32_t firstDelayMs = 0;
    std::uint32_t intervalMs = 0;
};

// CInputSystem's constructor (0x59AA4D..0x59AAC0) obtains and bounds the
// actual OS repeat settings. GenerateRepeatEvent (0x59B2D2) selects +0x930
// for the first repeat and +0x934 thereafter. Check its two read instructions
// as well as the constructor's bounds; an unreadable/mismatched setting means
// no automatic repeat/retry, never a fabricated fallback frequency.
template <class Read> NativeRepeatSettings ReadNativeRepeatSettings(std::uintptr_t input, const Read& read) {
    std::uint32_t firstInstruction = 0, nextInstruction = 0, first = 0, interval = 0;
    if (input == 0 || !read(0x0059B307, firstInstruction) || firstInstruction != 0x0930968B
        || !read(0x0059B30F, nextInstruction) || nextInstruction != 0x0934968B || !read(input + 0x930, first)
        || !read(input + 0x934, interval) || first < 250 || first > 1000 || interval < 33 || interval > 400)
        return {};
    return {true, first, interval};
}

}
