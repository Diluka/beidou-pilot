"""GUI桌面原语的真实执行程序必须在正常、取消和输入失败后释放按键。"""

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from beidou_pilot.engines.desktop import CONTAINER_DESKTOP, parse_actions
from beidou_pilot.errors import JsonObject


class DesktopHarness:
    def __init__(self, *, cancel_at: float | None = None, fail_key: str | None = None) -> None:
        self.now = 0.0
        self.cancel_at = cancel_at
        self.fail_key = fail_key
        self.held: set[str] = set()
        self.commands: list[list[str]] = []

    def command(self, command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        for kind in ("keydown", "keyup"):
            if kind not in command:
                continue
            offset = command.index(kind) + 1
            keys = command[offset + 2:] if command[offset:offset + 2] == ["--delay", "0"] else command[offset:]
            for key in keys:
                if kind == "keydown":
                    self.held.add(key)
                    if key == self.fail_key:
                        raise subprocess.CalledProcessError(1, command, stderr="X11 input failed")
                else:
                    self.held.discard(key)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def read(self, command: list[str], **options: object) -> str:
        if "-tree" in command:
            return ('  0x101 ("beidou.exe" "beidou.exe") 1280x720+0+0 +0+0\n'
                    '    0x102 child 1280x700+0+0 +0+20\n')
        return "Map State: IsViewable\n"

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def execute(self) -> JsonObject:
        actions = parse_actions([{"action": "hold", "keys": ["Return"], "seconds": .4},
                                 {"action": "click", "x": 50, "y": 60}], argparse.ArgumentParser())
        payload = {"actions": actions, "screenshot": None, "game_crop": None, "run_dir": "/virtual",
                   "cancel_file": "/virtual/desktop-cancel" if self.cancel_at is not None else None}
        output = io.StringIO()
        with (patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stdout(output),
              patch("subprocess.run", side_effect=self.command), patch("subprocess.check_output", side_effect=self.read),
              patch("time.monotonic", side_effect=lambda: self.now), patch("time.sleep", side_effect=self.sleep),
              patch("signal.signal"), patch.dict("os.environ", {"RUN_ID": "desktop-contract"}),
              patch.object(Path, "write_text", return_value=0),
              patch.object(Path, "exists", autospec=True, side_effect=lambda path:
                  str(path) == "/virtual/desktop-cancel" and self.cancel_at is not None and self.now >= self.cancel_at)):
            exec(CONTAINER_DESKTOP, {})
        return json.loads(output.getvalue())


class DesktopInputContract(unittest.TestCase):
    def test_gui_key_then_click_releases_the_key(self) -> None:
        harness = DesktopHarness()
        report = harness.execute()
        self.assertFalse(report["cancelled"])
        self.assertFalse(harness.held)
        self.assertTrue(any(command[1:4] == ["mousemove", "50", "60"] for command in harness.commands))

    def test_cancel_releases_ui_key_and_skips_remaining_click(self) -> None:
        harness = DesktopHarness(cancel_at=.25)
        report = harness.execute()
        self.assertTrue(report["cancelled"])
        self.assertFalse(harness.held)
        self.assertFalse(any(command[1:4] == ["mousemove", "50", "60"] for command in harness.commands))

    def test_failed_key_dispatch_still_releases_what_may_have_been_pressed(self) -> None:
        harness = DesktopHarness(fail_key="Return")
        with self.assertRaises(subprocess.CalledProcessError):
            harness.execute()
        self.assertFalse(harness.held)


if __name__ == "__main__":
    unittest.main()
