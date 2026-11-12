// SPDX-License-Identifier: AGPL-3.0-or-later
#include "QuestInteraction.h"

#include <nlnx/node.hpp>
#include <nlnx/nx.hpp>

#include <algorithm>
#include <charconv>
#include <initializer_list>
#include <limits>
#include <map>

namespace {
constexpr auto Source = "client_local_quest";
using MapleControl::Fact;

std::optional<std::int32_t> Integer(nl::node node) {
    if (node.data_type() != nl::node::type::integer || node.size() != 0) return std::nullopt;
    const auto value = node.get_integer();
    if (value < std::numeric_limits<std::int32_t>::min() || value > std::numeric_limits<std::int32_t>::max())
        return std::nullopt;
    return static_cast<std::int32_t>(value);
}

std::optional<std::int32_t> Number(const std::string& name) {
    std::int32_t value;
    const auto parsed = std::from_chars(name.data(), name.data() + name.size(), value);
    if (parsed.ec != std::errc() || parsed.ptr != name.data() + name.size() || value < 0) return std::nullopt;
    return value;
}

bool HasOnlyFields(nl::node record, std::initializer_list<const char*> supported) {
    if (record.data_type() != nl::node::type::none) return false;
    for (auto field : record) {
        const auto name = field.name();
        if (std::none_of(supported.begin(), supported.end(), [&](const char* key) { return name == key; }))
            return false;
    }
    return true;
}
}

QuestInteraction::QuestInteraction(Interaction& model, Sender send, DialogOpener open)
    : interaction(model), sender(std::move(send)), dialogOpener(std::move(open)) {}

QuestInteraction::~QuestInteraction() {
    Reset();
}

