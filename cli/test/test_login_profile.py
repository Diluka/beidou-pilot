"""离线验证统一账号配置与 GUI 选角；不替代真实客户端入图。"""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

from beidou_pilot.backend import Backend
from beidou_pilot.cli import main


class LoginProfileContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "clientctl.py").touch()
        self.target = self.root / "target.json"
        self.target.write_text('{"project":"isolated","service":"app","network":"isolated","expected_image":"fixture"}')
        self.profile = self.root / "profile.json"
        self.profile.write_text(
            '{"username":"fixture-user","password":"fixture-password","character_id":7,"channel":1}'
        )
        self.profile.chmod(0o600)

    def test_open_requires_the_shared_profile_instead_of_legacy_gui_options(self) -> None:
        for backend in ("beidou", "headless"):
            for options in (
                [],
                ["--profile", str(self.profile), "--character", "First", "--character-index", "0", "--channel", "1"],
            ):
                with self.subTest(backend=backend, options=options), patch("beidou_pilot.cli.dispatch") as dispatch:
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(self.root), "--json", "--backend", backend, "open", *options])
                    self.assertEqual(2, code)
                    self.assertEqual("usage", json.loads(output.getvalue())["error"]["code"])
                    dispatch.assert_not_called()

    def test_rejects_a_cid_that_would_be_truncated_by_the_native_client(self) -> None:
        self.profile.write_text('{"username":"fixture","password":"fixture","character_id":4294967298}')
        output = io.StringIO()
        with patch("beidou_pilot.headless.open_game") as open_client, redirect_stdout(output):
            code = main(
                ["--root", str(self.root), "--json", "--backend", "headless", "open", "--profile", str(self.profile)]
            )
        self.assertEqual(2, code)
        self.assertEqual("profile_invalid", json.loads(output.getvalue())["error"]["code"])
        open_client.assert_not_called()

    def test_gui_selects_the_profile_cid_and_requires_the_same_actor_in_game(self) -> None:
        first = {"id": 6, "name": "First", "index": 0}
        desired = {"id": 7, "name": "Desired", "index": 1}
        running = {
            "running": True,
            "renderer": "intel",
            "client": {"container_id": "fixture", "run_id": "fixture"},
            "game_geometry": {"x": 0, "y": 0, "width": 1280, "height": 720},
        }
        roster = {"characters_available": True, "characters": [first, desired]}
        for observed, expected_code in ((desired, 0), (first, 2)):
            with self.subTest(observed=observed["id"]):
                stages = iter(
                    (
                        {"stage": "STOPPED", "running": False},
                        {**running, "stage": "LOGIN"},
                        {
                            **running,
                            "stage": "CHANNEL_SELECT",
                            "channel_panel": {
                                "channels": [
                                    {"channel": 1, "root_rect": {"left": 0, "right": 20, "top": 0, "bottom": 20}},
                                    {"channel": 2, "root_rect": {"left": 20, "right": 40, "top": 0, "bottom": 20}},
                                ]
                            },
                        },
                        {**running, "stage": "CHARACTER_SELECT", "login": {**roster, "selected_index": 0}},
                        {**running, "stage": "CHARACTER_SELECT", "login": {**roster, "selected_index": 1}},
                        {**running, "stage": "IN_GAME", "world_id": 0, "channel": 2},
                    )
                )

                def engine(name: str, arguments: list[str], *, payload: str | None = None) -> str:
                    if name == "stage":
                        return json.dumps(next(stages))
                    if name == "observe":
                        return json.dumps(
                            {
                                "native_values_valid": True,
                                "world_id": 0,
                                "position": {"x": 0, "y": 0},
                                "character": {**observed, "hp": 20},
                            }
                        )
                    if name == "clientctl" and arguments == ["check"]:
                        return '{"image_available":true}'
                    if name in {"clientctl", "runtime-ui"}:
                        return ""
                    self.fail(f"未预期的引擎调用：{name}")

                output = io.StringIO()
                with (
                    patch.object(Backend, "_run", side_effect=engine) as invoke,
                    patch.object(Backend, "desktop") as desktop,
                    patch("beidou_pilot.headless.any_running", return_value=False),
                    patch("beidou_pilot.session.adopt_session", return_value={"target_file": str(self.target)}),
                    patch("beidou_pilot.session.time.sleep"),
                    redirect_stdout(output),
                ):
                    code = main(
                        [
                            "--root",
                            str(self.root),
                            "--json",
                            "open",
                            "--target",
                            str(self.target),
                            "--profile",
                            str(self.profile),
                        ]
                    )
                self.assertEqual(expected_code, code, output.getvalue())
                result = json.loads(output.getvalue())
                if code == 0:
                    self.assertEqual(7, result["data"]["character"]["id"])
                    self.assertEqual(2, result["data"]["channel"])
                else:
                    self.assertEqual("character_mismatch", result["error"]["code"])
                actions = [action for invoked in desktop.call_args_list for action in invoked.args[0]]
                self.assertEqual([["Right"]], [action["keys"] for action in actions if action["action"] == "hold"])
                self.assertIn({"action": "double-click", "x": 30, "y": 10}, actions)
                self.assertEqual(
                    [
                        call("runtime-ui", ["type-private"], payload=secret)
                        for secret in ("fixture-user", "fixture-password")
                    ],
                    [
                        invoked
                        for invoked in invoke.call_args_list
                        if invoked.args[:2] == ("runtime-ui", ["type-private"])
                    ],
                )
                self.assertNotIn("fixture-password", output.getvalue())
