"""真实共享事件发布器与 CLI 消费合同；不代替游戏通知交互效果验收。"""

from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import fcntl
import io
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError
from beidou_pilot.events import EventCursor, EventReader, parse_cursor
from .test_bridge import BridgeFiles


class ClientEventsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        root = Path(__file__).resolve().parents[2]
        source = build / "event-source.cpp"
        source.write_text(
            r"""
#include "EventTransport.h"
#include <chrono>
#include <iostream>

int main(int argc, char** argv) {
    MapleControl::State state;
    state.instanceId = "client-1";
    state.sceneGeneration = 7;
    state.characterKnown = true;
    state.character.id = 4;
    MapleControl::EventTransport events(argv[1], "bridge-contract");
    if (!events.Flush(state)) return 2;
    std::cout << 0 << std::endl;
    unsigned int count = 0;
    std::uint64_t sequence = 0;
    while (std::cin >> count) {
        for (unsigned int i = 0; i < count; ++i) {
            state.observedAtMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            sequence = events.Emit(state, "notification.opened", "client-native-ui",
                MapleControl::Value::Object({{"id", "current-notification"}, {"native_kind", 99},
                    {"kind", MapleControl::Value()}, {"source_text", MapleControl::Value()},
                    {"text", MapleControl::Value()}, {"expires_at_ms", MapleControl::Value()},
                    {"remaining_ms", MapleControl::Value()}, {"pending", true}, {"available", true},
                    {"buttons", MapleControl::Value::Array({MapleControl::Value::Object(
                        {{"control_id", 2001}, {"action", "dismiss"}})})}}));
        }
        if (!events.Flush(state)) return 2;
        std::cout << sequence << std::endl;
    }
}
""",
            encoding="utf-8",
        )
        cls.executable = build / "event-source"
        subprocess.run(
            [
                "g++",
                "-std=c++20",
                "-O0",
                f"-I{root / 'shared/lua-runtime'}",
                str(source),
                str(root / "shared/lua-runtime/EventTransport.cpp"),
                str(root / "shared/lua-runtime/Observation.cpp"),
                "-o",
                str(cls.executable),
            ],
            check=True,
        )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        (self.files.root / "clientctl.py").touch()
        self.files.state.update(capabilities={"events": True}, event_stream_status="ok")
        self.files.publish()
        self.source = subprocess.Popen(
            [str(self.executable), str(self.files.directory)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        self.addCleanup(self.close_source)
        self.assertEqual(self.source.stdout.readline().strip(), "0")
        self.reader = EventReader(self.files.root, "beidou")
        self.origin = EventCursor("client-1", "bridge-contract", 0)

    def close_source(self) -> None:
        self.source.stdin.close()
        self.source.wait(timeout=3)
        self.source.stdout.close()

    def emit(self, count: int = 1) -> int:
        self.source.stdin.write(str(count) + "\n")
        self.source.stdin.flush()
        return int(self.source.stdout.readline())

    def test_cli_preserves_unknown_notification_and_single_button_without_consuming_it(self) -> None:
        self.emit()
        handles = [
            path.open("a")
            for path in (
                self.files.root / "state/maple-input.lock",
                self.files.directory / "control.lock",
                self.files.directory / "observation.lock",
            )
        ]
        self.addCleanup(lambda: [handle.close() for handle in handles])
        for handle in handles:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(self.files.root), "--json", "events", "read"])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())["data"]
        self.assertEqual(result["cursor"], {"instance_id": "client-1", "run_id": "bridge-contract", "seq": 1})
        event = result["events"][0]
        self.assertEqual(
            (event["type"], event["source"], event["character_id"], event["scene_generation"]),
            ("notification.opened", "client-native-ui", 4, 7),
        )
        self.assertIsNone(event["expires_at_ms"])
        self.assertEqual(
            event["data"],
            {
                "id": "current-notification",
                "native_kind": 99,
                "kind": None,
                "source_text": None,
                "text": None,
                "expires_at_ms": None,
                "remaining_ms": None,
                "pending": True,
                "available": True,
                "buttons": [{"control_id": 2001, "action": "dismiss"}],
            },
        )
        self.assertEqual(self.reader.read()["events"], result["events"])
        self.assertEqual(self.reader.read(parse_cursor(json.dumps(result["cursor"])))["events"], [])

    def test_watch_starts_at_baseline_and_resumes_independent_cursor_without_duplicates(self) -> None:
        self.emit()
        stream = self.reader.watch(seconds=0.04, interval=0.01)
        ready = next(stream)
        self.assertEqual((ready["event"], ready["cursor"]["seq"]), ("events_ready", 1))
        self.emit()
        observed = list(stream)
        self.assertEqual([line["cursor"]["seq"] for line in observed], [2])
        self.assertEqual(observed[0]["event"], "client_event")
        other = EventReader(self.files.root, "beidou")
        replay = list(other.watch(self.origin, seconds=0.01, interval=0.01))
        self.assertEqual([line["cursor"]["seq"] for line in replay], [0, 1, 2])

    def test_stopping_watcher_keeps_existing_game_command_and_keys(self) -> None:
        self.files.state["command"] = {"id": "owned-lua", "status": "running", "reason": None}
        self.files.state["held_keys"] = [39]
        self.files.publish()
        command = self.files.directory / "command.txt"
        command.write_text("existing Lua command\n")
        process = subprocess.Popen(
            [sys.executable, "-m", "beidou_pilot", "--root", str(self.files.root), "--json", "events", "watch"],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertTrue(select.select([process.stdout], [], [], 3)[0], "监听器未及时报告订阅就绪")
            self.assertEqual(json.loads(process.stdout.readline())["event"], "events_ready")
            self.files.publish(age=2)
            self.assertTrue(select.select([process.stdout], [], [], 3)[0], "监听器未报告采样暂不可用")
            self.assertEqual(json.loads(process.stdout.readline())["event"], "events_unavailable")
            process.send_signal(signal.SIGTERM)
            output, errors = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 130, errors)
            self.assertEqual(json.loads(output)["error"]["code"], "interrupted")
            self.assertEqual(command.read_text(), "existing Lua command\n")
            state = json.loads((self.files.directory / "state.json").read_text())
            self.assertEqual((state["command"]["status"], state["held_keys"]), ("running", [39]))
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_watch_waits_for_fresh_sample_without_repeating_diagnostics_or_advancing_cursor(self) -> None:
        stream = self.reader.watch(seconds=0.5, interval=0.01)
        ready = next(stream)
        self.files.publish(age=2)
        with self.assertRaises(ClientError) as failure:
            self.reader.read(self.origin)
        self.assertEqual(failure.exception.code, "stale_bridge_state")
        unavailable = next(stream)
        self.assertEqual(unavailable["event"], "events_unavailable")
        self.assertEqual(unavailable["cursor"], ready["cursor"])
        self.emit()
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(next, stream)
            time.sleep(0.03)
            self.assertFalse(waiting.done(), "旧采样期间不能投递事件或反复输出异常诊断")
            self.files.publish()
            resumed = waiting.result(timeout=1)
        self.assertEqual((resumed["event"], resumed["cursor"]), ("events_ready", ready["cursor"]))
        event = next(stream)
        self.assertEqual((event["event"], event["cursor"]["seq"]), ("client_event", 1))
        self.files.state["run_id"] = "successor-run"
        (self.files.root / "state/maple-session.json").write_text('{"run_id":"successor-run"}')
        self.files.publish()
        with self.assertRaises(ClientError) as failure:
            next(stream)
        self.assertEqual(failure.exception.code, "events_identity_changed")

    def test_watch_deadline_applies_while_initial_sample_is_temporarily_invalid(self) -> None:
        self.files.publish(age=-1)
        started = time.monotonic()
        reports = list(self.reader.watch(seconds=0.03, interval=0.01))
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual([report["event"] for report in reports], ["events_unavailable"])
        self.assertIsNone(reports[0]["cursor"])

    def test_slow_reader_gets_explicit_gap_from_native_retention(self) -> None:
        self.emit(129)
        with self.assertRaises(ClientError) as failure:
            self.reader.read(self.origin)
        self.assertEqual(failure.exception.code, "events_gap")
        current = self.reader.read()
        self.assertEqual((current["first_seq"], current["last_seq"], len(current["events"])), (2, 129, 128))

    def test_cursor_and_live_identity_do_not_follow_a_successor(self) -> None:
        for cursor in (EventCursor("another-client", "bridge-contract", 0), EventCursor("client-1", "old-run", 0)):
            with self.assertRaises(ClientError) as failure:
                self.reader.read(cursor)
            self.assertEqual(failure.exception.code, "events_identity_changed")
        self.files.state["run_id"] = "next-run"
        (self.files.root / "state/maple-session.json").write_text('{"run_id":"next-run"}')
        self.files.publish()
        with self.assertRaises(ClientError) as failure:
            self.reader.read()
        self.assertEqual(failure.exception.code, "events_identity_changed")

    def test_missing_capability_and_failed_publication_remain_explicit(self) -> None:
        with self.assertRaises(ClientError) as failure:
            EventReader(self.files.root, "headless")
        self.assertEqual(failure.exception.code, "unsupported_capability")
        self.files.state["capabilities"] = {}
        self.files.publish()
        with self.assertRaises(ClientError) as failure:
            self.reader.read()
        self.assertEqual(failure.exception.code, "unsupported_capability")
        self.files.state.update(capabilities={"events": True}, event_stream_status="publish_failed")
        self.files.publish()
        with self.assertRaises(ClientError) as failure:
            self.reader.read()
        self.assertEqual(failure.exception.code, "events_unavailable")


if __name__ == "__main__":
    unittest.main()
