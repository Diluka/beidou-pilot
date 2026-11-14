"""运行实际公共路线函数，验证跨层/转场、复用与失败边界；不模拟游戏效果。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from beidou_pilot.script_libraries import with_library


class RouteLuaContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.root = Path(__file__).resolve().parents[2]
        cls.executable = cls.directory / "route-lua"
        sources = sorted(
            path for path in (cls.root / "third_party/lua").glob("*.c") if path.name not in {"ltests.c", "onelua.c"}
        )
        subprocess.run(
            ["gcc", "-DLUA_USE_LINUX", "-O0", *map(str, sources), "-lm", "-ldl", "-o", str(cls.executable)], check=True
        )

    def scenario(self, name: str) -> None:
        seconds = 1 if name == "budget" else 30
        source = with_library(
            "island-supply",
            None,
            f"local outward = island_supply.to_town({{seconds={seconds}}})\n"
            "assert(outward.arrived and outward.map_id == 1000000)\n"
            "local back = island_supply.to_field({seconds=20})\n"
            "assert(back.arrived and back.map_id == 50000)\n",
        )
        if name == "missing-terrain":
            source = with_library(
                "travel",
                None,
                'local r = travel.begin({name="unknown",seconds=10,start_map=50000,'
                "start={min_x=1100,max_x=1350,min_y=-95,max_y=-75},destination_map=1000000,"
                "destination={min_x=-90,max_x=-40,min_y=264,max_y=284}})\n"
                "r:drop_to(nil,{min_x=1390,max_x=1500,min_y=270,max_y=280})\n",
            )
        path = self.directory / (name + ".lua")
        path.write_text(source)
        subprocess.run(
            [str(self.executable), str(self.root / "cli/test/route_contract.lua"), name, str(path)],
            check=True,
            timeout=5,
        )

    def test_known_route_crosses_layers_transitions_and_is_reused_on_return(self) -> None:
        for name in ("normal", "landing"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_drop_preserves_airborne_drift_until_landing_before_portal_alignment(self) -> None:
        self.scenario("inertia")

    def test_wrong_start_stall_and_budget_do_not_dispatch_later_segments(self) -> None:
        for name in ("wrong-start", "stalled", "budget", "missing-terrain"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_identity_scene_transition_and_observation_unavailable_stop_without_arrival(self) -> None:
        for name in ("identity", "scene", "unexpected-portal", "observation-unavailable", "destination"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_control_preemption_during_actions_or_destination_sampling_stops(self) -> None:
        for name in ("preempted", "final-preempted"):
            with self.subTest(name=name):
                self.scenario(name)
