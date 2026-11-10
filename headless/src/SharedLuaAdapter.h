// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Runtime.h"
#include "TaskTransport.h"
#include "Interaction.h"
#include "QuestInteraction.h"
#include <nlohmann/json.hpp>
#include "IO/KeyAction.h"

#include <chrono>
#include <filesystem>
#include <optional>
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
    bool Begin(const MapleControl::Action& action, std::string& error) override;
    MapleControl::ActionResult Result() const override;
    void Release() override;
    bool Released() const override;
    bool ReleasePending() const override;
    bool Logs(const std::string& scriptId, const std::vector<std::string>& lines) override;

private:
    void Capture(std::uint64_t nativeTick);
    void ReadCommand(bool externalActionBusy);
    void ReadObservation();
    nlohmann::json ObservationData(const std::string& domain, std::string& status, std::string& error) const;
    void Publish();
    void ApplyRelease();
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
    MapleControl::Runtime runtime;
    MapleControl::TaskTransport taskTransport;
    MapleControl::ActionResult result;

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
    std::optional<ms::KeyAction::Id> heldAction;
    std::uint64_t currentTick = 0;
    std::uint64_t releaseTick = 0;
    std::uint64_t actionUntilMs = 0;
    std::uint64_t lastPublishMs = 0;
    std::uint64_t inputEvents = 0;
    bool active = false;
    bool releasePending = false;
    bool scriptCommand = false;
    std::string commandId;
    std::string commandStatus = "idle";
    std::string commandReason;
    std::string lastConsumedId;
    std::string rejectedId;
    std::string rejectedReason;
};
