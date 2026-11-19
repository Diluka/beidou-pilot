// SPDX-License-Identifier: AGPL-3.0-or-later
#include "../ezorsia/NativeAutoApTransaction.h"
#include <cassert>

int main() {
    using Tx = BeiDouBridge::NativeAutoApTransaction;
    assert(!Tx::ReportedDispatched(false, false));
    assert(!Tx::ReportedDispatched(true, false));
    assert(!Tx::ReportedDispatched(false, true));
    assert(Tx::ReportedDispatched(true, true));
    assert(Tx::MayRequestInstall(0));
    assert(Tx::MayRequestInstall(1));
    assert(Tx::MayRequestInstall(2));
    assert(Tx::MayRequestInstall(-2));
    assert(!Tx::MayRequestInstall(-1));
    assert(std::string(Tx::InstallFailureReason(-2)) == "auto_ap_install_unknown");
    assert(std::string(Tx::InstallFailureReason(2)) == "auto_ap_install_unknown");
    assert(std::string(Tx::InstallFailureReason(-1)) == "auto_ap_unsupported");
    const Tx::Identity owner{5, 7, 9, "original"};
    Tx tx;
    assert(!tx.Start({0, 7, 9, "original"}));
    assert(tx.Start(owner));
    assert(!tx.Start(owner));
    assert(tx.BindAndChoose(owner, false, true, true) == Tx::Decision::None);
    assert(tx.BindAndChoose(owner, true, false, true) == Tx::Decision::None);
    assert(tx.BindAndChoose(owner, true, true, true) == Tx::Decision::Confirm);
    assert(tx.BindAndChoose(owner, true, true, true) == Tx::Decision::None);
    tx.Returned(false);
    assert(tx.State() == Tx::Phase::Unknown);
    Tx changed;
    assert(changed.Start(owner));
    assert(changed.BindAndChoose({6, 7, 9, "original"}, true, true, true) == Tx::Decision::None);
    assert(changed.State() == Tx::Phase::Unknown);
    Tx noModal;
    assert(noModal.Start(owner));
    noModal.Returned(true);
    assert(noModal.State() == Tx::Phase::Unknown);
    Tx changedContext;
    assert(changedContext.Start(owner));
    assert(changedContext.BindAndChoose({5, 7, 10, "original"}, true, true, true) == Tx::Decision::None);
    assert(changedContext.State() == Tx::Phase::Unknown);
    Tx changedInstance;
    assert(changedInstance.Start(owner));
    assert(changedInstance.BindAndChoose({5, 7, 9, "other"}, true, true, true) == Tx::Decision::None);
    assert(changedInstance.State() == Tx::Phase::Unknown);
    Tx changedScene;
    assert(changedScene.Start(owner));
    assert(changedScene.BindAndChoose({5, 8, 9, "original"}, true, true, true) == Tx::Decision::None);
    assert(changedScene.State() == Tx::Phase::Unknown);
    Tx completed;
    assert(completed.Start(owner));
    assert(completed.BindAndChoose(owner, true, true, true) == Tx::Decision::Confirm);
    completed.Returned(true);
    assert(completed.State() == Tx::Phase::Finished);
}
