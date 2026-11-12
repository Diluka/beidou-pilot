"""首转节点的双端公共入口合同；不把参数装载当作真实停练验收。"""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.bridge import BridgeClient
from beidou_pilot.cli import main
from .test_bridge import BridgeFiles


class AdvancementEntryContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = {
            backend: BridgeFiles(Path(temporary.name) / backend, backend)
            for backend in ("beidou", "headless")
        }
        self.files["headless"].environment["HOSTNAME"] = "headless-container"
        self.files["headless"].register("headless")
        self.terrain = {"source": "local-client-map-data", "footholds": [
            {"id": 1, "x1": -200, "x2": 200, "y1": 20, "y2": 20, "prev": 0, "next": 0},
        ], "ropes": []}

    def combat(self, backend, command, job, level, options):
        files = self.files[backend]
        state = deepcopy(files.state)
        state["character"].update(job=job, level=level)
        state["capabilities"] = {"attack_move": True}
        state["monsters"] = []
        output = io.StringIO()
        target = "beidou_pilot." + ("control_scripts" if command == "fight" else "hunting") + ".run_strategy"
        with (
            patch.dict(os.environ, files.environment),
            patch.object(BridgeClient, "snapshot", return_value=state),
            patch("beidou_pilot.hunting.load_hunt_terrain", return_value=self.terrain),
            patch(target, return_value={"status": "completed", "last_state": state}) as run,
            redirect_stdout(output),
        ):
            code = main(["--root", str(files.root), "--backend", backend, "--json", command,
                         "100100", "--bounds", "-200", "200", *options])
        return code, json.loads(output.getvalue()), run

    def test_both_commands_load_only_the_selected_node_or_explicit_target(self) -> None:
        cases = [
            (0, 7, [], 8, "first_job_checkpoint"),
            (0, 7, ["--first-job", "magician"], 8, "advancement"),
            (0, 7, ["--first-job", "magician", "--until-level", "10"], 8, "advancement"),
            (0, 6, ["--first-job", "magician", "--until-level", "7"], 7, "until_level"),
            (0, 8, ["--first-job", "warrior"], 10, "advancement"),
            (0, 8, ["--first-job", "bowman"], 10, "advancement"),
            (0, 8, ["--first-job", "thief"], 10, "advancement"),
            (0, 8, ["--first-job", "pirate"], 10, "advancement"),
            (0, 7, ["--until-level", "7"], 7, "until_level"),
            (0, 7, ["--until-level", "10"], 10, "until_level"),
            (0, 8, ["--until-level", "10"], 10, "until_level"),
            (100, 29, [], 30, "advancement"),
            (200, 29, ["--first-job", "magician"], 30, "advancement"),
            (110, 69, ["--until-level", "120"], 70, "advancement"),
            (111, 119, [], 120, "advancement"),
        ]
        for backend in self.files:
            for command in ("fight", "hunt"):
                for job, level, options, expected_level, source in cases:
                    with self.subTest(backend=backend, command=command, job=job, level=level, options=options):
                        code, report, run = self.combat(backend, command, job, level, options)
                        self.assertEqual(0, code, report)
                        self.assertEqual(1, run.call_count)
                        self.assertEqual("combat/" + command, run.call_args.args[1])
                        self.assertEqual(expected_level, run.call_args.args[2]["stop_level"])
                        data = report["data"]
                        self.assertEqual(expected_level, data["requested_level"])
                        self.assertEqual(source, data["stop_level_source"])
                        milestone = data["advancement"]
                        if source == "first_job_checkpoint" or job == 0 and "--first-job" not in options:
                            self.assertIsNone(milestone["level"])
                            self.assertIsNone(milestone["due"])
                            self.assertIsNone(milestone["first_job"])
                        elif job == 0:
                            self.assertEqual(options[1], milestone["first_job"])

    def test_due_or_unselected_nodes_refuse_before_loading_lua(self) -> None:
        cases = [
            (0, 8, [], "advancement_route_required"),
            (0, 10, [], "advancement_route_required"),
            (0, 8, ["--first-job", "magician"], "advancement_due"),
            (0, 9, ["--first-job", "magician", "--until-level", "10"], "advancement_due"),
            (0, 10, ["--first-job", "warrior"], "advancement_due"),
            (100, 30, [], "advancement_due"),
            (110, 70, [], "advancement_due"),
            (111, 120, [], "advancement_due"),
            (0, 7, ["--first-job", "mage"], "usage"),
        ]
        for backend in self.files:
            for command in ("fight", "hunt"):
                for job, level, options, error in cases:
                    with self.subTest(backend=backend, command=command, job=job, level=level, options=options):
                        code, report, run = self.combat(backend, command, job, level, options)
                        self.assertEqual((2, error), (code, report["error"]["code"]))
                        run.assert_not_called()

    def test_unmapped_jobs_keep_each_commands_existing_default(self) -> None:
        for backend in self.files:
            for command, expected_level, source in (("fight", 121, "next_level"), ("hunt", None, "none")):
                with self.subTest(backend=backend, command=command):
                    code, report, run = self.combat(backend, command, 112, 120, [])
                    self.assertEqual(0, code, report)
                    self.assertIsNone(report["data"]["advancement"])
                    self.assertEqual(expected_level, run.call_args.args[2]["stop_level"])
                    self.assertEqual(source, report["data"]["stop_level_source"])

    def test_status_does_not_infer_or_remember_a_first_job_route(self) -> None:
        for backend, files in self.files.items():
            for job, level, expected_level in ((0, 7, None), (0, 8, None), (0, 10, None), (100, 29, 30)):
                with self.subTest(backend=backend, job=job, level=level):
                    # A previous explicit command must not become persistent role strategy.
                    self.combat(backend, "hunt", 0, 7, ["--first-job", "magician"])
                    state = deepcopy(files.state)
                    state["character"].update(job=job, level=level)
                    output = io.StringIO()
                    with (
                        patch.dict(os.environ, files.environment),
                        patch.object(BridgeClient, "snapshot", return_value=state),
                        patch.object(Backend, "read", side_effect=lambda domain: (
                            {"stage": "IN_GAME", "running": True} if domain == "stage" else state
                        )),
                        redirect_stdout(output),
                    ):
                        self.assertEqual(0, main(["--root", str(files.root), "--backend", backend, "--json", "status"]))
                    milestone = json.loads(output.getvalue())["data"]["advancement"]
                    self.assertEqual(expected_level, milestone["level"])
                    if job == 0:
                        self.assertIsNone(milestone["due"])
                        self.assertEqual({"magician": 8, "warrior": 10, "bowman": 10, "thief": 10, "pirate": 10},
                                         {c["first_job"]: c["level"] for c in milestone["candidates"]})


if __name__ == "__main__":
    unittest.main()