bool QuestInteraction::Load(std::string& error) {
    if (resourcesLoaded) return true;
    const auto root = nl::nx::Quest;
    if (!root) {
        error = "quest_resources_unavailable";
        return false;
    }
    const auto info = root["QuestInfo.img"];
    const auto check = root["Check.img"];
    if (!info || !check) {
        error = "quest_resource_layout_unsupported";
        return false;
    }

    const auto readPages = [](nl::node node, bool branches) {
        Sequence result;
        if (!node) return result;
        if (node.data_type() != nl::node::type::none) {
            result.known = false;
            return result;
        }
        std::map<std::int32_t, std::string> pages;
        for (auto child : node) {
            const auto name = child.name();
            const auto index = Number(name);
            if (!index) {
                if (!branches || (name != "yes" && name != "no" && name != "stop")) result.known = false;
            } else if (child.data_type() != nl::node::type::string) {
                result.known = false;
            } else {
                if (!pages.emplace(*index, child.get_string()).second) result.known = false;
            }
        }
        for (const auto& [index, text] : pages) {
            if (index != static_cast<std::int32_t>(result.pages.size())) result.known = false;
            result.pages.push_back(text);
        }
        return result;
    };
    const auto readRequirements = [](nl::node node) {
        Requirements result;
        if (!node || node.data_type() != nl::node::type::none) {
            result.unknown = true;
            return result;
        }
        for (auto condition : node) {
            const auto name = condition.name();
            if (name == "npc" || name == "lvmin" || name == "lvmax") {
                const auto value = Integer(condition);
                if (!value)
                    result.unknown = true;
                else if (name == "npc")
                    result.npc = *value;
                else if (name == "lvmin")
                    result.minimumLevel = *value;
                else
                    result.maximumLevel = *value;
            } else if (name == "job") {
                if (condition.data_type() != nl::node::type::none) {
                    result.unknown = true;
                    continue;
                }
                std::vector<std::int32_t> jobs;
                bool known = true;
                for (auto job : condition) {
                    const auto value = Integer(job);
                    if (value)
                        jobs.push_back(*value);
                    else
                        known = false;
                }
                if (known)
                    result.jobs = std::move(jobs);
                else
                    result.unknown = true;
            } else if (name == "quest") {
                if (condition.data_type() != nl::node::type::none) result.unknown = true;
                for (auto quest : condition) {
                    if (!HasOnlyFields(quest, {"id", "state"})) {
                        result.unknown = true;
                        continue;
                    }
                    const auto id = Integer(quest["id"]);
                    const auto status = Integer(quest["state"]);
                    if (!id || *id < 1 || *id > 32767 || !status || *status < 0 || *status > 2)
                        result.unknown = true;
                    else
                        result.quests.emplace_back(static_cast<std::int16_t>(*id), *status);
                }
            } else if (name == "item") {
                if (condition.data_type() != nl::node::type::none) result.unknown = true;
                for (auto item : condition) {
                    if (!HasOnlyFields(item, {"id", "count"})) {
                        result.unknown = true;
                        continue;
                    }
                    const auto id = Integer(item["id"]);
                    const auto count = Integer(item["count"]);
                    if (!id || *id / 1000000 < 1 || *id / 1000000 > 5 || !count)
                        result.unknown = true;
                    else
                        result.items.emplace_back(static_cast<std::uint32_t>(*id), *count);
                }
            } else if (name == "mob") {
                if (condition.data_type() != nl::node::type::none || condition.size() != 1) {
                    result.unknown = true;
                    continue;
                }
                const auto mob = *condition.begin();
                if (!HasOnlyFields(mob, {"id", "count"})) {
                    result.unknown = true;
                    continue;
                }
                const auto id = Integer(mob["id"]);
                const auto count = Integer(mob["count"]);
                if (!id || *id < 1 || !count || *count < 1 || *count > 999)
                    result.unknown = true;
                else
                    result.mob = std::pair{static_cast<std::uint32_t>(*id), *count};
            } else {
                result.unknown = true;
            }
        }
        return result;
    };
    const auto readActions = [](nl::node node, Requirements& requirements) {
        if (!node || node.data_type() != nl::node::type::none) return false;
        bool known = true;
        std::map<std::uint32_t, std::int64_t> costs;
        for (auto action : node) {
            const auto name = action.name();
            if (name == "exp" || name == "nextQuest") {
                const auto value = Integer(action);
                if (!value || *value < 0) known = false;
            } else if (name == "item" && action.data_type() == nl::node::type::none) {
                for (auto item : action) {
                    const auto id = Integer(item["id"]);
                    const auto count = Integer(item["count"]);
                    if (!id || *id / 1000000 < 1 || *id / 1000000 > 5 || !count) {
                        known = false;
                        continue;
                    }
                    if (!HasOnlyFields(item, {"id", "count"})) {
                        known = false;
                        continue;
                    }
                    if (*count < 0) costs[static_cast<std::uint32_t>(*id)] -= static_cast<std::int64_t>(*count);
                }
            } else {
                known = false;
            }
        }
        for (const auto& [id, count] : costs) {
            if (count > std::numeric_limits<std::int32_t>::max())
                known = false;
            else
                requirements.items.emplace_back(id, static_cast<std::int32_t>(count));
        }
        return known;
    };

    std::vector<Definition> parsed;
    for (auto entry : info) {
        const auto id = Number(entry.name());
        const auto title = entry["name"];
        if (!id || *id < 1 || *id > 32767 || title.data_type() != nl::node::type::string) continue;
        Definition definition{};
        definition.id = static_cast<std::int16_t>(*id);
        definition.name = title.get_string();
        if (definition.name.empty()) continue;
        for (std::size_t index = 0; index < definition.logs.size(); ++index) {
            const auto text = entry[static_cast<unsigned int>(index)];
            if (text.data_type() == nl::node::type::string) definition.logs[index] = text.get_string();
        }
        for (const auto flag : {"autoStart", "autoPreComplete", "autoComplete", "repeatable", "blocked"}) {
            const auto value = entry[flag];
            if (value && Integer(value) != 0) definition.ordinary = false;
        }
        const auto say = root["Say.img"][entry.name()];
        definition.start = readPages(say["0"], true);
        definition.accepted = readPages(say["0"]["yes"], false);
        definition.declined = readPages(say["0"]["no"], false);
        definition.completion = readPages(say["1"], true);
        for (std::size_t phase = 0; phase < definition.requirements.size(); ++phase) {
            const auto key = std::to_string(phase);
            auto& requirements = definition.requirements[phase];
            requirements = readRequirements(check[entry.name()][key]);
            definition.actionsKnown[phase] = readActions(root["Act.img"][entry.name()][key], requirements);
        }
        parsed.push_back(std::move(definition));
    }
    definitions = std::move(parsed);
    resourcesLoaded = true;
    return true;
}

