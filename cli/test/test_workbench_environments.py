"""通过公开入口检查角色分区、选服和开发服管理。Docker 仅使用临时仓库内的替身。"""

import json
import sys

from .test_workbench_build import WorkbenchFixture


SERVER_DOCKER = r"""
import json, os, re, sys
from pathlib import Path
p = Path(os.environ['BUILD_DOCKER_STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
s['calls'].append(a)
p.write_text(json.dumps(s))
if a[0] == 'ps':
    filters = [a[i+1] for i, v in enumerate(a[:-1]) if v == '--filter']
    for name, item in s['containers'].items():
        labels = item['Config']['Labels']
        if all(f.startswith('label=') and f[6:] in [k + '=' + v for k,v in labels.items()] for f in filters):
            print(name)
elif a[0] == 'inspect':
    print(json.dumps([s['containers'][key] for key in a[1:]]))
elif a[:2] == ['network','inspect']:
    print(json.dumps([s['networks'][a[2]]]))
elif a[:2] == ['volume','ls']:
    key, pattern = a[a.index('--filter') + 1].split('=', 1)
    if key != 'name' or a[a.index('--format') + 1] != '{{.Name}}':
        sys.exit('unexpected volume listing: ' + repr(a))
    for name in s['volumes']:
        if re.search(pattern, name):
            print(name)
elif a[:2] == ['volume','inspect']:
    print(json.dumps([s['volumes'][a[2]]]))
elif a[:2] == ['image','inspect']:
    if a[2] not in s['images']:
        sys.exit(1)
    print(s['images'][a[2]])
elif a[0] in ('compose', 'exec'):
    pass
else:
    sys.exit('unexpected Docker operation: ' + repr(a))
"""


