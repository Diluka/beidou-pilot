// SPDX-License-Identifier: AGPL-3.0-or-later
// The network and unused GUI initialization boundaries are replaced for offline tests.
#include "LoginState.h"
#include "LoginBridge.h"
#include <nlohmann/json.hpp>
#include <fstream>
#include "HeadlessState.h"
#include "Configuration.h"
#include "Net/Handlers/LoginHandlers.h"
#include "Net/OutPacket.h"
#include "Net/Session.h"
#include "IO/UI.h"
#include <cassert>

namespace ms {
Cryptography::Cryptography() = default;
Cryptography::~Cryptography() = default;
PacketSwitch::PacketSwitch() = default;
SocketAsio::SocketAsio() = default;
SocketAsio::~SocketAsio() = default;
Session::Session() = default;
Session::~Session() = default;
Keyboard::Keyboard() = default;
UI::UI() = default;
std::vector<std::vector<int8_t>> sent;
OutPacket::OutPacket(int16_t op) : opcode(op) { write_short(op); }
void OutPacket::dispatch() { sent.push_back(bytes); }
void OutPacket::write_byte(int8_t v) { bytes.push_back(v); }
void OutPacket::write_short(int16_t v) { write_byte(v); write_byte(v >> 8); }
void OutPacket::write_int(int32_t v) { for (int i=0;i<4;++i) write_byte(v >> (8*i)); }
void OutPacket::write_hardware_info() {}
void OutPacket::skip(size_t n) { bytes.insert(bytes.end(), n, 0); }
void OutPacket::write_point(Point<int16_t> p) { write_short(p.x()); write_short(p.y()); }
void OutPacket::write_time() { write_int(0); }
void OutPacket::write_string(const std::string& s) { write_short(s.size()); for (char c : s) write_byte(c); }
}