std::int32_t QuestInteraction::Status(const Definition& definition) const {
    if (!state->ready || !state->characterKnown) return -1;
    if (quests->get_started().contains(definition.id)) return 1;
    if (quests->get_completed().contains(definition.id)) return 2;
    return 0;
}

bool QuestInteraction::HasBody(const Definition& definition) const {
    switch (Status(definition)) {
    case 0:
        return (definition.start.known && !definition.start.pages.empty()) || definition.logs[0].has_value();
    case 1:
        return definition.logs[1].has_value()
               || (definition.completion.known && !definition.completion.pages.empty()
                   && Eligible(definition, QuestPhase::Complete) == Fact::True);
    case 2:
        return definition.logs[2].has_value();
    default:
        return false;
    }
}

Fact QuestInteraction::Presence(const Definition& definition) const {
    if (definition.requirements[0].npc != npcId && definition.requirements[1].npc != npcId) return Fact::False;
    switch (Status(definition)) {
    case 0:
        return Eligible(definition, QuestPhase::Start);
    case 1:
        return Fact::True;
    case 2:
        return Fact::False;
    default:
        return Fact::Unknown;
    }
}

Fact QuestInteraction::Eligible(const Definition& definition, QuestPhase phase) const {
    if (!state->ready || !state->characterKnown) return Fact::Unknown;
    const auto index = phase == QuestPhase::Start ? 0 : 1;
    if (Status(definition) != index) return Fact::False;
    const auto& requirements = definition.requirements[index];
    const bool bodyKnown =
        phase == QuestPhase::Start
            ? (definition.start.known && !definition.start.pages.empty()) || definition.logs[0].has_value()
            : (definition.completion.known && !definition.completion.pages.empty()) || definition.logs[1].has_value();
    bool unknown = requirements.unknown || !definition.ordinary || !definition.actionsKnown[index] || !bodyKnown;
    if (phase == QuestPhase::Start)
        unknown = unknown || !definition.start.known || !definition.accepted.known || !definition.declined.known;
    else
        unknown = unknown || !definition.completion.known;
    if (requirements.npc && *requirements.npc != npcId) return Fact::False;
    if (requirements.jobs) {
        if (!state->character.known[1])
            unknown = true;
        else if (std::find(requirements.jobs->begin(), requirements.jobs->end(), state->character.values[1])
                 == requirements.jobs->end())
            return Fact::False;
    }
    if (requirements.minimumLevel || requirements.maximumLevel) {
        if (!state->character.known[0])
            unknown = true;
        else {
            const auto level = static_cast<std::int64_t>(state->character.values[0]);
            if (requirements.minimumLevel && level < *requirements.minimumLevel) return Fact::False;
            if (requirements.maximumLevel && level > *requirements.maximumLevel) return Fact::False;
        }
    }
    for (const auto& [id, expected] : requirements.quests) {
        const auto actual = quests->get_started().contains(id) ? 1 : quests->get_completed().contains(id) ? 2 : 0;
        if (actual != expected) return Fact::False;
    }
    if (!requirements.items.empty()) {
        if (!state->inventoryKnown)
            unknown = true;
        else
            for (const auto& [id, needed] : requirements.items) {
                std::int64_t count = 0;
                bool known = true;
                for (const auto& item : state->inventory) {
                    if (item.itemId != id) continue;
                    if (!item.quantityKnown)
                        known = false;
                    else
                        count += item.quantity;
                }
                if (!known)
                    unknown = true;
                else if ((needed > 0 && count < needed) || (needed <= 0 && count > 0))
                    return Fact::False;
            }
    }
    if (requirements.mob) {
        if (phase != QuestPhase::Complete)
            unknown = true;
        else {
            const auto& progress = quests->get_started().at(definition.id);
            // This version pads each ordinary mob counter to three digits. Only a single target is mapped.
            if (progress.size() != 3
                || !std::all_of(progress.begin(), progress.end(), [](char c) { return c >= '0' && c <= '9'; }))
                unknown = true;
            else if (std::stoi(progress) < requirements.mob->second)
                return Fact::False;
        }
    }
    return unknown ? Fact::Unknown : Fact::True;
}

