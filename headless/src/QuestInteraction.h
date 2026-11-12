// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Interaction.h"

#include "Character/QuestLog.h"

#include <array>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

enum class QuestPhase { Start, Complete };

struct QuestRequest {
    QuestPhase phase;
    std::int16_t questId;
    std::uint32_t npcObjectId;
    std::int32_t npcId;
};

// This is a client-owned UI provider. Its request type never enters the public game API.
class QuestInteraction {
public:
    using Sender = std::function<bool(const QuestRequest&, std::string&)>;
    using DialogOpener = std::function<bool(std::uint32_t, std::int32_t, std::string&)>;

    QuestInteraction(Interaction& interaction, Sender sender, DialogOpener opener);
    ~QuestInteraction();

    // Native state and quest objects remain alive while this provider owns a page.
    // A false result with no error means this provider has no presentable entries for this NPC.
    bool Open(std::uint32_t objectId, std::int32_t npcId, const MapleControl::State& state, const ms::QuestLog& quests,
              std::string& error);
    void Refresh(const MapleControl::State& state, const ms::QuestLog& quests);
    // The owner calls this when its interaction context changes or another provider takes the page.
    void Reset();

private:
    struct Requirements {
        bool unknown = false;
        std::optional<std::int32_t> npc;
        std::optional<std::vector<std::int32_t>> jobs;
        std::optional<std::int32_t> minimumLevel;
        std::optional<std::int32_t> maximumLevel;
        std::vector<std::pair<std::int16_t, std::int32_t>> quests;
        std::vector<std::pair<std::uint32_t, std::int32_t>> items;
        std::optional<std::pair<std::uint32_t, std::int32_t>> mob;
    };

    struct Sequence {
        bool known = true;
        std::vector<std::string> pages;
    };

    struct Definition {
        std::int16_t id;
        std::string name;
        std::array<std::optional<std::string>, 3> logs;
        std::array<Requirements, 2> requirements;
        std::array<bool, 2> actionsKnown;
        bool ordinary = true;
        Sequence start;
        Sequence accepted;
        Sequence declined;
        Sequence completion;
    };

    enum class View { Closed, List, Start, Reply, Detail, Completed };

    bool Load(std::string& error);
    std::int32_t Status(const Definition& definition) const;
    bool HasBody(const Definition& definition) const;
    MapleControl::Fact Presence(const Definition& definition) const;
    MapleControl::Fact Eligible(const Definition& definition, QuestPhase phase) const;
    void Select(const Definition& definition);
    std::optional<std::string> Text(MapleControl::Fact eligibility) const;
    void Render();
    bool Confirm(std::string& error);

    Interaction& interaction;
    Sender sender;
    DialogOpener dialogOpener;
    bool resourcesLoaded = false;
    std::vector<Definition> definitions;
    const MapleControl::State* state = nullptr;
    const ms::QuestLog* quests = nullptr;
    std::uint32_t npcObjectId = 0;
    std::int32_t npcId = 0;
    const Definition* selected = nullptr;
    View view = View::Closed;
    std::vector<std::string> sequence;
    std::size_t page = 0;
    std::optional<QuestRequest> pending;
    std::optional<std::string> renderedText;
    MapleControl::Fact renderedEligibility = MapleControl::Fact::Unknown;
    std::int32_t renderedStatus = 0;
    std::vector<std::tuple<std::int16_t, std::int32_t, bool>> renderedList;
    bool renderedUnknown = false;
};
