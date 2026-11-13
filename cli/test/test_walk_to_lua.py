"""运行真实 walk_to Lua，验证地形图、执行与失败语义；不模拟真实游戏效果。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from beidou_pilot.strategies import StrategyMetadata, _lua_literal, compile_strategy, read_strategy_file


def _foothold(foothold_id: int, x1: int, x2: int, y1: int, y2: int | None = None) -> dict:
    return {"id": foothold_id, "x1": x1, "x2": x2, "y1": y1, "y2": y1 if y2 is None else y2, "prev": 0, "next": 0}


def _scene(footholds: list[dict], ropes: list[dict] | None = None) -> dict:
    return {
        "instance_id": "walk-to-contract",
        "character_id": 1,
        "map_id": 1,
        "scene_generation": 1,
        "terrain": {"status": "available", "source": "contract", "footholds": footholds, "ropes": ropes or []},
    }


def _options(metadata: StrategyMetadata, **values: object) -> dict:
    result: dict = {option.name: option.default for option in metadata.options if option.has_default}
    result.update(values)
    return result


class WalkToLuaContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(__file__).resolve().parents[2]
        lua = cls.root / "third_party/lua"
        cls.executable = Path(temporary.name) / "walk-to-lua"
        sources = sorted(path for path in lua.glob("*.c") if path.name not in {"ltests.c", "onelua.c"})
        subprocess.run(
            ["gcc", "-DLUA_USE_LINUX", "-O0", *map(str, sources), "-lm", "-ldl", "-o", str(cls.executable)],
            check=True,
        )
        cls.contract = cls.root / "cli/test/walk_to_contract.lua"
        cls.strategy = cls.root / "shared/scripts/travel/walk_to.lua"

    def run_scenario(
        self,
        scenario: str,
        scene: dict,
        options: dict,
        *,
        initial: dict,
        character: dict | None = None,
    ) -> None:
        source, metadata = read_strategy_file(self.strategy)
        self.assertIsNotNone(metadata)
        assert metadata is not None
        compiled = compile_strategy(source, _options(metadata, **options), scene)
        case = {
            "scene": scene,
            "character": character or {"id": 1, "hp": 100, "max_hp": 100},
            "initial": initial,
            "inventory": [],
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
                timeout=30,
            )

    def test_vertical_wall_splits_platform_and_stops_without_moving(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 200), _foothold(2, 200, 200, 130, 200)])
        self.run_scenario(
            "wall", scene, {"target_x": 380, "target_y": 200, "budget_seconds": 20}, initial={"x": 20, "y": 200}
        )

    def test_target_on_same_side_of_wall_is_reached(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 200), _foothold(2, 200, 200, 130, 200)])
        self.run_scenario(
            "wall-same-side",
            scene,
            {"target_x": 150, "target_y": 200, "budget_seconds": 20},
            initial={"x": 20, "y": 200},
        )

    def test_same_platform_walk_reaches_target(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 200)])
        self.run_scenario(
            "walk", scene, {"target_x": 300, "target_y": 200, "budget_seconds": 20}, initial={"x": 20, "y": 200}
        )

    def test_jump_up_reaches_overlapping_platform(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 300), _foothold(2, 100, 300, 240)])
        self.run_scenario(
            "jumpup", scene, {"target_x": 200, "target_y": 240, "budget_seconds": 20}, initial={"x": 50, "y": 300}
        )

    def test_unexecutable_edge_is_disabled_and_repanned(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 300), _foothold(2, 100, 300, 240)])
        self.run_scenario(
            "jump-fail", scene, {"target_x": 200, "target_y": 240, "budget_seconds": 20}, initial={"x": 50, "y": 300}
        )

    def test_walk_off_edge_drops_to_lower_platform(self) -> None:
        scene = _scene([_foothold(1, 0, 200, 200), _foothold(2, 0, 400, 300)])
        self.run_scenario(
            "drop", scene, {"target_x": 300, "target_y": 300, "budget_seconds": 20}, initial={"x": 20, "y": 200}
        )

    def test_rope_connects_floors_with_jump_grab(self) -> None:
        scene = _scene(
            [_foothold(1, 0, 200, 300), _foothold(2, 0, 200, 100)],
            [{"index": 1, "x": 100, "y1": 100, "y2": 250}],
        )
        self.run_scenario(
            "rope", scene, {"target_x": 100, "target_y": 100, "budget_seconds": 20}, initial={"x": 20, "y": 300}
        )

    def test_airborne_start_waits_for_landing_before_planning(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 200)])
        self.run_scenario(
            "airborne-start",
            scene,
            {"target_x": 100, "target_y": 200, "budget_seconds": 20},
            initial={"x": 20, "y": 120},
        )

    def test_low_hp_stops_before_input(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 200)])
        self.run_scenario(
            "hp-low",
            scene,
            {"target_x": 100, "target_y": 200, "budget_seconds": 20, "min_hp_ratio": 0.5},
            initial={"x": 20, "y": 200},
            character={"id": 1, "hp": 30, "max_hp": 100},
        )

    def test_off_platform_target_reports_explicit_reason(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 200)])
        self.run_scenario(
            "target-off", scene, {"target_x": 9999, "target_y": 9999, "budget_seconds": 20}, initial={"x": 20, "y": 200}
        )

    def test_plan_only_logs_path_without_input(self) -> None:
        scene = _scene([_foothold(1, 0, 200, 200), _foothold(2, 0, 400, 300)])
        self.run_scenario(
            "plan-only",
            scene,
            {"target_x": 300, "target_y": 300, "budget_seconds": 20, "plan_only": True},
            initial={"x": 20, "y": 200},
        )

    def test_map_change_stops_before_confirming_arrival(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 200)])
        self.run_scenario(
            "map-change", scene, {"target_x": 300, "target_y": 200, "budget_seconds": 20}, initial={"x": 20, "y": 200}
        )

    def test_identity_change_stops(self) -> None:
        scene = _scene([_foothold(1, 0, 400, 200)])
        self.run_scenario(
            "identity-change",
            scene,
            {"target_x": 300, "target_y": 200, "budget_seconds": 20},
            initial={"x": 20, "y": 200},
        )


if __name__ == "__main__":
    unittest.main()
