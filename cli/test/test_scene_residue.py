"""Scene collections must discard queued spawns on clear (#387)."""

from pathlib import Path
import subprocess
import tempfile
import unittest


class SceneResidueContract(unittest.TestCase):
    def test_clear_discards_pending_spawns(self) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        native = root / "headless/src"
        with tempfile.TemporaryDirectory(prefix="scene-residue-") as temporary:
            executable = Path(temporary) / "scene_residue_contract"
            sources = [root / "cli/test/scene_residue_contract.cpp"]
            sources += [
                engine / "Gameplay/MapleMap" / f"{name}.cpp"
                for name in (
                    "MapChars",
                    "MapNpcs",
                    "MapDrops",
                    "MapReactors",
                    "MapObjects",
                )
            ]
            sources += [
                engine / "Gameplay/Physics" / f"{name}.cpp"
                for name in (
                    "Physics",
                    "FootholdTree",
                    "Foothold",
                )
            ]
            subprocess.run(
                [
                    "g++",
                    "-std=c++20",
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
                    *map(str, sources),
                    "-o",
                    str(executable),
                ],
                check=True,
                timeout=180,
            )
            subprocess.run([str(executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
