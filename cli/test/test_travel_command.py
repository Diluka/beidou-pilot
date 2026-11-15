"""travel CLI 合同：目录包、跨图路线注入、结果投影与双端可用性。

对端全部是替身，只证明 CLI 参数、注入形状和投影，不证明真实寻路或游戏效果。
"""

from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError
from .test_bridge import BridgeFiles


TICK_SOURCE = (
    "-- @tick.gear 3\n"
    "-- @option[type=int,opt,default=3] arrive_tolerance 到达水平容差\n"
    "local function main(context)\n"
    "end\n"
)

ROUTE = {
    "source": "native_world_map",
    "status": "ok",
    "error": None,
    "start": 100000000,
    "goal": 100000100,
    "legs": [{"from": 100000000, "portal": "east00", "to": 100000100, "portal_at": [[1400, 300]]}],
    "model": {"logic_version": 2, "source_fingerprint": "0123456789abcdef", "maps": 120, "edges": 180},
    "cache": "hit",
}


def travel_snapshot() -> dict:
    return {
        "ready": True,
        "instance_id": "client-1",
        "scene_generation": 3,
        "map_id": 100000000,
        "character": {"id": 4, "x": 10.5, "y": 20.0, "hp": 100, "max_hp": 100},
    }


def travel_observed() -> dict:
    return {
        "ready": True,
        "instance_id": "client-1",
        "scene_generation": 4,
        "map_id": 100000100,
        "character": {"id": 4, "x": 1400.0, "y": 300.0, "hp": 90, "max_hp": 100},
    }


class TravelCommandContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = BridgeFiles(self.root)
        self.native = BridgeFiles(self.root / "headless", "headless")
        self.native.environment["HOSTNAME"] = "headless-container"
        self.native.register("headless")
        self.native.publish()
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.package = self.root / "travel-policy"
        self.package.mkdir()
        self.entry = self.package / "main.lua"
        self.entry.write_text(TICK_SOURCE, encoding="utf-8")

    def cli(self, backend: str, *arguments: str) -> tuple[int, dict]:
        files = self.files if backend == "beidou" else self.native
        output = io.StringIO()
        with patch.dict(os.environ, files.environment), redirect_stdout(output):
            code = main(["--json", "--root", str(files.root), "--backend", backend, *arguments])
        return code, json.loads(output.getvalue())

    @contextmanager
    def travel_mocks(
        self,
        *,
        route: dict | None = None,
        route_error: ClientError | None = None,
        snapshots: list[dict] | None = None,
        report: dict | None = None,
    ):
        route = ROUTE if route is None else route
        snapshots = [travel_snapshot(), travel_observed()] if snapshots is None else snapshots
        report = {"id": "a" * 32, "status": "completed", "reason": "script_returned"} if report is None else report
        with (
            patch("beidou_pilot.bridge.BridgeClient") as bridge,
            patch("beidou_pilot.observations.NativeObserver") as observer,
            patch("beidou_pilot.cli.compile_strategy", return_value="compiled-travel") as compile_strategy,
            patch(
                "beidou_pilot.strategy_scene.scene_context", return_value={"instance_id": "client-1"}
            ) as scene_context,
        ):
            client = bridge.return_value
            client.snapshot.side_effect = list(snapshots)
            client.run_script.return_value = report
            if route_error is not None:
                observer.return_value.route.side_effect = route_error
            else:
                observer.return_value.route.return_value = route
            yield bridge, observer, compile_strategy, scene_context, client

    def travel_arguments(self, package: Path | None = None, *extra: str) -> list[str]:
        return [
            "travel",
            str(self.package if package is None else package),
            "--target-map",
            "100000100",
            "--target-x",
            "1400",
            "--target-y",
            "300",
            *extra,
        ]

    def test_travel_requires_directory_package_with_entry(self) -> None:
        single = self.root / "policy.lua"
        single.write_text(TICK_SOURCE, encoding="utf-8")
        code, report = self.cli(
            "beidou", "travel", str(single), "--target-map", "100000100", "--target-x", "1400", "--target-y", "300"
        )
        self.assertEqual(2, code, report)
        self.assertEqual("usage", report["error"]["code"])

        empty = self.root / "empty-policy"
        empty.mkdir()
        code, report = self.cli(
            "beidou", "travel", str(empty), "--target-map", "100000100", "--target-x", "1400", "--target-y", "300"
        )
        self.assertEqual(2, code, report)
        self.assertEqual("script_package_entry_missing", report["error"]["code"])
        self.assertEqual(str(empty), report["error"]["details"]["path"])

    def test_travel_requires_positive_target_arguments(self) -> None:
        base = ["travel", str(self.package)]
        cases = (
            (),
            ("--target-map", "100000100"),
            ("--target-map", "100000100", "--target-x", "1400"),
            ("--target-map", "100000100", "--target-y", "300"),
            ("--target-map", "0", "--target-x", "1400", "--target-y", "300"),
            ("--target-map", "-100", "--target-x", "1400", "--target-y", "300"),
            ("--target-map", "abc", "--target-x", "1400", "--target-y", "300"),
            ("--target-map", "1e3", "--target-x", "1400", "--target-y", "300"),
            ("--target-map", "100000100", "--target-x", "1.5", "--target-y", "300"),
            ("--target-map", "100000100", "--target-x", "1400", "--target-y", "abc"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                code, report = self.cli("beidou", *base, *arguments)
                self.assertEqual(2, code, report)
                self.assertEqual("usage", report["error"]["code"])

    def test_travel_injects_route_and_goal_and_projects_arrival(self) -> None:
        with self.travel_mocks() as (_, observer, compile_strategy, scene_context, client):
            code, report = self.cli("beidou", *self.travel_arguments())
        self.assertEqual(0, code, report)
        self.assertEqual("beidou", report["backend"])
        data = report["data"]
        self.assertEqual("completed", data["status"])
        self.assertEqual("a" * 32, data["id"])
        self.assertEqual(100000000, data["start"])
        self.assertEqual({"map_id": 100000100, "x": 1400, "y": 300}, data["goal"])
        self.assertEqual(
            {
                "status": ROUTE["status"],
                "legs": ROUTE["legs"],
                "model": ROUTE["model"],
                "cache": ROUTE["cache"],
            },
            data["route"],
        )
        self.assertEqual(
            {
                "map_id": 100000100,
                "x": 1400.0,
                "y": 300.0,
                "hp": 90,
                "script_status": "completed",
            },
            data["arrival"],
        )

        observer.assert_called_once_with(self.files.root.resolve(), "beidou", "default")
        observer.return_value.route.assert_called_once_with(100000000, 100000100)

        source, options, scene, extra = compile_strategy.call_args.args
        self.assertEqual(TICK_SOURCE, source)
        self.assertEqual({"arrive_tolerance": 3}, options)
        self.assertEqual({"instance_id": "client-1"}, scene)
        self.assertEqual(
            {"route": ROUTE, "goal": {"map_id": 100000100, "x": 1400, "y": 300}},
            extra,
        )
        scene_context.assert_called_once()

        self.assertIsNone(client.run_script.call_args.args[0])
        self.assertEqual(180, client.run_script.call_args.kwargs["seconds"])
        self.assertEqual("compiled-travel", client.run_script.call_args.kwargs["code"])
        self.assertEqual(str(self.package.resolve()), client.run_script.call_args.kwargs["package_root"])
        self.assertIsNone(client.run_script.call_args.kwargs["admission_control"])
        self.assertEqual(2, client.snapshot.call_count)

    def test_travel_forwards_explicit_session_seconds(self) -> None:
        with self.travel_mocks() as (_, _, _, _, client):
            code, report = self.cli("beidou", *self.travel_arguments(None, "--seconds", "42"))
        self.assertEqual(0, code, report)
        self.assertEqual(42, client.run_script.call_args.kwargs["seconds"])

    def test_travel_rejects_route_that_is_not_ok(self) -> None:
        route = {"source": "native_world_map", "status": "no_route", "error": "no_route", "legs": []}
        with self.travel_mocks(route=route) as (_, observer, compile_strategy, _, client):
            code, report = self.cli("beidou", *self.travel_arguments())
        self.assertEqual(2, code, report)
        self.assertEqual("travel_route_unavailable", report["error"]["code"])
        self.assertEqual({"start": 100000000, "goal": 100000100, "route": route}, report["error"]["details"])
        observer.return_value.route.assert_called_once_with(100000000, 100000100)
        compile_strategy.assert_not_called()
        client.run_script.assert_not_called()

    def test_travel_wraps_native_route_query_failure(self) -> None:
        failure = ClientError("native_world_map_unavailable", "世界门户图不可用。")
        with self.travel_mocks(route_error=failure) as (_, observer, compile_strategy, _, client):
            code, report = self.cli("beidou", *self.travel_arguments())
        self.assertEqual(2, code, report)
        self.assertEqual("travel_route_unavailable", report["error"]["code"])
        self.assertEqual(
            {"start": 100000000, "goal": 100000100, "cause": "native_world_map_unavailable"},
            report["error"]["details"],
        )
        observer.return_value.route.assert_called_once_with(100000000, 100000100)
        compile_strategy.assert_not_called()
        client.run_script.assert_not_called()

    def test_travel_requires_ready_client_before_route_query(self) -> None:
        for key, value in (("ready", False), ("map_id", None), ("character", None)):
            with self.subTest(key=key):
                snapshot = travel_snapshot()
                snapshot[key] = value
                with self.travel_mocks(snapshots=[snapshot]) as (_, observer, compile_strategy, _, client):
                    code, report = self.cli("beidou", *self.travel_arguments())
                self.assertEqual(2, code, report)
                self.assertEqual("travel_observation_unavailable", report["error"]["code"])
                observer.assert_not_called()
                compile_strategy.assert_not_called()
                client.run_script.assert_not_called()

    def test_travel_rejects_unknown_policy_options(self) -> None:
        code, report = self.cli("beidou", *self.travel_arguments(None, "--library", "travel"))
        self.assertEqual(2, code, report)
        self.assertEqual("invalid_strategy_option", report["error"]["code"])

    def test_travel_runs_on_headless_native_channel(self) -> None:
        with self.travel_mocks() as (_, observer, compile_strategy, _, client):
            code, report = self.cli("headless", *self.travel_arguments())
        self.assertEqual(0, code, report)
        self.assertEqual("headless", report["backend"])
        self.assertEqual("completed", report["data"]["status"])
        self.assertEqual("completed", report["data"]["arrival"]["script_status"])
        observer.assert_called_once_with(self.native.root.resolve(), "headless", "default")
        observer.return_value.route.assert_called_once_with(100000000, 100000100)
        compile_strategy.assert_called_once()
        client.run_script.assert_called_once()

    def test_travel_uses_resolved_package_root_and_detects_missing_directory(self) -> None:
        with self.travel_mocks() as (_, _, _, _, client):
            code, report = self.cli("beidou", *self.travel_arguments())
        self.assertEqual(0, code, report)
        self.assertEqual(str(self.package.resolve()), client.run_script.call_args.kwargs["package_root"])
        self.assertTrue(Path(client.run_script.call_args.kwargs["package_root"]).is_absolute())


if __name__ == "__main__":
    unittest.main()
