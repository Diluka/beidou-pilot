#!/usr/bin/env python3
"""通过客户端原生观察API读取背包，按请求投影所需栏位。"""

import argparse
import json
from typing import TypedDict, cast

from ..observations import observe_domain


class InventoryItem(TypedDict):
    inventory_type: int
    slot: int
    item_id: int
    quantity: int | None


class InventorySnapshot(TypedDict):
    observed_at: str
    source: str
    readonly: bool
    items: list[InventoryItem]
    equipped: list[InventoryItem]
    capacities: dict[str, int]
    checksums_valid: bool | None
    native_values_valid: bool
    unavailable: list[str]
    not_covered: list[str]
    read_seconds: float


def read_inventory(types: list[int], equipped: bool = False) -> InventorySnapshot:
    """原生域一次采集全部栏位；消费层只过滤已有结构化事实。"""
    report = cast(InventorySnapshot, observe_domain("inventory"))
    selected = set(types)
    report["items"] = [item for item in report["items"] if item["inventory_type"] in selected]
    report["capacities"] = {kind: value for kind, value in report["capacities"].items()
                            if int(kind) in selected}
    if not equipped:
        report["equipped"] = []
        if "equipped_items" not in report["not_covered"]:
            report["not_covered"].append("equipped_items")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--type', type=int, choices=range(1, 6), action='append',
                        help='1装备、2消费、3设置、4其他、5特殊，可重复；默认2和4')
    parser.add_argument('--item-id', type=int, help='只返回此物品，并汇总数量')
    parser.add_argument('--equipped', action='store_true', help='同时读取已装备负槽位，武器-11、帽子-1、上衣-5')
    args = parser.parse_args()
    report = read_inventory(args.type or [2, 4], args.equipped)
    if args.item_id is not None:
        report['items'] = [item for item in report['items'] + report['equipped']
                           if item['item_id'] == args.item_id]
        quantities = [item['quantity'] for item in report['items']]
        total = None if report['unavailable'] or None in quantities else sum(quantities)
        print(json.dumps({'observed_at': report['observed_at'], 'item_id': args.item_id,
                          'total_quantity': total,
                          'matches': report['items'], 'checksums_valid': report['checksums_valid'],
                          'native_values_valid': report['native_values_valid'],
                          'unavailable': report['unavailable'], 'source': report['source'],
                          'readonly': True}, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
