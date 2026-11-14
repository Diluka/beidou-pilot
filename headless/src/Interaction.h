// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include "Contract.h"

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

struct InteractionControl {
    std::string role;
    std::string text;
    MapleControl::Fact enabled = MapleControl::Fact::Unknown;
    std::string ref;
};

struct InteractionPage {
    std::string source;
    std::string title;
    std::optional<std::string> text;
    std::optional<std::vector<InteractionControl>> controls;
};

// The client UI owns references and callbacks. Neither is decoded by a consumer.
class Interaction {
public:
    struct Context {
        std::string instance;
        std::uint32_t character = 0;
        std::uint64_t scene = 0;
    };

    using Callback = std::function<bool(std::string&)>;

    bool ResetContext(const Context& current);
    void BeginPage(InteractionPage page);
    void AddControl(std::string role, std::string text, MapleControl::Fact enabled, Callback callback);
    void ClosePage();
    const InteractionPage* CurrentPage() const;
    std::string RegisterTarget(Callback callback);
    void RemoveTarget(const std::string& reference);
    bool Activate(const std::string& reference, const Context& current, std::string& error);

private:
    struct Binding {
        Context context;
        MapleControl::Fact enabled;
        Callback callback;
    };

    std::string NextReference();
    Context context;
    std::uint64_t nextReference = 0;
    std::optional<InteractionPage> page;
    std::map<std::string, Binding> controls;
    std::map<std::string, Binding> targets;
};
