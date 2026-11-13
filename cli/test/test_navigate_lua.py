"""运行真实 navigate Lua，验证多段换图、落点核对与失败语义；不模拟真实游戏效果。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from beidou_pilot.strategies import StrategyMetadata, _lua_literal, compile_strategy, read_strategy_file


def _terrain(y: int = 200, left: int = 0, right: int = 400) -> dict:
    return {"footholds": [[1, left, right, y, y, 0, 0]], "ropes": []}


def _route(legs: int = 2) -> dict:
    maps = [100, 200, 300]
    rows = []
    for index in range(legs):
        rows.append(
            {
                "map_id": maps[index],
                "map_name": f"图{maps[index]}",
                "portal": "east00",
                "portal_x": 380,
                "portal_y": 200,
                "target_map": maps[index + 1],
                "target_name": f"图{maps[index + 1]}",
                "terrain": _terrain(),
            }
        )
    return {
        "start": maps[0],
        "goal": maps[legs],
        "goal_name": f"图{maps[legs]}",
        "legs": rows,
        "final": {"map_id": maps[legs], "terrain": _terrain()},
    }


def _scene() -> dict:
    return {
        "instance_id": "navigate-contract",
        "character_id": 1,
        "map_id": 100,
        "scene_generation": 1,
        "terrain": {
            "status": "available",
            "source": "contract",
            "footholds": [{"id": 1, "x1": 0, "x2": 400, "y1": 200, "y2": 200, "prev": 0, "next": 0}],
            "ropes": [],
        },
    }


def _options(metadata: StrategyMetadata, **values: object) -> dict:
    result: dict = {option.name: option.default for option in metadata.options if option.has_default}
    result.update(values)
    return result


class NavigateLuaContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(__file__).resolve().parents[2]
        lua = cls.root / "third_party/lua"
        cls.executable = Path(temporary.name) / "navigate-lua"
        sources = sorted(path for path in lua.glob("*.c") if path.name not in {"ltests.c", "onelua.c"})
        subprocess.run(
            ["gcc", "-DLUA_USE_LINUX", "-O0", *map(str, sources), "-lm", "-ldl", "-o", str(cls.executable)],
            check=True,
        )
        cls.contract = cls.root / "cli/test/navigate_contract.lua"
        cls.strategy = cls.root / "shared/scripts/travel/navigate.lua"

    def run_scenario(
        self,
        scenario: str,
        route: dict,
        *,
        values: dict | None = None,
        hp: int = 100,
        max_hp: int = 100,
    ) -> None:
        source, metadata = read_strategy_file(self.strategy)
        self.assertIsNotNone(metadata)
        assert metadata is not None
        option_values: dict = {"budget_seconds": 60}
        option_values.update(values or {})
        options = _options(metadata, **option_values)
        compiled = compile_strategy(source, options, _scene(), {"route": route})
        arrivals = {str(leg["map_id"]): {"map_id": leg["target_map"], "x": 20, "y": 200} for leg in route["legs"]}
        case = {
            "scene": _scene(),
            "route": route,
            "start": {"x": 20, "y": 200},
            "hp": hp,
            "max_hp": max_hp,
            "arrivals": arrivals,
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            strategy_path = directory / "strategy.lua"
            strategy_path.write_text(compiled, encoding="utf-8")
            case_path = directory / "case.lua"
            case_path.write_text("return " + _lua_literal(case), encoding="utf-8")
            subprocess.run(
                [str(self.executable), str(self.contract), scenario, str(strategy_path), str(case_path)],
                check=True,
                timeout=40,
            )

    def test_two_legs_transition_and_arrive(self) -> None:
        self.run_scenario("two-legs", _route(2))

    def test_single_leg_transition_and_arrive(self) -> None:
        self.run_scenario("one-leg", _route(1))

    def test_map_mismatch_after_transition_stops(self) -> None:
        self.run_scenario("map-mismatch", _route(2))

    def test_portal_without_transition_stops(self) -> None:
        self.run_scenario("portal-unconfirmed", _route(1))

    def test_low_hp_stops_before_transition(self) -> None:
        self.run_scenario("hp-low", _route(1), values={"min_hp_ratio": 0.5}, hp=30)

    def test_exhausted_budget_stops(self) -> None:
        self.run_scenario("budget", _route(1), values={"budget_seconds": 1})


if __name__ == "__main__":
    unittest.main()
