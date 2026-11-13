// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "TickRuntime.h"
#include "IO/KeyAction.h"

class SharedLuaAdapter;

// A second native input owner, not a wrapper around the coroutine adapter's
// Begin/Release lifecycle. Both owners meet only at the physical key boundary.
class TickNativeAdapter final : public MapleControl::TickAdapter {
public:
    explicit TickNativeAdapter(SharedLuaAdapter& host);
    const char* Backend() const override;
    const MapleControl::State& Observe() const override;
    MapleControl::Observation ObserveDomain(const std::string& domain) const override;
    bool Supports(MapleControl::ActionKind kind) const override;
    bool SupportsSkill() const override;
    bool Begin(const MapleControl::Action& action, std::string& error) override;
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
    MapleControl::ActionResult result;
    std::uint64_t currentTick = 0;
    std::uint64_t releaseTick = 0;
    std::uint64_t deadlineMs = 0;
    std::uint64_t movementTick = 0;
    bool movementChanged = false;
    MapleControl::ActionKind actionKind = MapleControl::ActionKind::Stop;
    bool active = false;
    bool pulseReleased = false;
    bool releasing = false;
};
