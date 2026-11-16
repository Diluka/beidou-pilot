"""Shared offline fixtures for the #239 V17 motion contracts."""

from pathlib import Path
import subprocess
import tempfile

from test.img_fixture import Real, write_img


# Data/Map/Physics.img 的 19 个 real 值（#237 C.2 字面表）。
PHYSICS_VALUES = {
    "walkForce": 140000.0,
    "walkSpeed": 125.0,
    "walkDrag": 80000.0,
    "slipForce": 60000.0,
    "slipSpeed": 120.0,
    "floatDrag1": 100000.0,
    "floatDrag2": 10000.0,
    "floatCoefficient": 0.01,
    "swimForce": 120000.0,
    "swimSpeed": 140.0,
    "flyForce": 120000.0,
    "flySpeed": 200.0,
    "gravityAcc": 2000.0,
    "fallSpeed": 670.0,
    "jumpSpeed": 555.0,
    "maxFriction": 2.0,
    "minFriction": 0.05,
    "swimSpeedDec": 0.9,
    "flyJumpDec": 0.35,
}


def physics_img(directory: Path) -> Path:
    """Writes the nineteen real values as an original-format Physics.img."""
    return write_img(directory / "Physics.img", {name: Real(value) for name, value in PHYSICS_VALUES.items()})


def foothold_img(directory: Path, footholds: list[dict[str, int]]) -> Path:
    """Writes one map image whose foothold layer carries the given platforms."""
    tree: dict[str, dict[str, dict[str, dict[str, int]]]] = {"1": {"0": {}}}
    for row in footholds:
        identifier = str(row["id"])
        tree["1"]["0"][identifier] = {key: value for key, value in row.items() if key != "id"}
    return write_img(directory / "Test.img", {"foothold": tree})


def map_img(directory: Path, ladders: list[dict[str, int]]) -> Path:
    """Writes a minimal original-format map image with ladderRope entries."""
    tree: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    info = {
        "VRLeft": -9999,
        "VRRight": 9999,
        "VRTop": -9999,
        "VRBottom": 9999,
        "bgm": "Bgm00/GoPicnic",
        "cloud": 0,
        "fieldLimit": 0,
        "hideMinimap": 0,
        "mapMark": "",
        "swim": 0,
        "town": 1,
    }
    tree["1"] = {key: value for key, value in ladders[0].items() if key != "index"} if ladders else {}
    for number, ladder in enumerate(ladders[1:], start=2):
        tree[str(number)] = {key: value for key, value in ladder.items() if key != "index"}
    return write_img(
        directory / "Test.img",
        {"info": info, "seat": {}, "ladderRope": tree},
    )


def build_v17_contract(
    root: Path,
    build: Path,
    contract: str,
    *,
    motion: bool,
    parameters: bool,
    terrain: bool,
    climb: bool = False,
    mapinfo: bool = False,
) -> Path:
    """Compiles one contract against the real engine physics sources it needs."""
    engine = root / "third_party/maplestory-client"
    native = root / "headless/src"
    nlnx = engine / "includes/NoLifeNx/nlnx"
    sources = [
        native / "ImgResourceFile.cpp",
        engine / "Gameplay/Physics/Foothold.cpp",
        engine / "Gameplay/Physics/FootholdTree.cpp",
        nlnx / "file.cpp",
        nlnx / "node.cpp",
        root / "cli/test" / contract,
    ]
    if motion:
        sources.append(engine / "Gameplay/Physics/V17NormalMotion.cpp")
    if parameters:
        sources.append(engine / "Gameplay/Physics/V17PhysicsParameters.cpp")
    if climb:
        sources.append(engine / "Gameplay/Physics/V17ClimbMotion.cpp")
    if mapinfo:
        sources.append(engine / "Gameplay/MapleMap/MapInfo.cpp")
    executable = build / contract.removesuffix(".cpp")
    common = [
        "g++",
        "-std=c++20",
        "-O0",
        "-w",
        "-DHEADLESS",
        "-ffunction-sections",
        "-fdata-sections",
        "-Wl,--gc-sections",
        "-include",
        str(native / "PlatformIncludes.h"),
        f"-I{engine}",
        f"-I{engine / 'includes/NoLifeNx'}",
        f"-I{native}",
    ]
    libraries = []
    if terrain:
        library = build / "libbeidou-img.so"
        subprocess.run(
            [
                "g++",
                "-std=c++17",
                "-O2",
                "-fPIC",
                "-shared",
                str(native / "ImgResources.cpp"),
                str(native / "ImgKeys.cpp"),
                "-o",
                str(library),
            ],
            check=True,
            cwd=build,
            timeout=120,
        )
        libraries = [f"-L{build}", "-Wl,-rpath,$ORIGIN", "-lbeidou-img"]
    subprocess.run(
        [*common, *map(str, sources), *libraries, "-o", str(executable)],
        check=True,
        cwd=build,
        timeout=180,
    )
    return executable


def temporary_build(prefix: str) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    temporary = tempfile.TemporaryDirectory(prefix=prefix)
    return Path(temporary.name), temporary
