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
        "cli/beidou_pilot/cli.py",
        "cli/beidou_pilot/strategies.py",
        "cli/beidou_pilot/strategy_scene.py",
        "cli/beidou_pilot/control_scripts.py",
        "cli/beidou_pilot/script_libraries.py",
        "cli/beidou_pilot/hunting.py",
        "cli/beidou_pilot/hunt_terrain.py",
        "cli/beidou_pilot/task_management.py",
        "cli/beidou_pilot/events.py",
        "cli/beidou_pilot/notifications.py",
        "cli/beidou_pilot/engines/notifications.py",
        "cli/beidou_pilot/engines/interaction.py",
        "cli/test/test_interaction_cli.py",
        "cli/test/test_quest_interaction.py",
        "cli/test/test_scripted_portals.py",
        "cli/test/test_unified_control.py",
        "cli/test/test_strategies.py",
        "cli/test/test_task_management.py",
        "cli/test/test_lua_runtime.py",
        "cli/test/test_tick_runtime.py",
        "cli/test/test_tick_cli.py",
        "cli/test/test_tick_gui_input.py",
        "cli/test/test_allocation.py",
        "cli/test/test_native_care.py",
        "cli/test/test_task_transport.py",
        "cli/test/test_gui_key_input.py",
        "cli/test/test_native_item_use.py",
        "cli/test/test_native_observations.py",
        "cli/test/test_events.py",
        "cli/test/test_notifications.py",
        "cli/test/test_hunting.py",
        "cli/test/test_hunt_terrain.py",
        "cli/test/test_hunt_lua.py",
        "cli/test/test_route_lua.py",
        "cli/test/test_walk_to_lua.py",
        "cli/beidou_pilot/navigation.py",
        "cli/test/test_navigate_lua.py",
        "cli/test/test_catalog_resources.py",
    ),
    "clang-format": (
        "shared/lua-runtime/*.cpp",
        "shared/lua-runtime/*.h",
        "headless/src/SharedLuaAdapter.cpp",
        "headless/src/SharedLuaAdapter.h",
        "headless/src/TickNativeAdapter.cpp",
        "headless/src/TickNativeAdapter.h",
        "headless/src/Interaction.cpp",
        "headless/src/Interaction.h",
        "headless/src/QuestInteraction.cpp",
        "headless/src/QuestInteraction.h",
        "beidou-ijl15/ezorsia/AgentBridge.cpp",
        "beidou-ijl15/ezorsia/AgentBridge.h",
        "beidou-ijl15/ezorsia/NativeKeyInput.h",
        "beidou-ijl15/ezorsia/NativeKeyUnion.h",
        "beidou-ijl15/ezorsia/NativeTickInput.h",
        "beidou-ijl15/ezorsia/NativeKeyBindings.h",
        "beidou-ijl15/ezorsia/NativeMouseInput.h",
        "beidou-ijl15/ezorsia/NativeCare.h",
        "beidou-ijl15/ezorsia/NativeItemUse.h",
        "beidou-ijl15/ezorsia/NativeSkillUse.h",
        "beidou-ijl15/ezorsia/NativeObservation.cpp",
        "beidou-ijl15/ezorsia/NativeObservation.h",
        "beidou-ijl15/ezorsia/ObserveNotifications.cpp",
        "cli/test/*_contract.cpp",
    ),
    "stylua": (
        "shared/scripts/examples/*.lua",
        "shared/scripts/combat/hunt.lua",
        "cli/test/hunt_contract.lua",
        "shared/scripts/travel/_common.lua",
        "shared/scripts/travel/_terrain.lua",
        "shared/scripts/travel/_move.lua",
        "shared/scripts/travel/navigate.lua",
        "shared/scripts/travel/walk_to.lua",
        "cli/test/route_contract.lua",
        "cli/test/walk_to_contract.lua",
        "cli/test/navigate_contract.lua",
    ),
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
