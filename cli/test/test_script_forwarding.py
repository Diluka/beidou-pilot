"""宿主转发到旧镜像时，按旧 CLI 从进程工作目录读取脚本的行为核对实际文件。"""

import argparse
from contextlib import chdir
import json
from pathlib import Path
import sys

from .test_workbench_build import DOCKER, WorkbenchFixture


class LegacyScriptForwardingContract(WorkbenchFixture):
    def setUp(self) -> None:
        super().setUp()
        self.container = self.directory / "container"
        self.container.mkdir()
        (self.container / "work").symlink_to(self.workbench, target_is_directory=True)
        state = json.loads(self.state_path.read_text())
        state["container"] = {
            "Id": "client",
            "State": {"Running": True},
            "Config": {
                "User": "1000:1000",
                "Labels": {
                    "beidou.workbench": str(self.workbench),
                    "beidou.client.instance": "default",
                    "beidou.task": "maple-headless-maintained",
                    "beidou.backend": "headless",
                },
            },
            "HostConfig": {"Privileged": False, "NetworkMode": "isolated", "PortBindings": {}},
        }
        self.state_path.write_text(json.dumps(state))
        (self.directory / "bin/docker").write_text(
            f"#!{sys.executable}\nimport json, sys\n"
            'if sys.argv[1] == "exec":\n    print(json.dumps(sys.argv[2:]))\n    sys.exit(0)\n' + DOCKER
        )

    def read_as_legacy_client(self, *arguments: str) -> str:
        result = self.invoke("script", *arguments)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        execution = json.loads(result.stdout)
        split = execution.index("client")
        self.assertEqual(["beidou-pilot", "--json", "script", *arguments], execution[split + 1 :])
        docker = argparse.ArgumentParser(allow_abbrev=False)
        docker.add_argument("-w", "--workdir", type=Path, default=Path("/work"))
        options, _ = docker.parse_known_args(execution[:split])

        # 旧镜像的文件参数是 Path，不像当前 CLI 那样带工作台前缀。
        legacy = argparse.ArgumentParser(allow_abbrev=False)
        legacy.add_argument("--debug", action="store_true")
        legacy.add_argument("--backend")
        legacy.add_argument("--seconds")
        legacy.add_argument("action", choices=("describe", "run", "start"))
        legacy.add_argument("file", type=Path, nargs="?")
        request, _ = legacy.parse_known_args(execution[split + 4 :])
        with chdir(self.container / options.workdir.relative_to("/")):
            path = request.file
            if path.is_absolute():
                path = self.container / path.relative_to("/")
            return (path / "main.lua" if path.is_dir() else path).read_text()

    def test_old_image_selects_named_file_or_package_even_with_leading_options(self) -> None:
        for directory, marker in ((self.workbench, "wrong root"), (self.workbench / "scripts", "role scripts")):
            package = directory / "nested/policy"
            package.mkdir(parents=True)
            (directory / "sample.lua").write_text(marker)
            (package / "main.lua").write_text(marker)
        for arguments in (
            ("--debug", "describe", "sample.lua"),
            ("--backend", "headless", "run", "nested/policy", "--steps", "7"),
            ("--seconds=8", "start", "sample.lua", "--steps=9"),
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual("role scripts", self.read_as_legacy_client(*arguments))

    def test_absolute_image_example_works_before_the_role_has_any_scripts(self) -> None:
        example = Path("/opt/beidou-pilot/shared/scripts/examples/sample.lua")
        image_file = self.container / example.relative_to("/")
        image_file.parent.mkdir(parents=True)
        image_file.write_text("image example")
        self.assertEqual("image example", self.read_as_legacy_client("describe", str(example)))
