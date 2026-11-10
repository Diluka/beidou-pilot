"""狩猎入口的目标、攻击方式和持续装载合同；不把装载成功当作游戏收益。"""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.bridge import BridgeClient
from beidou_pilot.cli import main
from beidou_pilot.control_scripts import run_source
from .test_bridge import BridgeFiles


class HuntingEntryContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = BridgeFiles(self.root)
        (self.root / "clientctl.py").touch()
        self.files.state["monsters"] = [
            {"object_id": 50, "template_id": 100100, "name": "蜗牛", "x": 100, "y": 20, "active": True}
        ]
        self.files.state["capabilities"] = {"skill": True}
        self.terrain = {
            "map_id": 100,
            "source": "local-client-map-data",
            "ropes": [],
            "footholds": [{"id": 1, "x1": -100, "x2": 300, "y1": 20, "y2": 20, "prev": 0, "next": 0}],
        }

    def test_cli_selects_all_continuously_or_one_named_target_in_one_scene(self) -> None:
        for arguments, expected_mob, duration, level_changed in (
            (["--backend", "headless", "hunt", "--continuous"], None, None, False),
            (["hunt", "蜗牛", "--seconds", "12", "--until-level", "99"], 100100, 12, True),
        ):
            with self.subTest(arguments=arguments):
                final = deepcopy(self.files.state)
                final["character"]["experience"] = 130
                if level_changed:
                    final["character"]["level"] += 1
                report = {"status": "completed", "last_state": final}
                output = io.StringIO()
                with (
                    patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                    patch("beidou_pilot.hunting.load_hunt_terrain", return_value=self.terrain),
                    patch("beidou_pilot.hunting.run_strategy", return_value=report) as run,
                    redirect_stdout(output),
                ):
                    self.assertEqual(0, main(["--root", str(self.root), "--json", *arguments]))
                self.assertEqual(1, run.call_count)
                _, strategy, options, actual_duration = run.call_args.args
                self.assertEqual(("combat/hunt", duration), (strategy, actual_duration))
                self.assertEqual(expected_mob, options["mob_id"])
                self.assertIsNone(options["skill_id"])
                self.assertEqual(30, options["stop_level"])
                self.assertEqual(
                    ("client-1", 4, 100, 1),
                    tuple(options[k] for k in ("instance_id", "character_id", "map_id", "scene_generation")),
                )
                result = json.loads(output.getvalue())["data"]
                self.assertEqual("same_scene", result["scope"])
                self.assertEqual({"mob_id": expected_mob, "all_monsters": expected_mob is None}, result["target"])
                self.assertEqual(None if level_changed else 7, result["experience_delta"])
                self.assertEqual("inspect_final_state", result["effect"])

    def test_supported_skill_requires_current_verified_learned_skill_without_fallback(self) -> None:
        character = {
            "instance_id": "client-1",
            "scene_generation": 1,
            "character_id": 4,
            "native_values_valid": True,
            "skills_complete": True,
            "skills": {"1001004": {"level": 2, "master_level": None}},
        }
        for backend, override, code in (
            ("beidou", {}, None),
            ("headless", {}, None),
            ("beidou", {"skills": {}}, "skill_not_learned"),
            ("beidou", {"skills_complete": False}, "observation_unavailable"),
            ("beidou", {"scene_generation": 2}, "hunt_context_changed"),
        ):
            with self.subTest(backend=backend, override=override):
                output = io.StringIO()
                with (
                    patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                    patch("beidou_pilot.hunting.NativeObserver") as native,
                    patch("beidou_pilot.hunting.load_hunt_terrain", return_value=self.terrain),
                    patch(
                        "beidou_pilot.hunting.run_strategy",
                        return_value={"status": "completed", "last_state": self.files.state},
                    ) as run,
                    redirect_stdout(output),
                ):
                    native.return_value.observe.return_value = character | override
                    self.assertEqual(
                        0 if code is None else 2,
                        main(
                            [
                                "--root",
                                str(self.root),
                                "--backend",
                                backend,
                                "--json",
                                "hunt",
                                "100100",
                                "--skill",
                                "1001004",
                            ]
                        ),
                    )
                if code is None:
                    self.assertEqual(1001004, run.call_args.args[2]["skill_id"])
                    self.assertEqual("skill", json.loads(output.getvalue())["data"]["attack"]["mode"])
                else:
                    self.assertEqual(code, json.loads(output.getvalue())["error"]["code"])
                    run.assert_not_called()

    def test_unsupported_skill_and_due_advancement_never_start_hunting(self) -> None:
        for arguments, code in (
            (["--backend", "headless", "hunt", "--skill", "1001004"], "unsupported_capability"),
            (["hunt"], "advancement_due"),
        ):
            with self.subTest(arguments=arguments):
                self.files.state["capabilities"] = {"skill": False}
                self.files.state["character"]["level"] = 30
                output = io.StringIO()
                with (
                    patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                    patch("beidou_pilot.hunting.run_strategy") as run,
                    redirect_stdout(output),
                ):
                    self.assertEqual(2, main(["--root", str(self.root), "--json", *arguments]))
                self.assertEqual(code, json.loads(output.getvalue())["error"]["code"])
                run.assert_not_called()

    def test_skill_cli_preserves_native_admission_without_interpreting_numeric_result(self) -> None:
        for backend, native_result, dispatched, reason in (
            ("headless", 0, True, "native_skill_dispatched"),
            ("headless", 1, False, "skill_not_learned"),
            ("beidou", 0, True, "native_skill_requested"),
        ):
            with self.subTest(backend=backend, dispatched=dispatched):
                final = {
                    **self.files.state,
                    "last_skill": {
                        "skill_id": 1001004,
                        "native_result": native_result,
                        "dispatched": dispatched,
                        "reason": reason,
                    },
                }
                output = io.StringIO()
                with (
                    patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                    patch(
                        "beidou_pilot.control_scripts.run_source",
                        return_value={"status": "completed", "reason": "script_returned", "last_state": final},
                    ) as run,
                    redirect_stdout(output),
                ):
                    self.assertEqual(
                        0, main(["--root", str(self.root), "--backend", backend, "--json", "skill", "1001004"])
                    )
                result = json.loads(output.getvalue())["data"]
                self.assertEqual(
                    (native_result, dispatched, reason, "unknown"),
                    tuple(result[k] for k in ("native_result", "dispatched", "skill_reason", "effect")),
                )
                self.assertEqual("script_returned", result["reason"])
                self.assertEqual(("game.skill(1001004)\n", 3), run.call_args.args[1:])

    def test_hp_item_must_have_known_positive_hp_recovery_before_hunting(self) -> None:
        for item_id, specification, error in (
            (2000000, {"hp": 50}, None),
            (2000003, {"mp": 100}, "invalid_hp_item"),
            (2010000, {}, "healing_metadata_missing"),
        ):
            with self.subTest(item_id=item_id, error=error):
                output = io.StringIO()
                with (
                    patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                    patch("beidou_pilot.hunting.Catalog") as catalog,
                    patch("beidou_pilot.hunting.load_hunt_terrain", return_value=self.terrain),
                    patch(
                        "beidou_pilot.hunting.run_strategy",
                        return_value={"status": "completed", "last_state": self.files.state},
                    ) as run,
                    redirect_stdout(output),
                ):
                    catalog.return_value.item.return_value = {"spec": specification}
                    self.assertEqual(
                        0 if error is None else 2,
                        main(
                            [
                                "--root",
                                str(self.root),
                                "--backend",
                                "headless",
                                "--json",
                                "hunt",
                                "--hp-item",
                                str(item_id),
                            ]
                        ),
                    )
                catalog.return_value.item.assert_called_once_with(item_id)
                if error is None:
                    self.assertEqual(item_id, run.call_args.args[2]["hp_item_id"])
                else:
                    self.assertEqual(error, json.loads(output.getvalue())["error"]["code"])
                    run.assert_not_called()

    def test_continuous_strategy_source_uses_existing_bridge_lifetime(self) -> None:
        backend = Backend(self.root, "headless", "alpha")
        source = "while true do game.sleep(0.1) end\n"

        def submitted(path: Path, *, seconds: float | None) -> dict[str, str]:
            self.assertEqual(source, path.read_text())
            self.assertIsNone(seconds)
            return {"status": "cancelled"}

        with patch.object(BridgeClient, "run_script", side_effect=submitted) as bridge:
            self.assertEqual({"status": "cancelled"}, run_source(backend, source, None))
        self.assertEqual(1, bridge.call_count)
