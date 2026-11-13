// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Runtime.h"

namespace MapleControl {

// Native I/O only. Hosts must use a distinct adapter instance and independent
// input ownership from their coroutine Adapter. Begin/Result/Released describe
// the one-shot action only; SetHeldKeys updates persistent input independently.
class TickAdapter : public Adapter {
public:
    // Canonical names: left/right/up/down/jump/attack/pickup. The runtime sends
    // directional keys here; Begin owns one-shot keys and must not alter directions.
    virtual bool SetHeldKeys(const std::vector<std::string>& keys, std::string& error) = 0;
    // Confirm the most recent directional transition was consumed natively;
    // does not require an empty direction and is independent of the action slot.
    virtual bool HeldKeysSettled() const = 0;
    // Cancel the one-shot slot only. Never emit directional key-up/down edges;
    // another session may own movement. Released confirms action cancellation.
    virtual void ReleaseAction() = 0;
};

enum class ScriptMode { Coroutine, Tick, Invalid };

struct TickConfig {
    ScriptMode mode = ScriptMode::Coroutine;
    double budgetMs = 100;
    bool skipOverrun = false;
    bool abortCommit = true;
};

// Parse only file-level leading line comments (before executable Lua). Invalid
// declarations, duplicates and tick settings on coroutine scripts are rejected.
bool ParseTickConfig(const std::string& source, TickConfig& config, std::string& error);
ScriptMode ParseScriptMode(const std::string& source, std::string& error);

// Exactly one instance per client; multiple independent Lua states share this
// instance's movement intent and one-shot action slot. No Runtime state is used.
class TickRuntime {
public:
    explicit TickRuntime(TickAdapter& adapter);
    ~TickRuntime();
    TickRuntime(const TickRuntime&) = delete;
    TickRuntime& operator=(const TickRuntime&) = delete;

    // Chunk returns { main = function, context = table }, or defines global main.
    // Initialization is budgeted too. limitMs == 0 means no session deadline.
    bool Start(const std::string& scriptId, const std::string& source, std::uint32_t limitMs, std::string& error);
    // Call once after native state/action-completion facts have been updated.
    void Tick(bool sceneChanged = false);
    void Cancel(const std::string& scriptId, const std::string& reason);
    void CancelAll(const std::string& reason);
    bool Running() const;

    // Null for an unknown id; otherwise old Status basic fields plus mode,
    // control_released, tick and player. Statuses returns an admission-order array.
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
