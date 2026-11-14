"""宿主准备报告合同；Docker 替身仅核对装配请求，不代表真实镜像或游戏效果。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


DOCKER = """
import json
import os
from pathlib import Path
import sys

path = Path(os.environ["BUILD_DOCKER_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
state["calls"].append(args)
path.write_text(json.dumps(state))
if args[0] == "ps":
    print("client" if state["container"] else "")
elif args[0] == "inspect":
    print(json.dumps([state["container"]]))
elif args[:2] == ["image", "inspect"]:
    tag = args[2]
    if tag not in state["images"]:
        sys.exit(1)
    item = state["images"][tag]
    print(item["Id"] if "--format" in args else json.dumps([item]))
elif args[0] == "build":
    if state["fail_build"]:
        print("compiler fixture failed", file=sys.stderr)
        sys.exit(17)
    tag = args[args.index("--tag") + 1]
    backend = "beidou" if "-beidou:" in tag or "-beidou-ai:" in tag else "headless"
    labels = {"org.opencontainers.image.revision": tag.split(":")[-1], "beidou.backend": backend}
    if "-ai:" in tag:
        labels["beidou.harness"] = "codex"
    manifest_path = Path(args[-1]) / "build-input/manifest.json"
    state["images"][tag] = {"Id": "sha256:" + str(len(state["images"]) + 1),
                            "Config": {"Labels": labels},
                            "manifest": json.loads(manifest_path.read_text()) if manifest_path.exists() else None}
    path.write_text(json.dumps(state))
elif args[0] == "run":
    print(json.dumps(next(image["manifest"] for image in state["images"].values() if image["Id"] == args[-2])))
else:
    print("unexpected Docker operation: " + repr(args), file=sys.stderr)
    sys.exit(99)
"""


class WorkbenchBuildContract(unittest.TestCase):
    def setUp(self) -> None:
        source = Path(__file__).resolve().parents[2]
        main_root = subprocess.check_output(
            ["git", "-C", str(source), "worktree", "list", "--porcelain"], text=True
        ).splitlines()[0].removeprefix("worktree ")
        temporary_root = Path(main_root) / "tmp/56-build-report"
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repository = self.directory / "repo"
        self.repository.mkdir()
        self.entry = self.repository / "private/workbenches/workbench"
        self.entry.parent.mkdir(parents=True)
        shutil.copyfile(source / "private/workbenches/workbench", self.entry)
        self.native = self.repository / "shared/lua-runtime/TickRuntime.cpp"
        self.native.parent.mkdir(parents=True)
        self.native.write_text("native version one\n")
        self.dockerfile = self.repository / "docker/headless/Dockerfile"
        self.dockerfile.parent.mkdir(parents=True)
        self.dockerfile.write_text("RUN make -C headless CXXFLAGS=-O2\n")
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Build contract")
        self.git("config", "user.email", "build-contract@example.invalid")
        self.git("add", "private/workbenches/workbench", "shared/lua-runtime/TickRuntime.cpp", "docker/headless/Dockerfile")
        self.git("commit", "-m", "fixture source")
        self.revision = self.git("rev-parse", "HEAD")
        self.workbench = self.directory / "workbench"
        self.workbench.mkdir()
        self.state_path = self.directory / "docker.json"
        self.state_path.write_text(json.dumps({"images": {}, "container": None, "calls": [], "fail_build": False}))
        binaries = self.directory / "bin"
        binaries.mkdir()
        docker = binaries / "docker"
        docker.write_text(f"#!{sys.executable}\n" + textwrap.dedent(DOCKER))
        docker.chmod(0o700)
        self.environment = dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}",
                                BUILD_DOCKER_STATE=str(self.state_path))

    def git(self, *arguments: str) -> str:
        return subprocess.check_output(["git", "-C", str(self.repository), *arguments], text=True).strip()

    def build(self, settings: dict[str, str | bool]):
        (self.workbench / "workbench.json").write_text(json.dumps(settings))
        result = subprocess.run(
            ["bash", str(self.entry), str(self.workbench), "build"],
            env=self.environment, capture_output=True, text=True, timeout=15,
        )
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result, json.loads(result.stdout)

    def test_first_and_repeat_preparation_preserve_the_running_instance(self) -> None:
        state = json.loads(self.state_path.read_text())
        state["container"] = {
            "Id": "client", "Image": "sha256:running", "State": {"Running": True},
            "Config": {"Env": ["RUN_ID=existing-run"], "Labels": {
                "beidou.workbench": str(self.workbench), "beidou.client.instance": "default",
                "beidou.task": "client-v17-maintained", "beidou.backend": "headless",
                "org.opencontainers.image.revision": self.revision}},
            "HostConfig": {"Privileged": False, "NetworkMode": "isolated", "PortBindings": {}},
        }
        self.state_path.write_text(json.dumps(state))
        (self.repository / "README.md").write_text("Documentation update only.\n")
        self.git("add", "README.md")
        self.git("commit", "-m", "update documentation")
        prepared_revision = self.git("rev-parse", "HEAD")
        settings = {"ref": prepared_revision, "harness": True}
        first, created = self.build(settings)
        self.assertEqual(0, first.returncode, first.stderr)
        first_data = created["data"]
        self.assertEqual(prepared_revision, first_data["source_revision"])
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), first_data["preparation"]["context"]["source"]["tree"])
        self.assertEqual(["created"] * 3, [stage["outcome"] for stage in first_data["preparation"].values()])
        repeated, reused = self.build(settings)
        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual(first_data["image"], reused["data"]["image"])
        self.assertEqual(["reused"] * 3, [stage["outcome"] for stage in reused["data"]["preparation"].values()])
        for stage in reused["data"]["preparation"].values():
            self.assertGreaterEqual(stage["duration_ms"], 0)
        self.assertEqual({"container_id": "client", "image": "sha256:running", "run_id": "existing-run",
                          "running": True, "source_revision": self.revision, "native_inputs_match": True,
                          "matches_prepared_image": False}, reused["data"]["current_instance"])
        calls = json.loads(self.state_path.read_text())["calls"]
        self.assertFalse({"start", "stop", "rm", "exec", "run"} & {call[0] for call in calls})
        self.dockerfile.write_text("RUN make -C headless CXXFLAGS=-O3\n")
        self.git("add", "docker/headless/Dockerfile")
        self.git("commit", "-m", "change native compilation flags")
        changed, report = self.build({"ref": self.git("rev-parse", "HEAD")})
        self.assertEqual(0, changed.returncode, changed.stderr)
        self.assertFalse(report["data"]["current_instance"]["native_inputs_match"])

    def test_gui_reports_the_selected_manifest_and_rejects_changed_native_inputs(self) -> None:
        bridge = self.directory / "bridge"
        bridge.mkdir()
        manifest = {"source": {"commit_sha": self.revision, "tree_sha": self.git("rev-parse", "HEAD^{tree}")},
                    "target": {"executable_sha256": "client-fingerprint"},
                    "artifact": {"sha256": "bridge-fingerprint"}, "dependencies": {"lua": {"version": "5.4.9"}}}
        (bridge / "manifest.json").write_text(json.dumps(manifest))
        (bridge / "ijl15.dll").write_bytes(b"bridge fixture")
        settings = {"ref": self.revision, "backend": "beidou", "bridge_artifact": str(bridge)}
        result, report = self.build(settings)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(manifest, report["data"]["preparation"]["bridge"]["manifest"])
        self.assertEqual("artifact", report["data"]["preparation"]["bridge"]["source"])
        repeated, report = self.build(settings)
        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual(manifest, report["data"]["preparation"]["bridge"]["manifest"])
        self.assertEqual("image", report["data"]["preparation"]["bridge"]["source"])
        self.native.write_text("native version two\n")
        self.git("add", "shared/lua-runtime/TickRuntime.cpp")
        self.git("commit", "-m", "change native input")
        settings["ref"] = self.git("rev-parse", "HEAD")
        failed, report = self.build(settings)
        self.assertNotEqual(0, failed.returncode)
        self.assertEqual(("bridge_build_required", "bridge"), (report["error"]["code"], report["error"]["stage"]))
        self.assertIn("context", report["data"]["preparation"])
        self.assertNotIn("client_image", report["data"]["preparation"])

    def test_build_command_failure_keeps_diagnostics_and_reports_the_phase(self) -> None:
        state = json.loads(self.state_path.read_text())
        state["fail_build"] = True
        self.state_path.write_text(json.dumps(state))
        failed, report = self.build({"ref": self.revision})
        self.assertEqual(17, failed.returncode)
        self.assertFalse(report["ok"])
        self.assertEqual(("build_command_failed", "client_image", 17),
                         (report["error"]["code"], report["error"]["stage"], report["error"]["exit_code"]))
        self.assertIn("compiler fixture failed", failed.stderr)
        self.assertIn("context", report["data"]["preparation"])
        self.assertIsNone(report["data"]["current_instance"])


if __name__ == "__main__":
    unittest.main()