class WorkbenchEnvironmentContract(WorkbenchFixture):
    def setUp(self):
        super().setUp()
        self.live = self.private_root / "live/fixture"
        self.live.mkdir(parents=True)
        self.targets = {}
        self.state = {"calls": [], "containers": {}, "networks": {}, "images": {}, "volumes": {}}
        for env, digit in (("live", "1"), ("dev", "2")):
            # 同名角色、不同项目、镜像和网络；结果必须由所选分区决定。
            project = "fixture-" + env
            network = project + "_game"
            image_id = "sha256:" + digit * 64
            image = "fixture.invalid/server@sha256:" + str(int(digit) + 2) * 64
            server_id = env + "-game"
            labels = {"com.docker.compose.project": project, "com.docker.compose.service": "beidou-server-all"}
            if env == "dev":
                labels["beidou.workbench.environment"] = "dev"
            self.state["containers"][server_id] = {
                "Id": server_id,
                "Image": image_id,
                "State": {"Running": True},
                "Config": {"Labels": labels},
                "HostConfig": {"NetworkMode": network, "PortBindings": {}},
                "NetworkSettings": {"Networks": {network: {"IPAddress": "192.0.2." + digit}}},
            }
            self.state["networks"][network] = {
                "Internal": True,
                "Labels": {"com.docker.compose.project": project, "com.docker.compose.network": "game"},
            }
            self.state["images"][image] = image_id
            self.state["images"][image_id] = image_id
            self.targets[env] = {
                "project": project,
                "service": "beidou-server-all",
                "expected_image": image,
                "network": network,
            }
            (self.config / (env + ".server.json")).write_text(json.dumps(self.targets[env]))
        env_file = self.config / "dev-server.env"
        env_file.write_text("FIXTURE_ONLY=1\n")
        env_file.chmod(0o600)
        self.state_path.write_text(json.dumps(self.state))
        (self.directory / "bin/docker").write_text(f"#!{sys.executable}\n" + SERVER_DOCKER)

    def assert_error(self, result, code=None):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(result.stdout.strip(), result.stderr)
        error = json.loads(result.stdout)["error"]
        if code is not None:
            self.assertEqual(code, error["code"], error)

    def calls(self):
        return json.loads(self.state_path.read_text())["calls"]

    def test_list_and_notes_do_not_mix_roles_with_the_same_name(self):
        for env, role in (("live", self.live), ("dev", self.workbench)):
            (role / "account.json").write_text("{}")
            (role / "STATE.md").write_text(env + " sample conditions")
            (role / "PLAN.md").write_text(env + " growth plan")
        (self.private_root / "dev/not-a-role").mkdir()
        self.assertEqual({"live/fixture", "dev/fixture"}, set(self.command("list").stdout.splitlines()))
        for env in ("live", "dev"):
            self.assertEqual([env + "/fixture"], self.command("list", env).stdout.splitlines())
        for env, expected, unexpected in (
            ("live", "live growth plan", "sample conditions"),
            ("dev", "dev sample conditions", "growth plan"),
        ):
            result = self.command(env + "/fixture", "notes")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(expected, result.stdout)
            self.assertNotIn(unexpected, result.stdout)
        self.assertEqual([], self.calls())

    def test_roles_cannot_use_external_paths_or_alias_another_partition(self):
        (self.private_root / "dev/alias").symlink_to(self.live, target_is_directory=True)
        for candidate in (str(self.workbench), "fixture", "dev/../live/fixture", "dev/alias"):
            with self.subTest(candidate=candidate):
                self.assert_error(self.command(candidate, "notes"), "invalid_workbench")
        self.assertEqual([], self.calls())

    def test_role_inputs_cannot_link_to_another_role(self):
        (self.live / "account.json").write_text("{}")
        (self.live / "scripts").mkdir()
        (self.live / "runtime/default").mkdir(parents=True)
        (self.workbench / "runtime").mkdir()
        for relative in ("account.json", "scripts", "runtime/default"):
            with self.subTest(relative=relative):
                target = self.live / relative
                link = self.workbench / relative
                link.symlink_to(target, target_is_directory=target.is_dir())
                self.assert_error(self.invoke("open"), "invalid_workbench")
                link.unlink()
        self.assertEqual([], self.calls())

    def test_plan_verifies_local_image_id_or_pinned_digest_in_the_selected_partition(self):
        target = self.targets["live"]
        target["expected_image"] = self.state["containers"]["live-game"]["Image"]
        (self.config / "live.server.json").write_text(json.dumps(target))
        for env in ("dev", "live"):
            with self.subTest(env=env):
                result = self.command(env + "/fixture", "plan")
                self.assertEqual(0, result.returncode, result.stderr + result.stdout)
                data = json.loads(result.stdout)["data"]
                self.assertEqual(env + "-game", data["container_id"])
                self.assertEqual(self.targets[env]["project"], data["project"])
                self.assertEqual(self.targets[env]["network"], data["network"])
                self.assertEqual(self.state["containers"][data["container_id"]]["Image"], data["image"])
        self.assertFalse(any(c[0] == "compose" or "connect" in c for c in self.calls()))

    def test_missing_config_or_role_override_never_selects_other_target(self):
        (self.config / "dev.server.json").unlink()
        self.assert_error(self.invoke("plan"), "server_config_required")
        (self.workbench / "workbench.json").write_text(json.dumps({"server": self.targets["live"]}))
        self.assert_error(self.invoke("plan"), "workbench_config_invalid")
        (self.workbench / "workbench.json").unlink()
        (self.workbench / "server.json").write_text(json.dumps(self.targets["live"]))
        self.assert_error(self.invoke("plan"), "workbench_migration_required")
        self.assertFalse(any("label=com.docker.compose.project=" in " ".join(c) for c in self.calls()))

    def test_dev_cannot_use_live_project_even_if_container_is_marked_dev(self):
        (self.config / "dev.server.json").write_text(json.dumps(self.targets["live"]))
        self.state["containers"]["live-game"]["Config"]["Labels"]["beidou.workbench.environment"] = "dev"
        self.state_path.write_text(json.dumps(self.state))
        self.assert_error(self.invoke("plan"), "target_invalid")
        self.assert_error(self.command("server", "dev", "stop"), "target_invalid")
        self.assertFalse(any(c[0] == "compose" for c in self.calls()))

    def test_live_cannot_use_a_dev_container(self):
        self.state["containers"]["live-game"]["Config"]["Labels"]["beidou.workbench.environment"] = "dev"
        self.state_path.write_text(json.dumps(self.state))
        self.assert_error(self.command("live/fixture", "plan"), "target_invalid")

    def test_dev_requires_its_marked_server_and_internal_project_network(self):
        container = self.state["containers"]["dev-game"]
        network = self.state["networks"][self.targets["dev"]["network"]]
        for obj, field, wrong in (
            (container["Config"]["Labels"], "beidou.workbench.environment", "live"),
            (network, "Internal", False),
            (network["Labels"], "com.docker.compose.project", self.targets["live"]["project"]),
            (network["Labels"], "com.docker.compose.network", "backend"),
            (container["HostConfig"], "PortBindings", {"8282/tcp": [{}]}),
        ):
            with self.subTest(field=field):
                previous = obj[field]
                obj[field] = wrong
                self.state_path.write_text(json.dumps(self.state))
                self.assert_error(self.invoke("plan"), "target_invalid")
                obj[field] = previous
        self.state_path.write_text(json.dumps(self.state))
        target = self.targets["dev"].copy()
        del target["network"]
        (self.config / "dev.server.json").write_text(json.dumps(target))
        self.assert_error(self.invoke("plan"), "server_config_invalid")

    def test_dev_config_cannot_route_to_database_network_or_service(self):
        for override in ({"network": "fixture-dev_backend"}, {"service": "beidou-db"}):
            with self.subTest(override=override):
                target = {**self.targets["dev"], **override}
                (self.config / "dev.server.json").write_text(json.dumps(target))
                self.assert_error(self.invoke("plan"), "server_config_invalid")
                self.assert_error(self.command("server", "dev", "up"), "server_config_invalid")
        self.assertFalse(any(c[0] == "compose" for c in self.calls()))

    def test_dev_rejects_unpinned_or_mismatched_image(self):
        self.state["images"][self.targets["dev"]["expected_image"]] = self.state["containers"]["live-game"]["Image"]
        self.state_path.write_text(json.dumps(self.state))
        self.assert_error(self.invoke("plan"), "server_image_changed")
        target = {**self.targets["dev"], "expected_image": "fixture.invalid/server:latest"}
        self.state["images"][target["expected_image"]] = self.state["containers"]["dev-game"]["Image"]
        self.state_path.write_text(json.dumps(self.state))
        (self.config / "dev.server.json").write_text(json.dumps(target))
        self.assert_error(self.invoke("plan"))
        self.assert_error(self.command("server", "dev", "up"))
        self.assertFalse(any(c[0] == "compose" for c in self.calls()))

    def test_server_management_only_targets_dev_and_stop_preserves_volumes(self):
        for op in ("status", "up", "stop", "cli"):
            self.assert_error(self.command("server", "live", op), "usage")
        self.assert_error(self.command("server", "dev", "stop", "-v"), "usage")
        self.assertEqual([], self.calls())
        for args in (("up",), ("status",), ("cli", "--help"), ("stop",)):
            with self.subTest(args=args):
                result = self.command("server", "dev", *args)
                self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        composed = [c for c in self.calls() if c[0] == "compose"]
        self.assertEqual(3, len(composed))
        for c in composed:
            self.assertEqual(self.targets["dev"]["project"], c[c.index("-p") + 1])
            self.assertEqual(str(self.repository / "docker/dev-server/compose.yaml"), c[c.index("-f") + 1])
            self.assertNotIn("down", c)
            self.assertNotIn("-v", c)
        self.assertIn("up", composed[0])
        self.assertIn("ps", composed[1])
        self.assertEqual("stop", composed[2][-1])
        executions = [c for c in self.calls() if c[0] == "exec"]
        self.assertEqual(1, len(executions))
        self.assertIn("dev-game", executions[0])
        self.assertEqual("--help", executions[0][-1])

    def test_dev_up_accepts_only_an_absent_or_owned_database_volume(self):
        project = self.targets["dev"]["project"]
        name = project + "_workbench-db"
        owned = {
            "com.docker.compose.project": project,
            "com.docker.compose.volume": "workbench-db",
            "beidou.workbench.environment": "dev",
        }
        for labels, allowed in (
            (None, True),
            (owned, True),
            ({}, False),
            ({**owned, "com.docker.compose.project": self.targets["live"]["project"]}, False),
            ({**owned, "com.docker.compose.volume": "other-db"}, False),
            ({**owned, "beidou.workbench.environment": "live"}, False),
        ):
            with self.subTest(labels=labels):
                volumes = {name + "-backup": {"Labels": {}}}
                if labels is not None:
                    volumes[name] = {"Labels": labels}
                self.state["volumes"] = volumes
                self.state_path.write_text(json.dumps(self.state))
                result = self.command("server", "dev", "up")
                calls = self.calls()
                self.assertEqual(
                    [["volume", "inspect", name]] if labels is not None else [],
                    [c for c in calls if c[:2] == ["volume", "inspect"]],
                )
                composed = [c for c in calls if c[0] == "compose"]
                if allowed:
                    self.assertEqual(0, result.returncode, result.stderr + result.stdout)
                    self.assertEqual(1, len(composed))
                    self.assertIn("up", composed[0])
                else:
                    self.assert_error(result, "target_invalid")
                    self.assertEqual([], composed)

    def test_foreign_member_of_dev_project_blocks_management(self):
        self.state["containers"]["unrelated-db"] = {
            "Config": {
                "Labels": {
                    "com.docker.compose.project": self.targets["dev"]["project"],
                    "com.docker.compose.service": "db",
                }
            }
        }
        self.state_path.write_text(json.dumps(self.state))
        for op in ("up", "stop", "cli"):
            self.assert_error(self.command("server", "dev", op), "target_invalid")
        self.assertFalse(any(c[0] == "compose" for c in self.calls()))

    def test_closing_stopped_role_does_not_touch_servers(self):
        result = self.invoke("close")
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual("closed", json.loads(result.stdout)["data"]["status"])
        self.assertEqual({"ps"}, {c[0] for c in self.calls()})
