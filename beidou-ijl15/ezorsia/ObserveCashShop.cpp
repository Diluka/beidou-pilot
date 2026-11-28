// SPDX-License-Identifier: AGPL-3.0-or-later
// Read-only V17 cash shop observations; unverified actions remain unavailable.
#include "stdafx.h"
#include "NativeObservation.h"
#include <array>
#include <sstream>
#include <vector>

namespace NativeObservation {
namespace {
using Address = std::uint32_t;
std::string Hex(Address value) { std::ostringstream out; out << "0x" << std::hex << value; return out.str(); }

Value ReadCommodity(Address object) {
    if (!object) throw ReadError("cashshop: null commodity");
    const auto header = Bytes(object, 0x24);
    const auto guards = Bytes(object + 0x10, 12);
    const auto encodedPtr = Read<Address>(object + 0x18);
    const auto encoded = Bytes(encodedPtr, 10);
    const auto id = SecureValue(object + 0x10);
    const auto sn = Read<Address>(object + 0x0c);
    const auto price = Read<std::int32_t>(object + 0x20);
    if (Bytes(object, 0x24) != header || Bytes(object + 0x10, 12) != guards ||
        Read<Address>(object + 0x18) != encodedPtr || Bytes(encodedPtr, 10) != encoded)
        throw ReadError("cashshop: commodity changed");
    return Value::Object({{"address", Hex(object)}, {"sn_candidate", sn}, {"item_id_candidate", id},
        {"secure_value_checksum_valid", true}, {"price_candidate", price}});
}
}

Value CashShop() {
    const auto before = Read<std::array<Address, 3>>(0x00BF1650);
    if (before[0] > 256) throw ReadError("cashshop: window count out of range");
    auto node = before[1];
    std::vector<Address> grids, dialogs;
    for (Address i = 0; i < before[0]; ++i) {
        if (!node) throw ReadError("cashshop: truncated window list");
        const auto window = Read<Address>(node);
        const auto tables = Read<std::array<Address, 3>>(window);
        if (tables == std::array<Address, 3>{0x00AF1C24, 0x00AF1BD8, 0x00AF1BD4}) grids.push_back(window);
        if (tables == std::array<Address, 3>{0x00AF1D68, 0x00AF1D1C, 0x00AF1D18}) dialogs.push_back(window);
        const auto next = Read<Address>(node - 12);
        node = next ? next + 16 : 0;
    }
    if (node || Read<std::array<Address, 3>>(0x00BF1650) != before)
        throw ReadError("cashshop: window list changed");
    auto result = Value::Object({{"source", "client-native-cashshop"}, {"readonly", true},
        {"grid_count", static_cast<int>(grids.size())}, {"modal_count", static_cast<int>(dialogs.size())},
        {"grid", Value()}, {"modal", Value()}});
    if (grids.size() > 1 || dialogs.size() > 1) throw ReadError("cashshop: ambiguous candidate windows");
    if (grids.size() == 1) {
        const auto grid = grids[0];
        const auto parent = Read<Address>(grid + 0x240);
        if (!parent || parent + 0x15bc != grid) throw ReadError("cashshop: parent/grid relation mismatch");
        const auto parentBefore = Bytes(parent + 0x18, 0x28);
        const auto category = Read<std::array<Address, 3>>(parent + 0x52c);
        const auto indices = Read<std::array<std::int32_t, 10>>(grid + 0x178);
        const auto context = Read<Address>(0x00BE7918);
        if (!context) throw ReadError("cashshop: missing context");
        const auto array = Read<Address>(context + 0x36e0);
        const auto length = array ? Read<Address>(array - 4) : 0;
        if (length > 100000) throw ReadError("cashshop: commodity count out of range");
        auto items = Value::Array();
        for (int i = 0; i < 10; ++i) {
            if (indices[i] < 0) { items.Add(Value()); continue; }
            if (static_cast<Address>(indices[i]) >= length) throw ReadError("cashshop: commodity index out of range");
            const auto at = array + static_cast<Address>(indices[i]) * 8 + 4;
            const auto object = Read<Address>(at);
            auto item = ReadCommodity(object);
            if (Read<Address>(at) != object) throw ReadError("cashshop: commodity reference changed");
            item["slot"] = i;
            item["control_id_candidate"] = 2000 + i * 3;
            item["index"] = indices[i];
            items.Add(item);
        }
        const auto credit = SecureInt(parent + 0x1c);
        const auto points = SecureInt(parent + 0x28);
        const auto prepaid = SecureInt(parent + 0x34);
        if (Bytes(parent + 0x18, 0x28) != parentBefore || Read<std::array<Address, 3>>(parent + 0x52c) != category ||
            Read<std::array<std::int32_t, 10>>(grid + 0x178) != indices || Read<Address>(grid + 0x240) != parent ||
            Read<Address>(0x00BE7918) != context || Read<Address>(context + 0x36e0) != array ||
            (array && Read<Address>(array - 4) != length)) throw ReadError("cashshop: snapshot changed");
        result["grid"] = Value::Object({{"address", Hex(grid)}, {"parent", Hex(parent)}, {"window", Window(grid)},
            {"nx_credit", credit}, {"maple_point", points}, {"nx_prepaid", prepaid},
            {"balance_checksums_valid", true}, {"category_candidate", category[0]},
            {"subcategory_candidate", category[1]}, {"page_zero_candidate", category[2]}, {"items", items}});
    }
    if (dialogs.size() == 1) {
        const auto dialog = dialogs[0];
        const auto count = Read<Address>(dialog + 0x88);
        const auto array = Read<Address>(dialog + 0x90);
        if (count > 32 || (count && !array) || (array && Read<Address>(array - 4) != count))
            throw ReadError("cashshop: modal array mismatch");
        auto items = Value::Array();
        for (Address i = 0; i < count; ++i) {
            const auto at = array + i * 8 + 4;
            const auto object = Read<Address>(at);
            items.Add(ReadCommodity(object));
            if (Read<Address>(at) != object) throw ReadError("cashshop: modal reference changed");
        }
        if (Read<Address>(dialog + 0x88) != count || Read<Address>(dialog + 0x90) != array)
            throw ReadError("cashshop: modal changed");
        result["modal"] = Value::Object({{"address", Hex(dialog)}, {"active_cwnd", true}, {"window", Window(dialog)},
            {"count", count}, {"items", items}});
    }
    if (Read<std::array<Address, 3>>(0x00BF1650) != before) throw ReadError("cashshop: windows changed");
    return result;
}
}
