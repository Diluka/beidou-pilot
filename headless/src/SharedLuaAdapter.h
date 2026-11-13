// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Runtime.h"
#include "TaskTransport.h"
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

// The same Lua runtime is linked into both hosts. This class only adapts the
// original open-source client state/actions and its local management transport.
class SharedLuaAdapter final : public MapleControl::Adapter {
public:
    SharedLuaAdapter(std::filesystem::path directory, std::string runId);
    void Tick(std::uint64_t nativeTick, bool externalActionBusy);
    void Shutdown();
    bool Running() const;
    void Cancel(const std::string& reason);

    const char* Backend() const override;
    const MapleControl::State& Observe() const override;
    MapleControl::Observation ObserveDomain(const std::string& domain) const override;
    bool Supports(MapleControl::ActionKind kind) const override;
    bool SupportsSkill() const override;
    bool SupportsMonsterHpPercent() const override;
    bool Skill(std::uint32_t id, MapleControl::SkillResult& result, std::string& error) override;
    bool Begin(const MapleControl::Action& action, std::string& error) override;
    MapleControl::ActionResult Result() const override;
    void Release() override;
    bool Released() const override;
    bool ReleasePending() const override;
    bool Logs(const std::string& scriptId, const std::vector<std::string>& lines) override;

private:
    friend class TickNativeAdapter;
    void SyncKeys();
    nlohmann::json ScriptState(const std::string& id) const;
    nlohmann::json ScriptsDocument() const;
    void Capture(std::uint64_t nativeTick);
    void ReadCommand(bool externalActionBusy);
    void ReadObservation();
    nlohmann::json ObservationData(const std::string& domain, std::string& status, std::string& error) const;
    void Publish();
    void ApplyRelease();
    MapleControl::AllocationFacts AllocationFacts() const;
    void CaptureAllocation();
    std::string EquipmentReference(const ms::Equip* item) const;
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
    MapleControl::Runtime runtime;
    MapleControl::TaskTransport taskTransport;
    MapleControl::ActionResult result;
    std::optional<MapleControl::AllocationRequest> allocationRequest;
    MapleControl::Allocation allocation;

    struct EquipmentChange {
        int sourceSlot;
        int destinationSlot;
        const ms::Equip* source;
        const ms::Equip* destination;
        std::uint32_t characterId;
        std::uint64_t sceneGeneration;
    };

    std::optional<EquipmentChange> equipmentChange;

    Interaction interaction;
    QuestInteraction questInteraction;
    std::string localQuestUnavailable;

    struct NpcTarget {
        std::int32_t templateId;
        std::string reference;
    };

    std::map<std::int32_t, NpcTarget> npcTargets;
    std::optional<std::uint64_t> shownDialogueRevision;
    std::optional<std::uint32_t> reviveCharacter;
    std::vector<ms::KeyAction::Id> heldActions;
    std::set<ms::KeyAction::Id> physicalKeys;

    struct LastSkill {
        std::uint32_t id;
        MapleControl::SkillResult result;
    };

    std::optional<LastSkill> lastSkill;
    std::uint64_t currentTick = 0;
    std::uint64_t releaseTick = 0;
    std::uint64_t actionUntilMs = 0;
    std::uint64_t lastPublishMs = 0;
    std::uint64_t inputEvents = 0;
    bool active = false;
    bool releasePending = false;
    bool scriptCommand = false;
    std::string latestScriptId;
    std::string commandScriptId;
    std::vector<nlohmann::json> scriptHistory;
    std::string commandId;
    std::string commandStatus = "idle";
    std::string commandReason;
    std::string lastConsumedId;
    std::string rejectedId;
    std::string rejectedReason;
    // Destroy the runtime before the native input and host bookkeeping it may
    // release, including when the host unwinds after a native I/O failure.
    MapleControl::TickRuntime tickRuntime;
};