using namespace ms;
static void login(std::vector<int8_t> bytes) {
    InPacket packet(bytes.data(), bytes.size());
    LoginResultHandler handler;
    static_cast<const PacketHandler&>(handler).handle(packet);
}
static void characters(std::vector<int8_t> bytes) {
    InPacket packet(bytes.data(), bytes.size());
    CharlistHandler handler;
    static_cast<const PacketHandler&>(handler).handle(packet);
}
static std::vector<int8_t> account(int8_t gender) {
    // LOGIN_RESULT success followed by v83 account record, PIN/PIC disabled.
    std::vector<int8_t> p(4 + 2 + 4, 0);
    p.push_back(gender); p.insert(p.end(), 3, 0);
    p.insert(p.end(), 2, 0); // empty account name
    p.insert(p.end(), 2 + 8 + 8 + 4, 0);
    p.push_back(1); p.push_back(2);
    return p;
}
static std::vector<int8_t> list() {
    std::vector<int8_t> p{0, 1, 42, 0, 0, 0}; // channel, count, CID
    p.push_back('A'); p.insert(p.end(), 12, 0); // name
    p.insert(p.end(), 1+1+4+4+24+1+22+4+2+4+4+1+4, 0); // stats
    p.insert(p.end(), 1+1+4+1+4, 0); // look
    p.push_back(-1); p.push_back(-1); // empty equipment lists
    p.insert(p.end(), 4+12+2, 0); // weapon, pets, ranking flags
    p.push_back(2); p.insert(p.end(), 4, 0); // PIC, slots
    return p;
}
int main() {
    configure_login(0, 0, 0);
    login_state().creation_status = "completed"; login_state().created_cid = 42;
    stop_pending_creation("disconnected");
    assert(login_state().creation_status == "completed" && login_state().created_cid == 42);
    login_state().creation_status = "accepted"; stop_pending_creation("client_stopped");
    assert(login_state().creation_status == "unknown" && login_state().creation_error == "client_stopped");
    configure_login(0, 0, 0); sent.clear(); login({23,0,0,0});
    assert(sent.empty() && login_state().phase=="failed");
    configure_login(0, 0, 0); sent.clear(); login_state().accept_tos = true;
    login({23,0,0,0}); assert(sent.size()==1 && sent[0]==std::vector<int8_t>({7,0,1}));
    login({23,0,0,0}); assert(sent.size()==1 && login_state().phase=="failed");
    configure_login(0,0,0); sent.clear(); login(account(10));
    assert(sent.empty() && login_state().phase=="failed");
    // Existing CID does not authorize a choice for an unset account gender.
    configure_login(42,0,0); sent.clear(); login(account(10));
    assert(sent.empty() && login_state().phase=="failed" && login_state().error=="Account gender is required");
    {
        LoginBridge failedBridge("failed-bridge", "instance", "run");
        failedBridge.Tick();
        nlohmann::json failed;
        std::ifstream in("failed-bridge/login-state.json"); in >> failed;
        assert(failed["phase"]=="failed" && failed["error"]=="Account gender is required");
    }
    configure_login(42,0,0); sent.clear(); login_state().account_female=false;
    login(account(10)); assert(sent.size()==1 && sent[0]==std::vector<int8_t>({8,0,1,0}));
    login(account(0)); characters(list());
    assert(login_state().phase=="selecting_character" && sent.back()==std::vector<int8_t>({19,0,42,0,0,0}));
    configure_login(0,0,0); sent.clear(); login_state().account_female = true;
    login(account(10)); assert(sent.size()==1 && sent[0]==std::vector<int8_t>({8,0,1,1}));
    login(account(10)); assert(sent.size()==1 && login_state().phase=="failed");
    configure_login(0,0,0); sent.clear(); login_state().account_female = false;
    login(account(10)); assert(sent.size()==1 && sent[0]==std::vector<int8_t>({8,0,1,0}));
    login(account(0)); assert(sent.size()==2 && sent[1]==std::vector<int8_t>({11,0}));
    configure_login(0,0,0); sent.clear(); characters(list());
    assert(sent.empty() && login_state().phase=="character_list" && login_state().characters_known);
    assert(login_state().characters.size()==1 && login_state().characters[0].id==42 && login_state().characters[0].stats.name=="A");
    configure_login(42,0,0); sent.clear(); characters(list());
    assert(login_state().phase=="selecting_character" && headless_state().selected_character && headless_state().selected_character->id==42);
    assert(sent.size()==1 && sent[0]==std::vector<int8_t>({19,0,42,0,0,0}));
    configure_login(43,0,0); sent.clear(); characters(list());
    assert(sent.empty() && login_state().phase=="failed");
    configure_login(0,0,0); sent.clear();
    login_state().creation = CharacterCreation{"A",0,1,2,3,4,5,6,7,8,false};
    login_state().pending_request_id = "request"; login_state().phase = "checking_character_name";
    std::vector<int8_t> nameTaken{1,0,'A',1}; InPacket namePacket(nameTaken.data(),nameTaken.size());
    CharnameResponseHandler nameHandler; static_cast<const PacketHandler&>(nameHandler).handle(namePacket);
    assert(login_state().creation_status=="rejected" && login_state().creation_error=="name_taken" && sent.empty());
    login_state().phase = "checking_character_name"; login_state().creation_status = "accepted";
    std::vector<int8_t> mismatch{1,0,'B',0}; InPacket mismatchPacket(mismatch.data(),mismatch.size());
    static_cast<const PacketHandler&>(nameHandler).handle(mismatchPacket);
    assert(login_state().creation_status=="unknown" && login_state().creation_error=="name_response_mismatch");
    login_state().phase = "checking_character_name"; login_state().creation_status = "accepted";
    std::vector<int8_t> available{1,0,'A',0}; InPacket availablePacket(available.data(),available.size());
    static_cast<const PacketHandler&>(nameHandler).handle(availablePacket);
    assert(login_state().phase=="creating_character" && sent.size()==1);
    assert(sent[0]==std::vector<int8_t>({22,0,1,0,'A',0,0,0,0,1,0,0,0,2,0,0,0,3,0,0,0,
                                        4,0,0,0,5,0,0,0,6,0,0,0,7,0,0,0,8,0,0,0,0}));
    auto entry = list(); entry.erase(entry.begin(), entry.begin()+2); entry.resize(entry.size()-5); entry.insert(entry.begin(),0);
    InPacket created(entry.data(),entry.size()); AddNewCharEntryHandler addHandler;
    static_cast<const PacketHandler&>(addHandler).handle(created);
    assert(login_state().creation_status=="completed" && login_state().created_cid==42 && login_state().phase=="character_list");
    assert(sent.size()==1);
    configure_login(0,0,0); sent.clear(); characters(list());
    LoginBridge bridge("bridge", "instance", "run"); bridge.Tick();
    using Json = nlohmann::json;
    Json command = {{"protocol",1},{"instance_id","instance"},{"run_id","run"},
        {"request_id","0123456789abcdef0123456789abcdef"},{"operation","create_character"},
        {"params",{{"name","ABCDEFGHIJKLM"},{"job",0},{"face",1},{"hair",2},{"hair_color",3},{"skin",3},{"top",4},{"bottom",5},{"shoes",6},{"weapon",7},{"female",false}}}};
    { std::ofstream out("bridge/login-command.json"); out << command; }
    bridge.Tick();
    Json snapshot, result;
    { std::ifstream in("bridge/login-state.json"); in >> snapshot; }
    { std::ifstream in("bridge/login-results/0123456789abcdef0123456789abcdef.json"); in >> result; }
    assert(snapshot["pending_request_id"]==command["request_id"] && result["status"]=="accepted");
    assert(!std::filesystem::exists("bridge/login-command.json") && sent.size()==1 && sent[0][0]==21);
    { std::ofstream out("bridge/login-command.json"); out << command; }
    bridge.Tick(); assert(sent.size()==1); // same request cannot be replayed
    login_state().creation_status="rejected"; login_state().creation_error="name_taken"; login_state().phase="character_list";
    bridge.Tick();
    { std::ifstream in("bridge/login-results/0123456789abcdef0123456789abcdef.json"); in >> result; }
    assert(result["status"]=="rejected" && result["error"]=="name_taken");
    auto missingColor = command;
    missingColor["request_id"]="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    missingColor["params"].erase("hair_color");
    { std::ofstream out("bridge/login-command.json"); out << missingColor; }
    bridge.Tick();
    { std::ifstream in("bridge/login-results/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json"); in >> result; }
    assert(result["status"]=="rejected" && result["error"]=="invalid_request" && sent.size()==1);
    command["request_id"]="11111111111111111111111111111111";
    command["params"]["name"]="😀";
    { std::ofstream out("bridge/login-command.json"); out << command; }
    bridge.Tick();
    { std::ifstream in("bridge/login-results/11111111111111111111111111111111.json"); in >> result; }
    assert(result["status"]=="rejected" && result["error"]=="invalid_name_encoding" && sent.size()==1);
    command["request_id"]="22222222222222222222222222222222";
    command["params"]["name"]=std::string(14,'a');
    { std::ofstream out("bridge/login-command.json"); out << command; }
    bridge.Tick();
    { std::ifstream in("bridge/login-results/22222222222222222222222222222222.json"); in >> result; }
    assert(result["status"]=="rejected" && result["error"]=="name_too_long" && sent.size()==1);
    command["request_id"]="33333333333333333333333333333333";
    command["params"]["name"]="测试测试测试测"; // seven GBK characters = 14 bytes
    { std::ofstream out("bridge/login-command.json"); out << command; }
    bridge.Tick();
    { std::ifstream in("bridge/login-results/33333333333333333333333333333333.json"); in >> result; }
    assert(result["status"]=="rejected" && result["error"]=="name_too_long" && sent.size()==1);
    command["run_id"]="old-run";
    { std::ofstream out("bridge/login-command.json"); out << command; }
    bridge.Tick();
    assert(std::filesystem::exists("bridge/login-orphan-33333333333333333333333333333333.json") && !std::filesystem::exists("bridge/login-command.json") && sent.size()==1);
    command["request_id"]="44444444444444444444444444444444";
    { std::ofstream out("bridge/login-command.json"); out << command; }
    bridge.Tick();
    assert(std::filesystem::exists("bridge/login-orphan-44444444444444444444444444444444.json") && !std::filesystem::exists("bridge/login-command.json"));
    { std::ofstream out("bridge/login-command.json"); out << command; }
    bridge.Tick();
    assert(login_state().error=="login_orphan_slot_full_manual_recovery_required" && login_state().phase=="failed" && std::filesystem::exists("bridge/login-command.json"));
    configure_login(0,0,0);
    LoginBridge invalidBridge("invalid-bridge", "instance", "run");
    command["request_id"]="invalid";
    { std::ofstream out("invalid-bridge/login-command.json"); out << command; }
    invalidBridge.Tick();
    assert(std::filesystem::exists("invalid-bridge/login-orphan-command.json"));
    { std::ofstream out("invalid-bridge/login-command.json"); out << command; }
    invalidBridge.Tick();
    assert(login_state().error=="login_orphan_slot_full_manual_recovery_required" && std::filesystem::exists("invalid-bridge/login-command.json"));
}
