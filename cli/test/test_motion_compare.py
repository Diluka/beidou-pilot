"""离线物理末态比较器合同；合成记录只验证对齐、去重和门槛逻辑，不代表真机数据。"""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[2] / "tools"


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


comparator = load_tool("motion_compare")
PREFIX = comparator.PREFIX


def record(
    update_id: int,
    *,
    x: float,
    y: float = 0.0,
    vx: float = 0.0,
    vy: float = 0.0,
    on_ground: bool | None = True,
    intent: str = "right",
    edge: bool = False,
    event: str = "tick",
    step_ms: int = 30,
    tick_index: int = 1,
    scenario: str = "walk",
    direction: str = "right",
) -> dict:
    return {
        "event": event,
        "scenario": scenario,
        "direction": direction,
        "phase": "walk",
        "input": intent,
        "intent_edge": edge,
        "sample": "new",
        "finish_reason": None,
        "scene": {"map_id": 100, "scene_generation": 1},
        "tick": {"index": tick_index, "gear": 4, "time": tick_index * 0.016, "delta": 0.016},
        "character_id": 7,
        "native_updates": update_id,
        "display": {"x": int(x), "y": int(y), "on_ground": on_ground},
        "velocity": None,
        "movement": {
            "model": "contract_reference",
            "effective_speed": 100,
            "effective_jump": 100,
            "max_speed": 125,
            "max_jump_height": 75,
        },
        "physics": {
            "update_id": update_id,
            "step_ms": step_ms,
            "x": x,
            "y": y,
            "velocity": None if vx is None else {"x": vx, "y": vy},
            "on_ground": on_ground,
        },
        "update_delta": 1,
    }


def walk(count: int = 6, *, x_scale: float = 1.0, step_ms: int = 30) -> list[dict]:
    return [
        record(
            update, x=(update - 1) * x_scale, vx=100.0 * x_scale, edge=update == 1, step_ms=step_ms, tick_index=update
        )
        for update in range(1, count + 1)
    ]


