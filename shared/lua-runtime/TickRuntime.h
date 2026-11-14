// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"

#include <chrono>
#include <functional>
#include <memory>

namespace MapleControl {

// Native I/O only. A held intent is not an execution queue: native consumers
// implement its actual press/hold/release behavior and the Lua scheduler never
// replays it every tick.
class TickAdapter : public Adapter {
public:
    // ObserveDomain("terrain") is an internal, current-map static observation,
    // not a public game domain. On "ok", data contains map_id/source/footholds/
    // ropes, validated by the local resource producer. Other statuses preserve
    // their error/message/details without geometry. No cross-backend fallback.
    // Canonical direction names: left/right/up/down. Action keys belong to
    // SetActionIntent and must not alter these directional keys.
    virtual bool SetHeldKeys(const std::vector<std::string>& keys, std::string& error) = 0;
    virtual bool HeldKeysSettled() const = 0;
    // Stop clears only the action input. Repeating the same input is idempotent;
    // replacing it never overwrites an already-started native action.
    virtual bool SetActionIntent(const Action& action, std::string& error) = 0;
    // Confirmation of the latest input transition, including the old key-up.
    // May be true while the new input is held and while an old animation runs.
    virtual bool ActionIntentSettled() const = 0;
    // Native execution metadata, not the desired input. Null if none is known.
    // The pointed-to action remains valid until the adapter's next native update.
    virtual const Action* ActiveAction() const = 0;
    // Clear action input without touching direction or interrupting native animation.
    virtual void ReleaseAction() = 0;
    // Full input release, including the direction currently owned.
    virtual void Release() = 0;
    virtual bool Released() const = 0;
    virtual bool ReleasePending() const = 0;
};

// Decision cadence only; Native runs once per host update without throttling.
enum class TickGear { TenHz = 1, TwentyHz = 2, ThirtyHz = 3, Native = 4 };

struct TickConfig {
    TickGear gear = TickGear::ThirtyHz;
    double budgetMs = 100;
    bool skipOverrun = false;
    bool abortCommit = true;
};

// Parse only file-level leading line comments (before executable Lua). Scripts
// are tick scripts: an omitted @mode means tick, and any other mode is rejected.
// Invalid declarations and duplicates are rejected.
bool ParseTickConfig(const std::string& source, TickConfig& config, std::string& error);

// Exactly one instance per client; multiple independent Lua states share this
// instance's movement and action input intents.
class TickRuntime {
public:
    // Scheduling time only. Execution budgets and profiling always use real time.
    using Now = std::function<std::chrono::steady_clock::time_point()>;
    explicit TickRuntime(TickAdapter& adapter, Now now = std::chrono::steady_clock::now);
    ~TickRuntime();
    TickRuntime(const TickRuntime&) = delete;
    TickRuntime& operator=(const TickRuntime&) = delete;

    // Chunk returns { main = function, context = table }, or defines global main.
    // Initialization is budgeted too. limitMs == 0 means no session deadline.
    bool Start(const std::string& scriptId, const std::string& source, std::uint32_t limitMs, std::string& error);
    // Call every host update after native state/action-completion facts advance.
    // Cadence gates main/core reads only, never lifecycle, input release or drain.
    void Tick(bool sceneChanged = false);
    void Cancel(const std::string& scriptId, const std::string& reason);
    void CancelAll(const std::string& reason);
    bool Running() const;

    // Null for an unknown id; otherwise the tick session status. Statuses
    // returns an admission-order array.
    Value CurrentStatus(const std::string& scriptId) const;
    Value Statuses() const;

    // Fixed-size, runtime-lifetime aggregates, also exposed as tick.profile in
    // each session status (shared, not per-session). Available with no scripts.
    // host_tick_calls includes idle/reentrant early returns; active_frames counts
    // calls passing the updating/Running guard, including transition/drain frames.
    // Timings are inclusive steady-clock microseconds: samples/total_us/max_us.
    // observe includes snapshot copying; refresh_core includes core domain reads;
    // lua measures main calls including bindings/lazy reads, excluding initialization.
    // Only Tick is measured, not Start, status serialization or host Capture.
    // Compare count/total deltas for intervals; maxima are lifetime peaks.
    Value Profile() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};

}
