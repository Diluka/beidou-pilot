import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / "tools/botctl"
spec = importlib.util.spec_from_loader("botctl", importlib.machinery.SourceFileLoader("botctl", str(MODULE)))
botctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(botctl)


def response(data):
    return json.dumps({"ok": True, "data": data})


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class BotctlTests(unittest.TestCase):
    def run_botctl(self, argv, responses, root):
        calls = []

        def fake_run(command, *args, **kwargs):
            calls.append(command)
            return responses[len(calls) - 1]

        with patch.object(botctl, "ROOT", root), patch.object(botctl.subprocess, "run", side_effect=fake_run):
            code = botctl.main(argv)
        return code, calls

    def test_help_lists_all_subcommands(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            botctl.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        for command in ("install", "start", "status", "stop", "logs"):
            self.assertIn(command, output.getvalue())

    def test_name_requires_partition(self):
        for name in ("hero", "live/", "live/hero/extra", "/hero"):
            with self.subTest(name=name), self.assertRaises(SystemExit):
                botctl.main(["status", name])

    def test_install_overwrites_code_and_preserves_bot_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worktree = root / "worktree"
            source = worktree / "bot"
            source.mkdir(parents=True)
            (source / "main.lua").write_text("new")
            (root / "bot").mkdir()
            (root / "bot/main.lua").write_text("wrong source")
            role = root / "private/workbenches/dev/hero"
            (role / "scripts/bot").mkdir(parents=True)
            (role / "scripts/bot/main.lua").write_text("old")
            (role / "bot").mkdir()
            (role / "bot/state.json").write_text("state")
            with patch.object(botctl, "ROOT", root), patch.object(botctl, "WORKTREE", worktree):
                self.assertEqual(botctl.main(["install", "dev/hero"]), 0)
            self.assertEqual((role / "scripts/bot/main.lua").read_text(), "new")
            self.assertEqual((role / "bot/state.json").read_text(), "state")
            self.assertTrue((role / "bot/queue/done").is_dir())
            self.assertTrue((role / "bot/queue/rejected").is_dir())

    def test_send_publishes_and_reads_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "private/workbenches/dev/hero/bot/queue"
            (queue / "done").mkdir(parents=True)
            (queue / "rejected").mkdir()

            def receive(_):
                fields = dict(line.split("=", 1) for line in (queue / "slot1.cmd").read_text().splitlines())
                self.assertEqual(fields["kind"], "status")
                self.assertEqual(fields["source"], "host")
                self.assertEqual(fields["ttl"], "10")
                self.assertTrue(int(fields["created_ms"]) > 0)
                (queue / "done" / fields["id"]).write_text("ok\n")

            output = io.StringIO()
            with (
                patch.object(botctl, "ROOT", root),
                patch.object(botctl.time, "sleep", side_effect=receive),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(botctl.main(["send", "dev/hero", "--kind", "status", "--ttl", "10"]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual((result["slot"], result["receipt"], result["content"]), (1, "done", "ok"))

    def test_send_full_queue_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "private/workbenches/dev/hero/bot/queue"
            (queue / "done").mkdir(parents=True)
            (queue / "rejected").mkdir()
            for index in range(1, 9):
                (queue / f"slot{index}.cmd").write_text("occupied")
            with patch.object(botctl, "ROOT", root), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(botctl.main(["send", "dev/hero", "--kind", "stop"]), 1)
            self.assertTrue(all((queue / f"slot{i}.cmd").read_text() == "occupied" for i in range(1, 9)))

    def test_send_timeout_does_not_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "private/workbenches/dev/hero/bot/queue"
            (queue / "done").mkdir(parents=True)
            (queue / "rejected").mkdir()
            stderr = io.StringIO()
            with (
                patch.object(botctl, "ROOT", root),
                patch.object(botctl.time, "monotonic", side_effect=[0, 4]),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(botctl.main(["send", "dev/hero", "--kind", "stop"]), 1)
            self.assertIn("可能仍在处理", stderr.getvalue())
            self.assertEqual(len(list(queue.glob("slot*.cmd"))), 1)

    def test_start_dispatches_continuous_script(self):
        root = Path("/repo")
        code, calls = self.run_botctl(["start", "dev/hero"], [Result(stdout="ok\n")], root)
        self.assertEqual(code, 0)
        self.assertEqual(calls[0][-3:], ["start", "bot", "--continuous"])

    def test_status_prints_workbench_summary_and_bot_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            role = root / "private/workbenches/dev/hero"
            (role / "bot").mkdir(parents=True)
            (role / "bot/state.json").write_text('{"mode":"follow"}')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code, _ = self.run_botctl(
                    ["status", "dev/hero"],
                    [Result(stdout=response({"scripts": [{"id": "a", "status": "running"}]}))],
                    root,
                )
            self.assertEqual(code, 0)
            self.assertIn('"a"', output.getvalue())
            self.assertIn('"mode":"follow"', output.getvalue())

    def test_stop_cancels_running_script_and_verifies_release(self):
        running = {"command": {"status": "running", "script_id": "session-1"}, "scripts": []}
        stopped = {
            "command": {"status": "cancelled", "script_id": "session-1"},
            "scripts": [{"id": "session-1", "status": "cancelled", "control_released": True}],
            "held_keys": [],
        }
        root = Path("/repo")
        code, calls = self.run_botctl(
            ["stop", "dev/hero"],
            [Result(stdout=response(running)), Result(stdout=response({})), Result(stdout=response(stopped))],
            root,
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls[1][-3:], ["cancel", "--session", "session-1"])

    def test_stop_uses_unique_active_script_when_command_lacks_id(self):
        running = {"command": {"status": "running"}, "scripts": [{"id": "session-9", "status": "running"}]}
        stopped = {
            "command": {"status": "cancelled"},
            "scripts": [{"id": "session-9", "status": "cancelled", "control_released": True}],
            "held_keys": [],
        }
        with contextlib.redirect_stdout(io.StringIO()):
            code, calls = self.run_botctl(
                ["stop", "dev/hero"],
                [Result(stdout=response(running)), Result(stdout=response({})), Result(stdout=response(stopped))],
                Path("/repo"),
            )
        self.assertEqual(code, 0)
        self.assertEqual(calls[1][-3:], ["cancel", "--session", "session-9"])

    def test_stop_rejects_unreleased_control(self):
        running = {"command": {"status": "running", "script_id": "session-1"}, "scripts": []}
        stopped = {
            "command": {"status": "cancelled", "script_id": "session-1"},
            "scripts": [{"id": "session-1", "status": "cancelled", "control_released": False}],
        }
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code, _ = self.run_botctl(
                ["stop", "dev/hero"],
                [Result(stdout=response(running)), Result(stdout=response({})), Result(stdout=response(stopped))],
                Path("/repo"),
            )
        self.assertEqual(code, 1)
        self.assertIn("control_released", stderr.getvalue())

    def test_stop_refuses_without_unique_session(self):
        idle = {"command": {"status": "idle", "script_id": None}, "scripts": [{"id": "a", "status": "stopped"}]}
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code, calls = self.run_botctl(["stop", "dev/hero"], [Result(stdout=response(idle))], Path("/repo"))
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("script.id", stderr.getvalue())

    def test_logs_tails_existing_event_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            role = root / "private/workbenches/dev/hero"
            (role / "bot").mkdir(parents=True)
            events = role / "bot/events.jsonl"
            events.write_text('{"event":1}\n')
            code, calls = self.run_botctl(["logs", "dev/hero", "--lines", "2"], [Result()], root)
            self.assertEqual(code, 0)
            self.assertEqual(calls[0][:2], ["tail", "-n"])
            self.assertEqual(Path(calls[0][-1]), events)

    def test_logs_reports_missing_event_file(self):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temp:
            with contextlib.redirect_stderr(stderr):
                code, _ = self.run_botctl(["logs", "dev/hero"], [], Path(temp))
        self.assertEqual(code, 1)
        self.assertIn("事件日志不存在", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
