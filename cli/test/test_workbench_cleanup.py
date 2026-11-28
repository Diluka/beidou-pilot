"""工作台运行历史清理入口的离线合同；不接触真实角色或 Docker。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

from .test_workbench_build import WorkbenchFixture


DOCKER = r"""
import json
import os
from pathlib import Path
import sys

state = json.loads(Path(os.environ["CLEANUP_DOCKER_STATE"]).read_text())
args = sys.argv[1:]
if args[0] == "ps":
    if state.get("ps_error"):
        print("Docker unavailable", file=sys.stderr)
        sys.exit(70)
    if state.get("active"):
        print("client")
elif args[0] == "inspect" and "--format" in args:
    print(state["active"])
else:
    print("unexpected Docker operation: " + repr(args), file=sys.stderr)
    sys.exit(99)
"""


class WorkbenchCleanupContract(WorkbenchFixture):
    def setUp(self):
        super().setUp()
        source = Path(__file__).resolve().parents[2]
        self.cleanup = self.repository / "workbenches/cleanup-runtime"
        shutil.copyfile(source / "workbenches/cleanup-runtime", self.cleanup)
        self.cleanup.chmod(0o700)
        docker = self.directory / "bin/docker"
        docker.write_text(f"#!{sys.executable}\n" + textwrap.dedent(DOCKER))
        docker.chmod(0o700)
        self.environment["CLEANUP_DOCKER_STATE"] = str(self.state_path)

    def command_cleanup(self, *args):
        return subprocess.run(
            ["bash", str(self.cleanup), *args],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

    @staticmethod
    def run_directory(default: Path, run_id: str, marker: str):
        run = default / run_id
        run.mkdir(parents=True)
        (run / "marker.txt").write_text(marker)
        return run

    def test_dry_run_then_apply_migrates_prefix_and_preserves_active_instance(self):
        stopped = self.workbench / "runtime/default"
        legacy_id = "20261128T010203.123456789Z"
        legacy = self.run_directory(stopped, legacy_id, "legacy")
        prefix = legacy / "runtime/prefix"
        prefix.mkdir(parents=True)
        (prefix / "system.reg").write_text("wine state")
        stale = self.run_directory(stopped, "20261128T020304.123456789Z", "stale")
        stopped.joinpath("host.json").write_text(json.dumps({"run_id": legacy_id}))

        active_default = self.private_root / "live/active/runtime/default"
        active = self.run_directory(active_default, "20261128T030405.123456789Z", "active")
        active_stale = self.run_directory(active_default, "20261128T000001.123456789Z", "active stale")
        self.state_path.write_text(json.dumps({"active": str(active)}))

        preview = self.command_cleanup()

        self.assertEqual(0, preview.returncode, preview.stderr)
        self.assertIn("mode=dry-run", preview.stdout)
        self.assertIn(f"migrate {prefix} -> {stopped / 'prefix'}", preview.stdout)
        self.assertIn("candidate_runs=3", preview.stdout)
        self.assertTrue(prefix.is_dir())
        self.assertTrue(stale.is_dir())
        self.assertTrue(active.is_dir())
        self.assertTrue(active_stale.is_dir())

        applied = self.command_cleanup("--apply")

        self.assertEqual(0, applied.returncode, applied.stderr)
        self.assertIn("mode=apply", applied.stdout)
        self.assertIn("deleted_runs=3", applied.stdout)
        self.assertIn("preserved_active=1", applied.stdout)
        self.assertEqual("wine state", stopped.joinpath("prefix/system.reg").read_text())
        self.assertFalse(legacy.exists())
        self.assertFalse(stale.exists())
        self.assertTrue(active.is_dir())
        self.assertFalse(active_stale.exists())

    def test_scope_limits_cleanup_to_one_role(self):
        selected = self.run_directory(
            self.workbench / "runtime/default", "20261128T010203.123456789Z", "selected"
        )
        other = self.run_directory(
            self.private_root / "live/other/runtime/default", "20261128T020304.123456789Z", "other"
        )
        self.state_path.write_text(json.dumps({"active": ""}))

        result = self.command_cleanup("--apply", "dev/fixture")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(selected.exists())
        self.assertTrue(other.exists())
        self.assertIn("deleted_runs=1", result.stdout)

    def test_docker_query_failure_never_deletes_history(self):
        run = self.run_directory(
            self.workbench / "runtime/default", "20261128T010203.123456789Z", "preserved"
        )
        self.state_path.write_text(json.dumps({"active": "", "ps_error": True}))

        result = self.command_cleanup("--apply", "dev/fixture")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("无法查询活动客户端", result.stderr)
        self.assertTrue(run.is_dir())

    def test_ambiguous_legacy_prefixes_fail_without_deleting_either_copy(self):
        default = self.workbench / "runtime/default"
        first = self.run_directory(default, "20261128T010203.123456789Z", "first")
        second = self.run_directory(default, "20261128T020304.123456789Z", "second")
        for run in (first, second):
            prefix = run / "runtime/prefix"
            prefix.mkdir(parents=True)
            prefix.joinpath("system.reg").write_text(run.name)
        self.state_path.write_text(json.dumps({"active": ""}))

        result = self.command_cleanup("--apply", "dev/fixture")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("存在多份旧 Wine 前缀", result.stderr)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())
        self.assertFalse(default.joinpath("prefix").exists())

    def test_recorded_latest_prefix_is_kept_and_older_copies_are_history(self):
        default = self.workbench / "runtime/default"
        first = self.run_directory(default, "20261128T010203.123456789Z", "first")
        second = self.run_directory(default, "20261128T020304.123456789Z", "second")
        for run in (first, second):
            prefix = run / "runtime/prefix"
            prefix.mkdir(parents=True)
            prefix.joinpath("system.reg").write_text(run.name)
        default.joinpath("host.json").write_text(json.dumps({"run_id": second.name}))
        self.state_path.write_text(json.dumps({"active": ""}))

        result = self.command_cleanup("--apply", "dev/fixture")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(second.name, default.joinpath("prefix/system.reg").read_text())
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertIn("deleted_runs=2", result.stdout)

    def test_refuses_a_symbolic_history_directory(self):
        default = self.workbench / "runtime/default"
        default.mkdir(parents=True)
        outside = self.directory / "outside"
        outside.mkdir()
        link = default / "20261128T010203.123456789Z"
        link.symlink_to(outside, target_is_directory=True)
        self.state_path.write_text(json.dumps({"active": ""}))

        result = self.command_cleanup("--apply", "dev/fixture")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("历史运行目录不能是符号链接", result.stderr)
        self.assertTrue(outside.is_dir())
