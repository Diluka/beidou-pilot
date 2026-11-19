// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once

#include <cstdint>
#include <string>

namespace BeiDouBridge {

// Pure admission/one-shot state only. It neither performs input nor establishes
// that a native window belongs to the request; the native boundary must do so.
struct NativeAutoApTransaction {
    struct Identity {
        std::uint32_t character = 0;
        std::uint64_t scene = 0;
        std::uint32_t context = 0;
        std::string instance;
    };
    enum class Phase { Idle, AwaitingModal, AwaitingReturn, Finished, Unknown };
    enum class Decision { None, Confirm };

    bool Start(const Identity& identity) {
        if (phase != Phase::Idle || identity.character == 0 || identity.context == 0 || identity.instance.empty())
            return false;
        owner = identity;
        phase = Phase::AwaitingModal;
        return true;
    }

    Decision BindAndChoose(const Identity& current, bool boundToCall, bool focused, bool layoutVerified) {
        if (phase != Phase::AwaitingModal || !boundToCall || !focused || !layoutVerified) return Decision::None;
        if (current.character != owner.character || current.scene != owner.scene || current.context != owner.context
            || current.instance != owner.instance) {
            phase = Phase::Unknown;
            return Decision::None;
        }
        phase = Phase::AwaitingReturn;
        return Decision::Confirm;
    }

    void Returned(bool confirmed) {
        if (phase == Phase::AwaitingModal || phase == Phase::AwaitingReturn)
            phase = confirmed && phase == Phase::AwaitingReturn ? Phase::Finished : Phase::Unknown;
    }

    static bool ReportedDispatched(bool consumed, bool confirmed) { return consumed && confirmed; }

    // Install states: 0 untried, 1 ready, 2 in progress, -1 unsupported, -2 unknown.
    static bool MayRequestInstall(long state) { return state != -1; }

    static const char* InstallFailureReason(long state) {
        return state == -1 ? "auto_ap_unsupported" : "auto_ap_install_unknown";
    }

    Phase State() const { return phase; }

private:
    Identity owner;
    Phase phase = Phase::Idle;
};

} // namespace BeiDouBridge
