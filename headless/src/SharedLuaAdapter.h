// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"
#include "TickNativeAdapter.h"
#include "Interaction.h"
#include "QuestInteraction.h"
#include <nlohmann/json.hpp>
#include "IO/KeyAction.h"

#include <chrono>
#include <filesystem>
#include <optional>
#include <set>
#include <string>

namespace ms {
class Equip;
}

// The same tick Lua runtime is linked into both hosts. This class only adapts
// the original open-source client state/observations/interactions and the local
// management transport; native player input is owned by TickNativeAdapter.
class SharedLuaAdapter final {
public:
    SharedLuaAdapter(std::filesystem::path directory, std::string runId);
    void Tick(std::uint64_t nativeTick);
    void Shutdown();
    bool Running() const;
    void Cancel(const std::string& reason);

    const MapleControl::State& Observe() const;
    MapleControl::Observation ObserveDomain(const std::string& domain) const;
    bool Logs(const std::string& scriptId, const std::vector<std::string>& lines);

private:
    friend class TickNativeAdapter;
    void SyncKeys();
    nlohmann::json ScriptState(const std::string& id) const;
    nlohmann::json ScriptsDocument() const;
    void Capture(std::uint64_t nativeTick);
    void ReadCommand();
    void ReadObservation();
    nlohmann::json ObservationData(const std::string& domain, std::string& status, std::string& error) const;
    std::string EquipmentReference(const ms::Equip* item) const;
    void Publish();
    void CaptureInteraction();
    bool OpenNpc(std::int32_t objectId, std::int32_t npcId, std::string& error);
    bool OpenServerNpc(std::int32_t objectId, std::int32_t npcId, std::string& error);
    bool RespondNpc(std::uint64_t revision, std::int8_t response, std::optional<std::int32_t> selection,
                    std::string& error);
    bool RequestQuest(const QuestRequest& request, std::string& error);
    nlohmann::json StateDocument() const;

    std::filesystem::path directory;
    std::string runId;
    MapleControl::State state;
    TickNativeAdapter tickAdapter;

    Interaction interaction;
    QuestInteraction questInteraction;
    std::string localQuestUnavailable;

    struct NpcTarget {
        std::int32_t templateId;
        std::string reference;
    };

    std::map<std::int32_t, NpcTarget> npcTargets;
    std::optional<std::uint64_t> shownDialogueRevision;
    std::set<ms::KeyAction::Id> physicalKeys;

    std::uint64_t inputEvents = 0;
    std::string latestScriptId;
    std::string commandScriptId;
    std::string commandId;
    std::string commandStatus = "idle";
    std::string commandReason;
    std::string lastConsumedId;
    std::string rejectedId;
    std::string rejectedReason;
    std::uint64_t lastPublishMs = 0;
    bool scriptCommand = false;
    // Destroy the runtime before the native input and host bookkeeping it may
    // release, including when the host unwinds after a native I/O failure.
    MapleControl::TickRuntime tickRuntime;
};
