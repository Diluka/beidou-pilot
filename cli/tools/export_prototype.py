#!/usr/bin/env python3
"""按源码白名单导出独立客户端原型；不创建仓库或携带运行资产。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import TypedDict


class ExportSummary(TypedDict):
    output: str
    files: int
    source_bytes: int


class SourceRecord(TypedDict):
    path: str
    bytes: int
    sha256: str


def export_prototype(workspace: Path, output: Path) -> ExportSummary:
    workspace, output = workspace.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError("导出目录已存在，须使用新的目录：" + str(output))
    native = workspace / "beidou-ijl15"
    files: dict[Path, Path] = {}

    def tree(source: Path, destination: Path, extensions: set[str]) -> None:
        for path in source.rglob("*"):
            if path.is_file() and path.suffix in extensions:
                files[path] = destination / path.relative_to(source)

    files[workspace / "cli/beidou-pilot"] = Path("cli/beidou-pilot")
    for name in ["LICENSE", "NOTICE", "Dockerfile", ".dockerignore", ".gitignore", "README.md", "AGENTS.md"]:
        files[workspace / name] = Path(name)
    for name in ["clientctl.py", "runtime-ui.py", "build.sh", "config/target.example.json", "config/resources.example.json"]:
        files[workspace / "cli" / name] = Path("cli") / name
    tree(workspace / "cli/beidou_pilot", Path("cli/beidou_pilot"), {".py"})
    tree(workspace / "cli/tools", Path("cli/tools"), {".py"})
    tree(workspace / "cli/test", Path("cli/test"), {".py"})
    for name in ["Dockerfile", "entrypoint.sh", "chinese-fontlink.reg"]:
        files[workspace / "cli/environment" / name] = Path("cli/environment") / name
    for name in ["Makefile", "build.sh", "agent", "LICENSE", "NOTICE", "Settings"]:
        files[workspace / "headless" / name] = Path("headless") / name
    tree(workspace / "headless/src", Path("headless/src"), {".cpp", ".h"})
    for name in ["prepare_resources.py", "img_directory_to_nx.cpp"]:
        files[workspace / "headless/tools" / name] = Path("headless/tools") / name
    engine = workspace / "third_party/maplestory-client"
    engine_output = Path("third_party/maplestory-client")
    for name in ["Audio", "Character", "Data", "Gameplay", "Graphics", "IO", "Net", "Template", "Util"]:
        tree(engine / name, engine_output / name, {".cpp", ".h", ".hpp"})
    for path in engine.glob("*.h"):
        files[path] = engine_output / path.name
    for name in ["Configuration.cpp", "LICENSE", "README.md"]:
        files[engine / name] = engine_output / name
    nx = Path("includes/NoLifeNx/nlnx")
    for path in (engine / nx).iterdir():
        if path.is_file() and path.suffix in {".cpp", ".h", ".hpp"}:
            files[path] = engine_output / nx / path.name
    for name in ["includes/glfw-3.3.2.bin.WIN64/include/GLFW/glfw3.h",
                 "includes/glfw-3.3.2.bin.WIN64/LICENSE.md",
                 "includes/NoLifeNx/nlnx/includes/lz4_v1_8_2_win32/include/lz4.h",
                 "includes/NoLifeNx/nlnx/includes/lz4_v1_8_2_win32/README.md"]:
        files[engine / name] = engine_output / name
    for name in ["Keys.cpp", "NoLifeWzToNx.cpp", "README.md"]:
        files[workspace / "third_party/nolifewztonx" / name] = Path("third_party/nolifewztonx") / name
    for name in ["single_include/nlohmann/json.hpp", "LICENSE.MIT"]:
        files[workspace / "third_party/json" / name] = Path("third_party/json") / name
    native_output = Path("beidou-ijl15")
    for name in ["LICENSE", "README.md", "ezorsia.sln"]:
        files[native / name] = native_output / name
    tree(native / "ezorsia", native_output / "ezorsia", {".cpp", ".h", ".rc", ".vcxproj", ".filters", ".ini"})
    tree(workspace / "shared/lua-runtime", Path("shared/lua-runtime"), {".cpp", ".h"})
    tree(workspace / "shared/scripts", Path("shared/scripts"), {".lua"})
    files[workspace / "shared/scripts/AGENTS.md"] = Path("shared/scripts/AGENTS.md")
    tree(workspace / "third_party/lua", Path("third_party/lua"), {".c", ".h", ".hpp"})
    for name in ["src/detours.h", "LICENSE.md"]:
        files[workspace / "third_party/detours" / name] = Path("third_party/detours") / name
    files[workspace / "third_party/UPSTREAM.json"] = Path("third_party/UPSTREAM.json")
    for name in ["ARCHITECTURE.md", "CLI.md", "CONTROL.md", "LUA_API.md", "DEPENDENCIES.md"]:
        files[workspace / "docs" / name] = Path("docs") / name
    for name in ["project.yml", ".gitignore"]:
        files[workspace / ".serena" / name] = Path(".serena") / name
    for name in ["core", "tech_stack", "suggested_commands", "conventions", "task_completion", "memory_maintenance"]:
        files[workspace / ".serena/memories" / (name + ".md")] = Path(".serena/memories") / (name + ".md")
    tree(native / "tools", native_output / "tools", {".ps1"})
    tree(native / "docs", native_output / "docs", {".md"})
    for source in files:
        if not source.is_file():
            raise FileNotFoundError(source)
    output.mkdir(parents=True)
    records: list[SourceRecord] = []
    for source, relative in sorted(files.items(), key=lambda entry: str(entry[1])):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        records.append({"path": relative.as_posix(), "bytes": destination.stat().st_size,
                        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
    manifest = {
        "format": "beidou-pilot-source-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_layout": {"cli": "cli", "headless": "headless", "beidou_ijl15": "beidou-ijl15", "shared": "shared", "third_party": "third_party"},
        "files": records,
        "generated": ["PROTOTYPE-MANIFEST.json"],
        "excluded": ["private configs and credentials", "runtime state and logs", "game assets and converted NX/XML",
                     "SoloMapling server sources and data", "Git metadata", "installers and compiled binaries"],
        "external_dependencies": {"detours_header_license": "third_party/detours/LICENSE.md",
                                  "headless_upstreams": json.loads((workspace / "third_party/UPSTREAM.json").read_text()),
                                  "gui_build": ["Visual Studio v143 and Windows SDK", "Detours Win32 static library", "Git build identity"],
                                  "gui_environment": ["matching V17 client assets", "VirtualGL amd64 and i386 packages"],
                                  "headless_runtime": ["converted NX resources", "verified Docker target", "private account profile"],
                                  "optional_metadata": "WZ XML for names, item metadata and map planning"},
    }
    (output / "PROTOTYPE-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"output": str(output), "files": len(records), "source_bytes": sum(record["bytes"] for record in records)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="新的源码导出目录，不覆盖已有内容")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(export_prototype(args.workspace, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
