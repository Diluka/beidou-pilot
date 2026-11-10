#!/usr/bin/env python3
"""按自维护源码白名单运行固定版本格式器；本地与 CI 共用此入口。"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess


SOURCES = {
    "ruff": (
        "tools/format.py",
        "harness/**/*.py",
        "cli/beidou_pilot/task_management.py",
        "cli/test/test_task_management.py",
        "cli/test/test_lua_runtime.py",
        "cli/test/test_task_transport.py",
        "cli/test/test_gui_key_input.py",
        "cli/test/test_native_item_use.py",
        "cli/test/test_native_observations.py",
    ),
    "clang-format": (
        "shared/lua-runtime/*.cpp",
        "shared/lua-runtime/*.h",
        "headless/src/SharedLuaAdapter.cpp",
        "headless/src/SharedLuaAdapter.h",
        "beidou-ijl15/ezorsia/AgentBridge.cpp",
        "beidou-ijl15/ezorsia/AgentBridge.h",
        "beidou-ijl15/ezorsia/NativeKeyInput.h",
        "beidou-ijl15/ezorsia/NativeItemUse.h",
        "beidou-ijl15/ezorsia/NativeObservation.cpp",
        "beidou-ijl15/ezorsia/NativeObservation.h",
        "cli/test/*_contract.cpp",
    ),
    "stylua": ("shared/scripts/examples/*.lua",),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="只检查，不写源码")
    mode.add_argument("--write", action="store_true", help="整理白名单内源码")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    versions = json.loads((root / "tools/format_versions.json").read_text())
    commands = {
        "ruff": ["format", "--config", str(root / "ruff.toml"), *(["--check"] if args.check else [])],
        "clang-format": [
            "--style=file:" + str(root / ".clang-format"),
            *(["--dry-run", "--Werror"] if args.check else ["-i"]),
        ],
        "stylua": ["--config-path", str(root / "stylua.toml"), "--verify", *(["--check"] if args.check else [])],
    }
    for name in SOURCES:
        if shutil.which(name) is None:
            parser.error(f"缺少 {name}，安装版本 {versions[name]}；见 docs/FORMATTING.md。")
        version = subprocess.run([name, "--version"], check=True, text=True, capture_output=True).stdout
        if versions[name] not in version.split():
            parser.error(f"{name} 版本须为 {versions[name]}，当前为 {version.strip()}。")
    failed = False
    for name, patterns in SOURCES.items():
        files = (
            subprocess.check_output(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *patterns], cwd=root
            )
            .decode()
            .split("\0")
        )
        files = sorted(set(files) - {""})
        print(f"{name}: {len(files)} files", flush=True)
        result = subprocess.run([name, *commands[name], *files], cwd=root)
        failed = failed or result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
