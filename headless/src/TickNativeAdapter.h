// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "TickRuntime.h"
#include "AutoAp.h"
#include "IO/KeyAction.h"

class SharedLuaAdapter;

// The tick engine's native input owner. The adapter only changes the desired
// native input and reports settled facts; native consumers own actual play.
class TickNativeAdapter final : public MapleControl::TickAdapter {
public:
    explicit TickNativeAdapter(SharedLuaAdapter& host);
    const MapleControl::State& Observe() const override;
    MapleControl::Observation ObserveDomain(const std::string& domain) const override;
    bool Supports(MapleControl::ActionKind kind) const override;
    bool SupportsSkill() const override;
    bool SetActionIntent(const MapleControl::Action& action, std::string& error) override;
    const MapleControl::Action* ActiveAction() const override;
    bool ActionIntentSettled() const override;
    MapleControl::ActionResult Result() const override;
    void Release() override;
    void ReleaseAction() override;
    bool Released() const override;
    bool ReleasePending() const override;
    bool Logs(const std::string& id, const std::vector<std::string>& lines) override;
    bool SetHeldKeys(const std::vector<std::string>& keys, std::string& error) override;
    bool HeldKeysSettled() const override;

    void Advance(std::uint64_t nativeTick, bool sceneChanged);
    void Shutdown();
    std::vector<ms::KeyAction::Id> Keys() const;

private:
    SharedLuaAdapter& host;
    std::vector<ms::KeyAction::Id> movement;
    std::vector<ms::KeyAction::Id> actionKeys;
    MapleControl::Action intent;
    MapleControl::Action activeAction;
    MapleControl::ActionResult result;
    std::uint64_t currentTick = 0;
    std::uint64_t intentTick = 0;
    std::uint64_t movementTick = 0;
    // Movement and jump transitions are observed by the local character's real
    // motion layer; other inputs keep their own native world-tick facts.
    std::uint64_t motionTick = 0;
    bool movementNeedsMotion = false;
    bool jumpNeedsMotion = false;
    std::uint64_t moveSequence = 0;
    std::uint64_t itemSequence = 0;
    std::array<std::uint32_t, 5> autoApExpected{};
    bool autoApPending = false;
    AutoApIdentity autoApIdentity;
    bool movementChanged = false;
    bool intentChanged = false;
    bool nativeActive = false;
};
