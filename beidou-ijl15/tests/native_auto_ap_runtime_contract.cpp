// SPDX-License-Identifier: AGPL-3.0-or-later
// Integrates the real shared TickRuntime with a model of GUI admission. The
// injected host callback is adversarial and does not prove that production
// logging actually mutates input or reenters the GUI bridge.
#include "TickRuntime.h"
#include "NativeTickInput.h"
#include <cassert>
#include <string>
#include <vector>

struct Adapter final : MapleControl::TickAdapter {
    MapleControl::State state;
    BeiDouBridge::NativeTickInput input;
    bool inject = false;
    unsigned releases = 0;
    unsigned acceptedLogs = 0;
    unsigned busyLogs = 0;

    Adapter() {
        state.instanceId = "test";
        state.inGame = state.ready = state.characterKnown = state.positionKnown = state.mapKnown = true;
        state.character.id = 7;
        state.character.known.fill(true);
        state.character.values[6] = 100;
        state.sceneGeneration = 1;
    }

    const MapleControl::State& Observe() const override { return state; }

    bool Supports(MapleControl::ActionKind kind) const override {
        return kind == MapleControl::ActionKind::AutoAp && input.Intent().kind != kind;
    }

    bool SetActionIntent(const MapleControl::Action& action, std::string& error) override {
        if (action.kind == MapleControl::ActionKind::AutoAp
            && (action.autoApInstanceId != state.instanceId || action.autoApCharacterId != state.character.id
                || action.autoApSceneGeneration != state.sceneGeneration)) {
            error = "auto_ap_identity_changed";
            return false;
        }
        if (action.kind == MapleControl::ActionKind::AutoAp && input.Intent().kind == action.kind
            && action.sessionId != input.Intent().sessionId) {
            error = "auto_ap_input_busy";
            return false;
        }
        input.SetIntent(action, 7);
        return true;
    }

    bool SetHeldKeys(const std::vector<std::string>&, std::string&) override { return true; }

    bool HeldKeysSettled() const override { return true; }

    bool ActionIntentSettled() const override { return input.ActionIntentSettled(); }

    const MapleControl::Action* ActiveAction() const override { return nullptr; }

    MapleControl::ActionResult Result() const override { return input.Result(); }

    void ReleaseAction() override {
        ++releases;
        input.ReleaseAction();
    }

    void Release() override { input.Release(7); }

    bool Released() const override { return input.Released(); }

    bool ReleasePending() const override { return input.ReleasePending(); }

    bool Logs(const std::string&, const std::vector<std::string>& lines) override {
        for (const auto& line : lines) {
            if (line == "accepted") ++acceptedLogs;
            if (line == "input_busy") ++busyLogs;
        }
        if (inject) {
            inject = false;
            MapleControl::Action other;
            other.kind = MapleControl::ActionKind::AutoAp;
            other.sessionId = "external";
            input.SetIntent(other, 7);
        }
        return true;
    }
};

int main() {
    const std::string script =
        "-- @tick.gear 4\nfunction main(c) local ok, reason = c.game.player.auto_ap('test', 7, 1); "
        "if ok then c.game.log('accepted') else c.game.log(reason) end end";
    std::string error;
    {
        Adapter adapter;
        MapleControl::TickRuntime runtime(adapter);
        assert(runtime.Start("a", script, 1000, error));
        assert(runtime.Start("b", script, 1000, error));
        runtime.Tick();
        assert(adapter.acceptedLogs == 1);
        assert(adapter.busyLogs == 1);
        assert(adapter.input.Intent().sessionId == "a");
    }
    {
        Adapter adapter;
        MapleControl::TickRuntime runtime(adapter);
        assert(runtime.Start("a", script, 1000, error));
        runtime.Tick();
        assert(adapter.input.Intent().sessionId == "a");
        assert(runtime.Start("b", script, 1000, error));
        runtime.Tick();
        assert(adapter.busyLogs == 1);
        assert(adapter.input.Intent().sessionId == "a");
        assert(adapter.releases == 0);
    }
    {
        Adapter adapter;
        adapter.state.character.id = 8; // Caller retained the original id 7 before opening the window.
        MapleControl::TickRuntime runtime(adapter);
        assert(runtime.Start("a", script, 1000, error));
        runtime.Tick();
        assert(adapter.input.Intent().kind == MapleControl::ActionKind::Stop);
        assert(!adapter.input.Dispatched());
        assert(adapter.releases == 1);
    }
    {
        Adapter adapter;
        MapleControl::TickRuntime runtime(adapter);
        assert(runtime.Start("a", script, 1000, error));
        adapter.inject = true;
        runtime.Tick();
        // Forced host interleaving shows rejection calls ReleaseAction; it is
        // not evidence that this interleaving is reachable in production.
        assert(adapter.acceptedLogs == 1);
        assert(adapter.releases == 1);
        assert(adapter.input.Intent().kind == MapleControl::ActionKind::Stop);
    }
}