bool QuestInteraction::Open(std::uint32_t objectId, std::int32_t npc, const MapleControl::State& current,
                            const ms::QuestLog& currentQuests, std::string& error) {
    Reset();
    state = &current;
    quests = &currentQuests;
    npcObjectId = objectId;
    npcId = npc;
    error.clear();
    if (!Load(error)) return false;
    bool present = false;
    bool unknown = false;
    for (const auto& definition : definitions) {
        const auto presence = Presence(definition);
        present = present || presence == Fact::True;
        unknown = unknown || presence == Fact::Unknown;
    }
    if (!present) {
        if (unknown) error = "quest_start_conditions_unknown";
        return false;
    }
    view = View::List;
    Render();
    return true;
}

void QuestInteraction::Select(const Definition& definition) {
    selected = &definition;
    sequence.clear();
    page = 0;
    const auto status = Status(definition);
    if (status == 0) {
        view = View::Start;
        if (definition.start.known) sequence = definition.start.pages;
        if (sequence.empty() && definition.logs[0]) sequence.push_back(*definition.logs[0]);
    } else if (status == 2) {
        view = View::Completed;
    } else {
        view = View::Detail;
        if (Eligible(definition, QuestPhase::Complete) == Fact::True && definition.completion.known)
            sequence = definition.completion.pages;
        if (sequence.empty() && definition.logs[1]) sequence.push_back(*definition.logs[1]);
    }
    Render();
}

std::optional<std::string> QuestInteraction::Text(Fact eligibility) const {
    std::optional<std::string> text;
    if (view == View::Start || view == View::Reply || view == View::Detail) {
        if (page < sequence.size()) text = sequence[page];
    } else if (view == View::Completed) {
        text = selected->logs[2];
    }
    if (text && (view == View::Start || view == View::Detail)) {
        *text += eligibility == Fact::True    ? "\n\n条件已满足。"
                 : eligibility == Fact::False ? "\n\n条件尚未满足。"
                                              : "\n\n部分条件未知，无法确认。";
        if (view == View::Detail && Status(*selected) == 1)
            *text += "\n任务进度：" + quests->get_started().at(selected->id);
    }
    if (text && (pending || (view == View::Detail && eligibility == Fact::True))) *text += "\n\n待确认。";
    return text;
}

