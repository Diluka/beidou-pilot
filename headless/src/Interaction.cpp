// SPDX-License-Identifier: AGPL-3.0-or-later
#include "Interaction.h"

bool Interaction::ResetContext(const Context& current) {
    if (context.instance == current.instance && context.character == current.character
        && context.scene == current.scene)
        return false;
    context = current;
    ClosePage();
    targets.clear();
    return true;
}

void Interaction::BeginPage(InteractionPage current) {
    controls.clear();
    if (current.controls) current.controls->clear();
    page = std::move(current);
}

void Interaction::AddControl(std::string role, std::string text, MapleControl::Fact enabled, Callback callback) {
    const auto reference = NextReference();
    page->controls->push_back({std::move(role), std::move(text), enabled, reference});
    controls.emplace(reference, Binding{context, enabled, std::move(callback)});
}

void Interaction::ClosePage() {
    controls.clear();
    page.reset();
}

const InteractionPage* Interaction::CurrentPage() const {
    return page ? &*page : nullptr;
}

std::string Interaction::RegisterTarget(Callback callback) {
    const auto reference = NextReference();
    targets.emplace(reference, Binding{context, MapleControl::Fact::True, std::move(callback)});
    return reference;
}

void Interaction::RemoveTarget(const std::string& reference) {
    targets.erase(reference);
}

bool Interaction::Activate(const std::string& reference, const Context& current, std::string& error) {
    const auto control = controls.find(reference);
    const auto target = targets.find(reference);
    const auto* binding = control != controls.end() ? &control->second
                          : target != targets.end() ? &target->second
                                                    : nullptr;
    if (binding == nullptr || binding->context.instance != current.instance
        || binding->context.character != current.character || binding->context.scene != current.scene) {
        error = "stale_interaction_reference";
        return false;
    }
    if (binding->enabled != MapleControl::Fact::True) {
        error = binding->enabled == MapleControl::Fact::Unknown ? "control_availability_unknown" : "control_disabled";
        return false;
    }
    // Activation may replace the page and erase its bindings.
    const auto callback = binding->callback;
    return callback(error);
}

std::string Interaction::NextReference() {
    return "@ui-" + context.instance + "-" + std::to_string(++nextReference);
}
