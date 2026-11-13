"""宿主首次登录参数与运行实例转发的离线合同。"""
import json
import subprocess
import unittest

from .test_workbench_build import WorkbenchBuildContract


class WorkbenchLoginContract(unittest.TestCase):
    setUp = WorkbenchBuildContract.setUp
    git = WorkbenchBuildContract.git

    def invoke(self, *args):
        return subprocess.run(["bash", str(self.entry), str(self.workbench), *args],
                              env=self.environment, capture_output=True, text=True, timeout=15)

    def running_client(self):
        root = self.workbench / "runtime/default/run"
        (root / "state").mkdir(parents=True)
        (root / "state/container.json").write_text("{}")
        state = json.loads(self.state_path.read_text())
        state["container"] = {
            "Id": "client", "Image": "image", "State": {"Running": True},
            "Config": {"User": "1000:1000", "Env": ["CLIENT_ROOT=/work/runtime/default/run"],
                       "Labels": {"beidou.workbench": str(self.workbench),
                                  "beidou.client.instance": "default", "beidou.client.root": str(root),
                                  "beidou.task": "maple-headless-maintained", "beidou.backend": "headless"}},
            "HostConfig": {"Privileged": False, "NetworkMode": "isolated", "PortBindings": {}},
        }
        self.state_path.write_text(json.dumps(state))
        docker = self.directory / "bin/docker"
        source = docker.read_text()
        source = source.replace('elif args[0] == "build":', 'elif args[0] == "exec":\n    print("{}")\nelif args[0] == "build":')
        docker.write_text(source)

    def test_running_character_request_is_forwarded_once(self):
        self.running_client()
        args = ["character", "create", "--name", "Example", "--job", "0", "--face", "1",
                "--hair", "2", "--hair-color", "0", "--skin", "3", "--top", "4", "--bottom", "5",
                "--shoes", "6", "--weapon", "7", "--gender", "female"]
        result = self.invoke(*args)
        self.assertEqual(0, result.returncode, result.stderr)
        calls = json.loads(self.state_path.read_text())["calls"]
        executions = [call for call in calls if call[0] == "exec"]
        self.assertEqual(1, len(executions))
        self.assertEqual(["beidou-pilot", "--json", *args], executions[0][executions[0].index("beidou-pilot"):])

    def test_running_login_observes_once_and_does_not_replay_options(self):
        self.running_client()
        (self.workbench / "workbench.json").write_text(json.dumps({"timeout": 42}))
        result = self.invoke("login")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = json.loads(self.state_path.read_text())["calls"]
        executions = [call for call in calls if call[0] == "exec"]
        self.assertEqual(1, len(executions))
        self.assertEqual(["beidou-pilot", "--json", "login", "--timeout", "42"], executions[0][executions[0].index("beidou-pilot"):])
        result = self.invoke("login", "--accept-terms")
        self.assertEqual("login_options_require_start", json.loads(result.stdout)["error"]["code"])
        calls = json.loads(self.state_path.read_text())["calls"]
        self.assertEqual(1, sum(call[0] == "exec" for call in calls))

    def test_running_gui_login_reports_unsupported_without_exec(self):
        self.running_client()
        state = json.loads(self.state_path.read_text())
        state["container"]["Config"]["Labels"]["beidou.backend"] = "beidou"
        self.state_path.write_text(json.dumps(state))
        result = self.invoke("login")
        self.assertEqual(2, result.returncode)
        self.assertEqual("unsupported_capability", json.loads(result.stdout)["error"]["code"])
        self.assertFalse(any(call[0] == "exec" for call in json.loads(self.state_path.read_text())["calls"]))

    def test_gui_login_rejects_unsupported_options_before_start(self):
        (self.workbench / "workbench.json").write_text(json.dumps({"backend": "beidou"}))
        result = self.invoke("login", "--gender", "female")
        self.assertEqual(2, result.returncode)
        self.assertEqual("unsupported_capability", json.loads(result.stdout)["error"]["code"])
        self.assertFalse(any(call[0] in ("run", "exec", "build", "compose")
                             for call in json.loads(self.state_path.read_text())["calls"]))

    def test_running_open_preserves_original_forwarding(self):
        self.running_client()
        record = self.workbench / "runtime/default/host.json"
        record.write_text(json.dumps({"container_id": "client", "image": "image"}))
        result = self.invoke("open")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = json.loads(self.state_path.read_text())["calls"]
        executions = [call for call in calls if call[0] == "exec"]
        self.assertEqual(1, len(executions))
        self.assertEqual(["beidou-pilot", "--json", "open", "--account", "/work/runtime/default/run/account.json",
                          "--server", "/work/runtime/default/run/server.json", "--timeout", "90"],
                         executions[0][executions[0].index("beidou-pilot"):])

    def test_completed_result_binds_only_unchanged_private_profile(self):
        self.running_client()
        record = self.workbench / "runtime/default/host.json"
        record.write_text(json.dumps({"container_id": "client", "image": "image", "run_id": "run"}))
        account = self.workbench / "account.json"
        snapshot = self.workbench / "runtime/default/run/account.json"
        profile = {"username": "fixture", "password": "fixture-secret"}
        for path in (account, snapshot):
            path.write_text(json.dumps(profile))
            path.chmod(0o600)
        docker = self.directory / "bin/docker"
        docker.write_text(docker.read_text().replace('print("{}")', 'print(json.dumps({"ok": True, "data": {"status": "unknown"}}))'))
        unknown = self.invoke("character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native")
        self.assertEqual(0, unknown.returncode)
        self.assertEqual(profile, json.loads(account.read_text()))
        source = docker.read_text().replace('print(json.dumps({"ok": True, "data": {"status": "unknown"}}))',
            'print(json.dumps({"ok": True, "data": {"status": "completed", "run_id": "run", "instance_id": "native", "request_id": "a" * 32, "character_id": 42}}))')
        docker.write_text(source)
        account.chmod(0o644)
        result = self.invoke("character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native")
        self.assertEqual(2, result.returncode)
        self.assertEqual(profile, json.loads(account.read_text()))
        account.chmod(0o600)
        result = self.invoke("character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(42, json.loads(account.read_text())["character_id"])
        calls = json.loads(self.state_path.read_text())["calls"]
        execution = [call for call in calls if call[0] == "exec"][-1]
        self.assertEqual(["beidou-pilot", "--json", "character", "result", "a" * 32,
                          "--run-id", "run", "--instance-id", "native"],
                         execution[execution.index("beidou-pilot"):])
        self.assertNotIn("fixture-secret", result.stdout + result.stderr)
        original = account.read_bytes()
        inode = account.stat().st_ino
        result = self.invoke("character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native")
        self.assertEqual(0, result.returncode)
        self.assertTrue(json.loads(result.stdout)["binding"]["ok"])
        self.assertEqual(original, account.read_bytes())
        self.assertEqual(inode, account.stat().st_ino)
        account.write_text(json.dumps({**profile, "character_id": 43}))
        result = self.invoke("character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native")
        self.assertEqual(2, result.returncode)
        self.assertEqual("account_binding_conflict", json.loads(result.stdout)["binding"]["code"])
        self.assertEqual(43, json.loads(account.read_text())["character_id"])
        account.write_text(json.dumps({**profile, "username": "other", "character_id": 42}))
        result = self.invoke("character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native")
        self.assertEqual(2, result.returncode)
        self.assertEqual("account_binding_conflict", json.loads(result.stdout)["binding"]["code"])

    def test_login_rejects_invalid_gender_before_docker(self):
        result = self.invoke("login", "--gender", "unknown")
        self.assertEqual(2, result.returncode)
        self.assertEqual("usage", json.loads(result.stdout)["error"]["code"])
        self.assertEqual([], json.loads(self.state_path.read_text())["calls"])

    def test_character_creation_requires_running_client(self):
        result = self.invoke("character", "create", "--name", "example")
        self.assertEqual(2, result.returncode)
        self.assertEqual("client_not_running", json.loads(result.stdout)["error"]["code"])
        calls = json.loads(self.state_path.read_text())["calls"]
        self.assertFalse(any(call[0] in ("run", "exec") for call in calls))


if __name__ == "__main__":
    unittest.main()
