"""离线验证统一账号配置与 GUI 选角；不替代真实客户端入图。"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import call, patch

from beidou_pilot.backend import Backend
from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError
from beidou_pilot.profile import (
    CharacterCreation,
    LoginRequest,
    load_account_profile,
    load_profile,
    validate_character_creation,
    validate_login_request,
)
from .test_bridge import BridgeFiles


class LoginProfileContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = BridgeFiles(self.root)
        self.files.runtime.update(character_id=7, channel=1)
        (self.root / "state/container.json").write_text(json.dumps(self.files.runtime))
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.server = self.root / "server.json"
        self.server.write_text(
            json.dumps({key: value for key, value in self.files.runtime["target"].items() if key != "network"})
        )
        self.account = self.root / "account.json"
        self.account.write_text(
            '{"username":"fixture-user","password":"fixture-password","character_id":7,"channel":1}'
        )
        self.account.chmod(0o600)

    def test_account_identity_does_not_change_existing_cid_contract(self) -> None:
        self.account.write_text('{"username":"fixture","password":"secret"}')
        account = load_account_profile(self.account)
        self.assertEqual("fixture", account.username)
        self.assertNotIn("secret", repr(account))
        with self.assertRaises(ClientError):
            load_profile(self.account)
        self.account.chmod(0o644)
        with self.assertRaises(ClientError) as error:
            load_account_profile(self.account)
        self.assertEqual("private_file_permissions", error.exception.code)

    def test_account_world_and_channel_match_existing_profile_contract(self) -> None:
        self.account.write_text('{"username":"fixture","password":"secret"}')
        account = load_account_profile(self.account)
        self.assertEqual((0, 0), (account.world, account.channel))
        for field in ("world", "channel"):
            for value in (0, 255):
                with self.subTest(field=field, value=value):
                    self.account.write_text(json.dumps({"username": "fixture", "password": "secret", field: value}))
                    self.assertEqual(value, getattr(load_account_profile(self.account), field))
            for value in (-1, 256, True, None, "1"):
                with self.subTest(field=field, value=value), self.assertRaises(ClientError):
                    self.account.write_text(json.dumps({"username": "fixture", "password": "secret", field: value}))
                    load_account_profile(self.account)

    def test_profile_module_account_mode_and_default(self) -> None:
        command = [sys.executable, "-m", "beidou_pilot.profile"]
        result = subprocess.run([*command, str(self.account)], capture_output=True, text=True, check=True)
        self.assertEqual({"character_id": 7, "world": 0, "channel": 1}, json.loads(result.stdout))
        self.account.write_text('{"username":"fixture-user","password":"fixture-password","channel":1}')
        result = subprocess.run(
            [*command, "--mode", "account", str(self.account)], capture_output=True, text=True, check=True
        )
        self.assertEqual({"mode": "account", "world": 0, "channel": 1}, json.loads(result.stdout))
        self.assertNotIn("fixture", result.stdout + result.stderr)
        result = subprocess.run([*command, str(self.account)], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("fixture", result.stdout + result.stderr)

    def test_login_modes_and_creation_are_separate(self) -> None:
        validate_login_request(LoginRequest("account", accept_terms=True, female=False))
        validate_login_request(LoginRequest("character", character_id=7))
        for request in (
            LoginRequest("account", character_id=7),
            LoginRequest("character"),
            LoginRequest("unknown"),
            LoginRequest("account", accept_terms=1),
            LoginRequest("account", female=0),
        ):
            with self.subTest(request=request), self.assertRaises(ClientError):
                validate_login_request(request)
        creation = CharacterCreation("name", 0, 1, 2, 3, 4, 5, 6, 7, 8, False)
        validate_character_creation(creation)
        with self.assertRaises(ClientError):
            validate_character_creation(CharacterCreation("", 0, 1, 2, 3, 4, 5, 6, 7, 8, False))
        with self.assertRaises(ClientError):
            validate_character_creation(CharacterCreation("name", True, 1, 2, 3, 4, 5, 6, 7, 8, False))

    def test_creation_int32_protocol_boundaries(self) -> None:
        from dataclasses import replace

        creation = CharacterCreation("name", 0, 1, 2, 3, 4, 5, 6, 7, 8, False)
        for field_name in ("job", "face", "hair", "hair_color", "skin", "top", "bottom", "shoes", "weapon"):
            for value in (-(2**31), 2**31 - 1):
                with self.subTest(field=field_name, value=value):
                    validate_character_creation(replace(creation, **{field_name: value}))
            for value in (-(2**31) - 1, 2**31):
                with self.subTest(field=field_name, value=value), self.assertRaises(ClientError):
                    validate_character_creation(replace(creation, **{field_name: value}))

    def test_open_requires_account_and_rejects_retired_login_options(self) -> None:
        for backend in ("beidou", "headless"):
            for options in (
                [],
                ["--account", str(self.account), "--character", "First", "--character-index", "0", "--channel", "1"],
                ["--account", str(self.account), "--profile", str(self.account), "--target", str(self.server)],
            ):
                with self.subTest(backend=backend, options=options), patch("beidou_pilot.cli.dispatch") as dispatch:
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(self.root), "--json", "--backend", backend, "open", *options])
                    self.assertEqual(2, code)
                    self.assertEqual("usage", json.loads(output.getvalue())["error"]["code"])
                    dispatch.assert_not_called()

    def test_rejects_a_cid_that_would_be_truncated_by_the_native_client(self) -> None:
        self.account.write_text('{"username":"fixture","password":"fixture","character_id":4294967298}')
        native = BridgeFiles(self.root / "headless", "headless")
        output = io.StringIO()
        with (
            patch.dict(os.environ, native.environment),
            patch("beidou_pilot.headless.open_game") as open_client,
            redirect_stdout(output),
        ):
            code = main(
                ["--root", str(native.root), "--json", "--backend", "headless", "open", "--account", str(self.account)]
            )
        self.assertEqual(2, code)
        self.assertEqual("profile_invalid", json.loads(output.getvalue())["error"]["code"])
        open_client.assert_not_called()

    def test_gui_selects_the_account_cid_and_requires_the_same_actor_in_game(self) -> None:
        first = {"id": 6, "name": "First", "index": 0}
        desired = {"id": 7, "name": "Desired", "index": 1}
        running = {
            "running": True,
            "renderer": "intel",
            "client": {"container_id": self.files.environment["HOSTNAME"], "run_id": self.files.environment["RUN_ID"]},
            "game_geometry": {"x": 0, "y": 0, "width": 1280, "height": 720},
        }
        roster = {"characters_available": True, "characters": [first, desired]}
        for observed, expected_code in ((desired, 0), (first, 2)):
            with self.subTest(observed=observed["id"]):
                stages = iter(
                    (
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
                    if name == "runtime-ui":
                        return ""
                    self.fail(f"未预期的引擎调用：{name}")

                output = io.StringIO()
                with (
                    patch.object(Backend, "_run", side_effect=engine) as invoke,
                    patch.object(Backend, "desktop") as desktop,
                    patch("beidou_pilot.session.time.sleep"),
                    redirect_stdout(output),
                ):
                    code = main(
                        [
                            "--root",
                            str(self.root),
                            "--json",
                            "open",
                            "--server",
                            str(self.server),
                            "--account",
                            str(self.account),
                        ]
                    )
                self.assertEqual(expected_code, code, output.getvalue())
                result = json.loads(output.getvalue())
                if code == 0:
                    self.assertEqual(7, result["data"]["character"]["id"])
                    self.assertEqual(2, result["data"]["channel"])
                    self.assertEqual(str(self.root / "server.json"), result["data"]["server_file"])
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
