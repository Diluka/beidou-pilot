"""静态交通候选；依据 BeiDouMS/BeiDou-Server 00422c2 的 NPC 脚本及 Boats.js。"""
from collections import defaultdict
from heapq import heappop, heappush

from .world_map import edges_of, route


def transport_edges():
    towns = {
        100000000: (1012000, (149, 267)), 101000000: (1032000, (117, -37)),
        102000000: (1022001, (766, 1864)), 103000000: (1052016, (1796, 152)),
        104000000: (1002007, (2750, -232)), 120000000: (1092014, (1364, -419)),
    }
    result = defaultdict(list)
    for origin, (npc, point) in towns.items():
        for target in towns:
            if target == origin:
                continue
            condition = 'jobId==0 为一折；特殊券分支未建模，普通票价和菜单仅为候选'
            if npc == 1002007:
                condition += '；持4032313继续对话自动消券前往100000000，普通菜单不可用'
            if npc == 1032000:
                condition += '；持4032288前往100000000免费并消券'
            result[origin].append(dict(kind='taxi', to=target, cost=800 if target in (101000000, 120000000) else 1000,
                                       npc=npc, npc_at=point, conditions=condition))
    for origin, point, target, cost in [(211000000, (1479, 86), 211040200, 10000),
                                        (220000000, (-1920, 97), 220050300, 25000),
                                        (240000000, (1807, 14), 240030000, 65000)]:
        result[origin].append(dict(kind='taxi', to=target, cost=cost, npc=2023000, npc_at=point,
                                   conditions='普通票价；脚本条件及服务器行为待核实'))
    result[101000300].append(dict(kind='airship', to=200000100, cost=5000, npc=1032007, npc_at=(482, 39),
                                  check_npc=1032008, check_map=101000300, check_at=(1592, 83),
                                  conditions='需要4031045及航班可登船；包含等待和航行'))
    result[200000100].append(dict(kind='airship', to=101000300, cost=5000, npc=2012000, npc_at=(-142, 33),
                                  check_npc=2012001, check_map=200000111, check_at=(-482, -636),
                                  conditions='需要4031047及航班可登船；售票与检票地图不同，包含等待和航行'))
    return result


def paid_route(scenes, start, goal, objective):
    """在有向门户与交通候选组成的图上按费用或换场景数排序。"""
    transports = transport_edges()
    if start == goal:
        return None
    walking, _ = route(scenes, start, goal)
    # 已有免费路线时，收费方案必须减少规划段数，避免推荐花钱绕回原地。
    max_legs = len(walking) - 1 if walking else len(scenes)
    queue = [(0, 0, start, False, 0)]
    best = {(start, False, 0): (0, 0)}
    previous = {}
    while queue:
        primary, secondary, node, used, legs = heappop(queue)
        key = (node, used, legs if walking else 0)
        if best.get(key) != (primary, secondary):
            continue
        if node == goal and used:
            steps = []
            state = key
            while state != (start, False, 0):
                state, step = previous[state]
                steps.append(step)
            steps.reverse()
            return {'steps': steps, 'cost': sum(step.get('cost', 0) for step in steps), 'planning_legs': len(steps)}
        if legs >= max_legs:
            continue
        candidates = [dict(kind='portal', to=e.target, portal=e.name, portal_at=e.sources,
                           portal_at_destination=e.receivers, cost=0)
                      for e in edges_of(scenes[node], scenes) if not e.script and e.target in scenes]
        candidates += [edge for edge in transports[node] if edge['to'] in scenes]
        for edge in candidates:
            target = edge['to']
            is_paid = edge['kind'] != 'portal'
            increment = (edge['cost'], 1) if objective == 'cost' else (1, edge['cost'])
            score = (primary + increment[0], secondary + increment[1])
            state = (target, used or is_paid, legs + 1 if walking else 0)
            if state not in best or score < best[state]:
                best[state] = score
                previous[state] = (key, dict(edge, **{'from': node}))
                heappush(queue, (*score, target, used or is_paid, legs + 1))
    return None
