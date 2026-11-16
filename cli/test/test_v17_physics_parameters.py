"""真实 IMG 解析路径下的 Physics.img 参数合同（独立字面预期，不由生产公式生成）。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

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


def physics_tree(**overrides: object) -> dict[str, object]:
    tree: dict[str, object] = {name: Real(value) for name, value in PHYSICS_VALUES.items()}
    tree.update(overrides)
    return tree


class V17PhysicsParametersContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        native = root / "headless/src"
        nlnx = engine / "includes/NoLifeNx/nlnx"
        temporary = tempfile.TemporaryDirectory(prefix="v17-parameters-")
        cls.addClassCleanup(temporary.cleanup)
        cls.build = Path(temporary.name)
        library = cls.build / "libbeidou-img.so"
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
            cwd=cls.build,
            timeout=90,
        )
        cls.executable = cls.build / "v17-parameters-contract"
        subprocess.run(
            [
                "g++",
                "-std=c++20",
                "-O0",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-DHEADLESS",
                "-ffunction-sections",
                "-fdata-sections",
                "-Wl,--gc-sections",
                "-include",
                str(native / "PlatformIncludes.h"),
                f"-I{engine}",
                f"-I{nlnx.parent}",
                f"-I{native}",
                str(native / "ImgResourceFile.cpp"),
                str(engine / "Gameplay/Physics/V17PhysicsParameters.cpp"),
                str(nlnx / "file.cpp"),
                str(nlnx / "node.cpp"),
                str(root / "cli/test/v17_physics_parameters_contract.cpp"),
                f"-L{cls.build}",
                "-Wl,-rpath,$ORIGIN",
                "-lbeidou-img",
                "-o",
                str(cls.executable),
            ],
            check=True,
            cwd=cls.build,
            timeout=90,
        )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.build)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def write(self, tree: dict[str, object]) -> Path:
        directory = self.directory / str(len(list(self.directory.iterdir())))
        write_img(directory / "Physics.img", tree)
        return directory

    def run_ok(self, scenario: str, directory: Path | None = None) -> None:
        command = [str(self.executable), scenario]
        if directory is not None:
            command.append(str(directory))
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
        self.assertEqual("ok", completed.stdout.strip())

    def test_all_nineteen_keys_are_read_from_the_real_img_parser(self) -> None:
        self.run_ok("values", self.write(physics_tree()))

    def test_named_accessors_and_byte_offset_lookup_use_one_table(self) -> None:
        # The executable covers the accessor identities together with the values;
        # this case keeps the fixture itself honest against #237's literal table.
        self.assertEqual(19, len(PHYSICS_VALUES))
        self.assertEqual(140000.0, PHYSICS_VALUES["walkForce"])
        self.assertEqual(0.35, PHYSICS_VALUES["flyJumpDec"])
        self.run_ok("values", self.write(physics_tree()))

    def test_missing_required_key_is_a_named_resource_error(self) -> None:
        tree = physics_tree()
        del tree["walkForce"]
        self.run_ok("missing", self.write(tree))

    def test_wrong_node_type_is_a_named_resource_error(self) -> None:
        self.run_ok("not-real", self.write(physics_tree(walkSpeed=125)))

    def test_non_finite_value_is_a_named_resource_error(self) -> None:
        self.run_ok("not-finite", self.write(physics_tree(jumpSpeed=Real(float("nan")))))

    def test_uninitialized_lookup_is_a_programming_error_not_zero(self) -> None:
        self.run_ok("uninitialized")

    def test_unavailable_table_is_a_resource_error(self) -> None:
        self.run_ok("missing-resource")


if __name__ == "__main__":
    unittest.main()
