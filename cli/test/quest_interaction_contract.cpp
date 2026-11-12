// SPDX-License-Identifier: AGPL-3.0-or-later
#include "QuestInteraction.h"
#include "Util/NxFiles.h"

#include <nlnx/node.hpp>
#include <nlnx/nx.hpp>

#include <algorithm>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void Check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::string Reference(const Interaction& model, const std::string& text) {
    const auto* page = model.CurrentPage();
    Check(page && page->controls.has_value(), "known_page_controls_missing");
    for (const auto& control : *page->controls)
        if (control.text == text) return control.ref;
    throw std::runtime_error("expected_control_missing: " + text);
}

MapleControl::Fact Enabled(const Interaction& model, const std::string& text) {
    const auto* page = model.CurrentPage();
    Check(page && page->controls.has_value(), "known_page_controls_missing");
    for (const auto& control : *page->controls)
        if (control.text == text) return control.enabled;
    throw std::runtime_error("expected_control_missing: " + text);
}

bool HasControl(const Interaction& model, const std::string& text) {
    const auto* page = model.CurrentPage();
    Check(page && page->controls.has_value(), "known_page_controls_missing");
    return std::any_of(page->controls->begin(), page->controls->end(),
                       [&](const InteractionControl& control) { return control.text == text; });
}
}