void QuestInteraction::Render() {
    renderedList.clear();
    if (view == View::List) {
        std::vector<const Definition*> rows;
        renderedUnknown = false;
        for (const auto& definition : definitions) {
            const auto presence = Presence(definition);
            if (presence == Fact::Unknown) renderedUnknown = true;
            if (presence == Fact::True) rows.push_back(&definition);
        }
        if (rows.empty()) {
            Reset();
            return;
        }
        interaction.BeginPage({Source, "本地任务",
                               renderedUnknown ? std::optional<std::string>("部分任务条件未知。") : std::nullopt,
                               std::vector<InteractionControl>{}});
        for (const auto* row : rows) {
            const auto& definition = *row;
            const bool readable = HasBody(definition);
            renderedList.emplace_back(definition.id, Status(definition), readable);
            interaction.AddControl("option", definition.name, readable ? Fact::True : Fact::Unknown,
                                   [this, definition = &definition](std::string&) {
                                       Select(*definition);
                                       return true;
                                   });
        }
        interaction.AddControl("button", "交谈", Fact::True, [this](std::string& error) {
            const auto objectId = npcObjectId;
            const auto npc = npcId;
            Reset();
            return dialogOpener(objectId, npc, error);
        });
    } else {
        renderedStatus = Status(*selected);
        renderedEligibility = view == View::Start    ? Eligible(*selected, QuestPhase::Start)
                              : view == View::Detail ? Eligible(*selected, QuestPhase::Complete)
                                                     : Fact::False;
        renderedText = Text(renderedEligibility);
        const auto title = selected->name
                           + (view == View::Completed                                     ? " · 已完成"
                              : view == View::Detail && renderedEligibility == Fact::True ? " · 交付详情"
                                                                                          : " · 任务详情");
        interaction.BeginPage({Source, title, renderedText, std::vector<InteractionControl>{}});
        if (!pending) {
            if (view == View::Start || view == View::Reply || view == View::Detail) {
                if (page > 0)
                    interaction.AddControl("button", "上一页", Fact::True, [this](std::string&) {
                        --page;
                        Render();
                        return true;
                    });
                if (page + 1 < sequence.size())
                    interaction.AddControl("button", "下一页", Fact::True, [this](std::string&) {
                        ++page;
                        Render();
                        return true;
                    });
                else if (view == View::Start) {
                    interaction.AddControl("button", "接受", renderedEligibility,
                                           [this](std::string& error) { return Confirm(error); });
                    interaction.AddControl("button", "暂不接受", Fact::True, [this](std::string&) {
                        if (selected->declined.known && !selected->declined.pages.empty()) {
                            sequence = selected->declined.pages;
                            page = 0;
                            view = View::Reply;
                            Render();
                        } else
                            Reset();
                        return true;
                    });
                } else if (view == View::Detail) {
                    interaction.AddControl("button", "交付", renderedEligibility,
                                           [this](std::string& error) { return Confirm(error); });
                }
            }
            interaction.AddControl("button", "返回列表", Fact::True, [this](std::string&) {
                selected = nullptr;
                sequence.clear();
                page = 0;
                view = View::List;
                Render();
                return true;
            });
        }
    }
    interaction.AddControl("button", "关闭", Fact::True, [this](std::string&) {
        Reset();
        return true;
    });
}

bool QuestInteraction::Confirm(std::string& error) {
    const auto phase = view == View::Start ? QuestPhase::Start : QuestPhase::Complete;
    if (Eligible(*selected, phase) != Fact::True) {
        error = "quest_conditions_not_met_or_unknown";
        Render();
        return false;
    }
    const QuestRequest request{phase, selected->id, npcObjectId, npcId};
    if (!sender(request, error)) return false;
    pending = request;
    Render();
    return true;
}

void QuestInteraction::Refresh(const MapleControl::State& current, const ms::QuestLog& currentQuests) {
    if (view == View::Closed) return;
    state = &current;
    quests = &currentQuests;
    if (pending) {
        const auto status = Status(*selected);
        if (status == 2) {
            pending.reset();
            view = View::Completed;
            Render();
        } else if (pending->phase == QuestPhase::Start && status == 1) {
            pending.reset();
            sequence = selected->accepted.pages;
            page = 0;
            view = sequence.empty() ? View::Detail : View::Reply;
            Render();
        }
        return;
    }
    if (view == View::List) {
        std::vector<std::tuple<std::int16_t, std::int32_t, bool>> statuses;
        bool unknown = false;
        for (const auto& definition : definitions) {
            const auto presence = Presence(definition);
            if (presence == Fact::Unknown) unknown = true;
            if (presence == Fact::True) statuses.emplace_back(definition.id, Status(definition), HasBody(definition));
        }
        if (statuses != renderedList || unknown != renderedUnknown) Render();
    } else if (view != View::Reply) {
        if (Status(*selected) != renderedStatus) {
            Select(*selected);
            return;
        }
        const auto eligibility = view == View::Start    ? Eligible(*selected, QuestPhase::Start)
                                 : view == View::Detail ? Eligible(*selected, QuestPhase::Complete)
                                                        : Fact::False;
        if (view == View::Detail && eligibility != renderedEligibility) {
            Select(*selected);
            return;
        }
        if (eligibility != renderedEligibility || Text(eligibility) != renderedText) Render();
    }
}

void QuestInteraction::Reset() {
    const auto* current = interaction.CurrentPage();
    if (current && current->source == Source) interaction.ClosePage();
    view = View::Closed;
    selected = nullptr;
    sequence.clear();
    pending.reset();
    renderedList.clear();
}
