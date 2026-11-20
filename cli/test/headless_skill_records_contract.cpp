#include "SkillUpRecords.h"
#include <cassert>

int main() {
    using namespace headless;
    assert(SkillRequestIdentity("run", "run", 7, true, 7));
    assert(!SkillRequestIdentity("old", "run", 7, true, 7));
    assert(!SkillRequestIdentity("run", "run", 8, true, 7));
    assert(!SkillRequestIdentity("run", "run", 7, false, 7));
    SkillRecords records = SkillRecords::array({{{"status", "pending"}, {"level_before", 3}, {"sp_before", 5}}});
    assert(SkillRequestPending(records));
    ObserveSkillRequest(records[0], true, 4, 5);
    assert(SkillRequestPending(records));
    ObserveSkillRequest(records[0], true, 4, 4);
    assert(records[0]["status"] == "confirmed");
    assert(!SkillRequestPending(records));
    records[0]["status"] = "pending";
    ObserveSkillRequest(records[0], false, 4, 4);
    ObserveSkillRequest(records[0], true, 4, 4);
    assert(records[0]["status"] == "unresolved");
    records[0]["status"] = "pending";
    InvalidatePendingSkillRequests(records);
    assert(records[0]["status"] == "unresolved");
    assert(SkillRequestPending(records));
    SkillRecords restarted = SkillRecords::array();
    assert(restarted.empty());
}