class MotionCompareContract(unittest.TestCase):
    def test_reader_accepts_raw_script_events_and_extracted_jsonl(self) -> None:
        first, second = walk(2)
        raw = json.dumps({"script_id": "s", "at_ms": 1, "text": PREFIX + json.dumps(first)})
        other = json.dumps({"script_id": "s", "at_ms": 2, "text": "ordinary log line"})
        extracted = PREFIX + json.dumps(second)
        records = comparator.records_from_text("\n".join([raw, other, extracted]))
        self.assertEqual([first, second], records)

    def test_identical_runs_are_comparable_and_repeated_host_frames_dedupe(self) -> None:
        records = walk(6)
        duplicated = [records[0], records[0], records[1], *records[2:]]
        result = comparator.compare(records, duplicated)
        self.assertEqual("comparable", result["status"], result)
        self.assertEqual(1, result["right"]["duplicates"])
        self.assertEqual(6, result["right"]["unique_updates"])

    def test_update_gap_missing_physics_and_unknown_ground_need_recollection(self) -> None:
        left = walk(6)
        for right, code in (
            (walk(3) + walk(6)[4:], "update_missing"),
            (
                [dict(record(1, x=0.0), physics=None), record(2, x=1.0, edge=True), *walk(6)[2:]],
                "physics_sample_missing",
            ),
            (walk(6)[:2] + [record(3, x=2.0, on_ground=None)] + walk(6)[3:], "ground_fact_missing"),
        ):
            with self.subTest(code=code):
                result = comparator.compare(left, right)
                self.assertEqual("evidence_insufficient", result["status"], result)
                self.assertIn(code, [issue["code"] for issue in result["evidence_issues"]])

    def test_step_length_and_scenario_or_direction_mismatch_are_not_comparable(self) -> None:
        left = walk(6)
        cases = (
            (walk(6, step_ms=8), "step_ms_mismatch"),
            ([dict(item, scenario="brake") for item in walk(6)], "scenario_mismatch"),
            ([dict(item, direction="left") for item in walk(6)], "direction_mismatch"),
        )
        for right, code in cases:
            with self.subTest(code=code):
                result = comparator.compare(left, right)
                self.assertEqual("evidence_insufficient", result["status"], result)
                self.assertIn(code, [issue["code"] for issue in result["evidence_issues"]])

    def test_trajectory_and_speed_threshold_failures_name_the_worst_step(self) -> None:
        left = walk(6)
        drifted = walk(6)
        drifted[3]["physics"]["x"] = left[3]["physics"]["x"] + 2.0
        result = comparator.compare(left, drifted)
        self.assertEqual("failed", result["status"], result)
        trajectory = result["comparisons"]["trajectory"]
        self.assertEqual("failed", trajectory["status"])
        self.assertEqual(3, trajectory["worst_step"])
        self.assertGreater(trajectory["max_delta"], 1.0)

        slower = walk(6)
        slower[4]["physics"]["velocity"]["x"] = 97.0
        result = comparator.compare(left, slower)
        self.assertEqual("failed", result["status"], result)
        self.assertEqual("failed", result["comparisons"]["velocity"]["status"])
        self.assertEqual(4, result["comparisons"]["velocity"]["worst_step"])

    def test_contact_events_within_one_step_pass_and_two_steps_fail(self) -> None:
        left = [
            record(1, x=0.0, edge=True),
            record(2, x=1.0),
            record(3, x=2.0, on_ground=False),
            record(4, x=3.0, on_ground=False),
            record(5, x=4.0, on_ground=True),
        ]
        right = [
            record(1, x=0.0, edge=True),
            record(2, x=1.0, on_ground=False),
            record(3, x=2.0, on_ground=False),
            record(4, x=3.0, on_ground=False),
            record(5, x=4.0, on_ground=True),
        ]
        result = comparator.compare(left, right)
        self.assertEqual("comparable", result["status"], result)
        self.assertEqual([[0, 2]], result["left"]["takeoffs"])
        self.assertEqual([[0, 1]], result["right"]["takeoffs"])
        late = [
            record(1, x=0.0, edge=True),
            record(2, x=1.0),
            record(3, x=2.0),
            record(4, x=3.0),
            record(5, x=4.0, on_ground=False),
            record(6, x=5.0, on_ground=False),
        ]
        result = comparator.compare(left, late)
        self.assertEqual("failed", result["status"], result)
        self.assertEqual("failed", result["comparisons"]["contacts"]["takeoffs"]["status"])

    def test_each_intent_edge_starts_its_own_relative_comparison_segment(self) -> None:
        def reversing(shift: float = 0.0) -> list[dict]:
            return [
                record(1, x=0.0, edge=True, intent="right"),
                record(2, x=1.0, vx=100.0),
                record(3, x=2.0, vx=100.0),
                record(4, x=3.0, edge=True, intent="left"),
                record(5, x=2.0 + shift, vx=-100.0),
                record(6, x=1.0 + shift, vx=-100.0),
            ]

        result = comparator.compare(reversing(), reversing())
        self.assertEqual("comparable", result["status"], result)
        self.assertEqual(2, len(result["left"]["input_edges"]))
        self.assertEqual(["right", "left"], result["left"]["edge_inputs"])
        drifted = comparator.compare(reversing(), reversing(shift=2.0))
        self.assertEqual("failed", drifted["status"], drifted)
        trajectory = drifted["comparisons"]["trajectory"]
        self.assertEqual((1, 1), (trajectory["worst_segment"], trajectory["worst_step"]))
        mismatched = [dict(item) for item in reversing()]
        mismatched[3] = dict(mismatched[3], input="jump")
        result = comparator.compare(reversing(), mismatched)
        self.assertEqual("evidence_insufficient", result["status"], result)
        self.assertIn("input_edges_mismatch", [issue["code"] for issue in result["evidence_issues"]])

    def test_multiple_frames_with_different_pose_inside_one_update_are_evidence_insufficient(self) -> None:
        records = walk(4)
        changed = [records[0], dict(records[1]), *records[2:]]
        changed[1]["physics"] = {**records[0]["physics"], "x": 99.0}
        changed[1]["native_updates"] = 1
        result = comparator.compare(records, changed)
        self.assertEqual("evidence_insufficient", result["status"], result)
        self.assertIn("series_unusable", [issue["code"] for issue in result["evidence_issues"]])

    def test_cli_exit_codes_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "left.json", Path(directory) / "right.json"
            left.write_text("\n".join(PREFIX + json.dumps(item) for item in walk(6)), encoding="utf-8")
            right.write_text("\n".join(PREFIX + json.dumps(item) for item in walk(6)), encoding="utf-8")
            cases = []
            with redirect_stdout(io.StringIO()) as output:
                code = comparator.main(["--left", str(left), "--right", str(right)])
            cases.append((0, code, json.loads(output.getvalue())["status"]))
            drifted = walk(6)
            drifted[2]["physics"]["x"] += 3.0
            right.write_text("\n".join(PREFIX + json.dumps(item) for item in drifted), encoding="utf-8")
            with redirect_stdout(io.StringIO()) as output:
                code = comparator.main(["--left", str(left), "--right", str(right)])
            cases.append((1, code, json.loads(output.getvalue())["status"]))
            evidence = walk(3) + walk(6)[4:]
            right.write_text("\n".join(PREFIX + json.dumps(item) for item in evidence), encoding="utf-8")
            with redirect_stdout(io.StringIO()) as output:
                code = comparator.main(["--left", str(left), "--right", str(right)])
            cases.append((3, code, json.loads(output.getvalue())["status"]))
            self.assertEqual([(0, 0, "comparable"), (1, 1, "failed"), (3, 3, "evidence_insufficient")], cases)


if __name__ == "__main__":
    unittest.main()