int main(int argc, char** argv) {
    Check(argc == 2, "quest_fixture_path_required");
    std::filesystem::current_path(argv[1]);
    const auto resourceError = ms::NxFiles::init();
    Check(!resourceError, "original_img_resources_did_not_initialize");
    Interaction model;
    const Interaction::Context context{"provider-contract", 1, 2};
    model.ResetContext(context);
    MapleControl::State state;
    state.ready = state.inGame = state.characterKnown = state.inventoryKnown = true;
    state.mapKnown = state.positionKnown = true;
    state.instanceId = "provider-contract";
    state.sceneGeneration = 2;
    state.mapId = 10;
    state.character.id = 1;
    state.character.values[0] = 6;
    state.character.values[1] = 0;
    state.character.values[6] = 80;
    state.character.values[7] = 100;
    state.character.values[8] = 10;
    state.character.values[9] = 30;
    state.character.known.fill(true);
    state.inventory = {{4, 1, 4000003, 2, true}};
    ms::QuestLog quests;
    quests.add_completed(1230, 1);
    std::vector<QuestRequest> requests;
    int dialogOpens = 0;
    const auto openServer = [&](std::uint32_t objectId, std::int32_t npcId, std::string&) {
        Check(model.CurrentPage() == nullptr, "local_provider_was_not_reset_before_server_navigation");
        Check(objectId == 42 && npcId == 777, "server_navigation_lost_native_subject");
        ++dialogOpens;
        model.BeginPage({"native_packet", "Server page", "native text", std::vector<InteractionControl>{}});
        return true;
    };
    QuestInteraction provider(
        model,
        [&](const QuestRequest& request, std::string&) {
            requests.push_back(request);
            return true;
        },
        openServer);
    std::string error;
    const auto activate = [&](const std::string& text) {
        error.clear();
        Check(model.Activate(Reference(model, text), context, error), error.c_str());
    };

    Check(provider.Open(42, 777, state, quests, error), error.c_str());
    Check(model.CurrentPage()->source == "client_local_quest" && requests.empty(), "quest_list_sent_a_request");
    Check(!HasControl(model, "Unknown conditions") && !HasControl(model, "Different job")
              && !HasControl(model, "Missing body") && HasControl(model, "交谈"),
          "unstarted_unknown_or_ineligible_templates_were_offered_as_current_tasks");
    const auto stable = Reference(model, "Resource quest");
    provider.Refresh(state, quests);
    Check(Reference(model, "Resource quest") == stable, "unchanged_facts_rebuilt_control_references");
    activate("Resource quest");
    Check(model.CurrentPage()->text->find("Start first") != std::string::npos && requests.empty(),
          "list_activation_did_not_open_the_resource_detail");
    activate("下一页");
    Check(model.CurrentPage()->text->find("Start second") != std::string::npos && requests.empty(),
          "next_page_sent_a_request_or_lost_resource_text");
    const auto accepted = Reference(model, "接受");
    activate("接受");
    Check(requests.size() == 1 && requests[0].phase == QuestPhase::Start && requests[0].questId == 4321
              && requests[0].npcObjectId == 42 && requests[0].npcId == 777,
          "explicit_confirmation_did_not_keep_internal_subject");
    Check(model.CurrentPage()->text->find("Accepted text") == std::string::npos,
          "request_submission_was_reported_as_started");
    provider.Refresh(state, quests);
    Check(requests.size() == 1 && !model.Activate(accepted, context, error), "pending_request_was_replayed");
    quests.add_started(4321, "000");
    provider.Refresh(state, quests);
    Check(model.CurrentPage()->text->find("Accepted text") != std::string::npos,
          "confirmed_started_record_did_not_show_post_accept_resource_text");
    activate("关闭");

    Check(provider.Open(42, 777, state, quests, error), error.c_str());
    activate("Resource quest");
    Check(model.CurrentPage()->text->find("Current task log") != std::string::npos
              && model.CurrentPage()->text->find("Completed log") == std::string::npos
              && Enabled(model, "交付") == MapleControl::Fact::False,
          "incomplete_task_was_given_a_success_body_or_enabled_confirmation");
    state.inventory[0].quantity = 3;
    quests.add_started(4321, "005");
    provider.Refresh(state, quests);
    Check(Enabled(model, "交付") == MapleControl::Fact::True, "known_item_and_single_mob_conditions_were_not_applied");
    activate("交付");
    Check(requests.size() == 2 && requests.back().phase == QuestPhase::Complete,
          "completion_confirmation_did_not_submit_once");
    provider.Refresh(state, quests);
    Check(model.CurrentPage()->text->find("Completed log") == std::string::npos,
          "unconfirmed_completion_was_shown_as_complete");
    quests.add_completed(4321, 2);
    provider.Refresh(state, quests);
    Check(model.CurrentPage()->text->find("Completed log") != std::string::npos && requests.size() == 2,
          "native_completion_did_not_select_completed_log");
    activate("关闭");

    Check(!provider.Open(42, 777, state, quests, error) && !error.empty() && !model.CurrentPage(),
          "unknown_unstarted_tasks_created_a_static_directory");
    quests.add_started(4322, "");
    Check(provider.Open(42, 777, state, quests, error), error.c_str());
    Check(Enabled(model, "Unknown conditions") == MapleControl::Fact::True,
          "unknown_completion_qualification_blocked_a_current_started_task");
    Check(!HasControl(model, "Resource quest") && !HasControl(model, "Different job"),
          "completed_history_or_ineligible_start_was_offered_again");
    activate("Unknown conditions");
    Check(model.CurrentPage()->text->find("Known readable started text") != std::string::npos
              && Enabled(model, "交付") == MapleControl::Fact::Unknown,
          "unsupported_condition_was_claimed_known");
    Check(!model.Activate(Reference(model, "交付"), context, error) && requests.size() == 2,
          "unknown_confirmation_reached_request_boundary");
    activate("返回列表");
    const auto talk = Reference(model, "交谈");
    activate("交谈");
    Check(dialogOpens == 1 && requests.size() == 2 && model.CurrentPage()->source == "native_packet",
          "mixed_npc_navigation_did_not_reach_the_server_opener_once");
    provider.Refresh(state, quests);
    Check(model.CurrentPage()->source == "native_packet" && !model.Activate(talk, context, error) && dialogOpens == 1,
          "server_navigation_reentered_the_local_quest_directory");
    model.ClosePage();

    quests.add_started(4325, "");
    Check(provider.Open(42, 777, state, quests, error), error.c_str());
    activate("Completion pages");
    Check(model.CurrentPage()->text->find("Fallback progress") != std::string::npos
              && model.CurrentPage()->text->find("Finish first") == std::string::npos
              && Enabled(model, "交付") == MapleControl::Fact::False,
          "unmet_conditions_showed_completion_say_instead_of_current_log");
    state.inventory[0].quantityKnown = false;
    provider.Refresh(state, quests);
    Check(model.CurrentPage()->text->find("Fallback progress") != std::string::npos
              && model.CurrentPage()->text->find("Finish first") == std::string::npos
              && Enabled(model, "交付") == MapleControl::Fact::Unknown,
          "unknown_conditions_showed_completion_say_instead_of_current_log");
    state.inventory[0].quantityKnown = true;
    state.inventory[0].quantity = 4;
    provider.Refresh(state, quests);
    Check(model.CurrentPage()->text->find("Finish first") != std::string::npos && requests.size() == 2,
          "completion_page_sequence_was_not_opened");
    Check(std::none_of(model.CurrentPage()->controls->begin(), model.CurrentPage()->controls->end(),
                       [](const InteractionControl& control) { return control.text == "交付"; }),
          "completion_confirmation_skipped_a_known_resource_page");
    activate("下一页");
    Check(model.CurrentPage()->text->find("Finish second") != std::string::npos
              && Enabled(model, "交付") == MapleControl::Fact::True && requests.size() == 2,
          "completion_sequence_did_not_wait_for_explicit_final_confirmation");
    Check(model.CurrentPage()->title.find("交付详情") != std::string::npos
              && model.CurrentPage()->text->find("待确认") != std::string::npos,
          "completion_explanation_was_presented_as_confirmed_success");
    state.inventory[0].quantityKnown = false;
    provider.Refresh(state, quests);
    Check(model.CurrentPage()->text->find("Fallback progress") != std::string::npos
              && model.CurrentPage()->text->find("Finish second") == std::string::npos,
          "changed_qualification_kept_an_obsolete_completion_explanation");
    activate("关闭");

    for (const auto id : {4321, 4322, 4323, 4324, 4325}) quests.add_completed(id, 3);
    model.BeginPage({"native_packet", "Server page", "native text", std::vector<InteractionControl>{}});
    Check(!provider.Open(42, 777, state, quests, error) && error.empty()
              && model.CurrentPage()->source == "native_packet",
          "completed_related_quests_permanently_intercepted_server_dialogue");
    nl::nx::Quest = {};
    QuestInteraction unavailable(model, [&](const QuestRequest&, std::string&) { return false; }, openServer);
    Check(!unavailable.Open(42, 777, state, quests, error) && !error.empty()
              && model.CurrentPage()->source == "native_packet",
          "missing_optional_quest_resource_blocked_another_provider");
}
