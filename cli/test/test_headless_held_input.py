"""真实无头输入/Combat/Player 合同；仅替换技能资源和网络，不登录或读取外部资产。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import tempfile
import unittest


class HeadlessHeldInputContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        cls.executable = build / "headless-held-input-contract"
        sources = [
            path
            for directory in ("Character", "Data", "Gameplay", "Graphics", "Audio", "Util")
            for path in sorted((engine / directory).rglob("*.cpp"))
            if path.name != "Skill.cpp"
        ]
        sources += [
            engine / name
            for name in (
                "Configuration.cpp",
                "IO/UI.cpp",
                "IO/Keyboard.cpp",
                "IO/Messages.cpp",
                "IO/UIElement.cpp",
                "IO/Window.cpp",
                "IO/Components/ChatBalloon.cpp",
                "IO/Components/Charset.cpp",
                "IO/Components/MapleFrame.cpp",
                "IO/UITypes/UIChatBar.cpp",
                "Net/OutPacket.cpp",
                "Net/Encoding.cpp",
            )
        ]
        sources += sorted((engine / "includes/NoLifeNx/nlnx").glob("*.cpp"))
        sources += [
            root / "headless/src" / name
            for name in (
                "HeadlessState.cpp",
                "LoginState.cpp",
                "Interaction.cpp",
                "QuestInteraction.cpp",
                "ImgResourceFile.cpp",
                "ImgResources.cpp",
                "ImgKeys.cpp",
                "SharedLuaAdapter.cpp",
                "TickNativeAdapter.cpp",
            )
        ]
        sources += [
            root / "shared/lua-runtime" / name for name in ("Observation.cpp", "TickRuntime.cpp", "EventTransport.cpp")
        ]
        sources += [root / "cli/test/headless_held_input_contract.cpp"]
        flags = [
            "-std=c++20",
            "-O0",
            "-w",
            "-DHEADLESS",
            "-DGLFW_INCLUDE_NONE",
            "-ffunction-sections",
            "-fdata-sections",
            "-include",
            str(root / "headless/src/PlatformIncludes.h"),
            f"-I{engine}",
            f"-I{engine / 'includes/NoLifeNx'}",
            f"-I{engine / 'includes/NoLifeNx/nlnx/includes/lz4_v1_8_2_win32/include'}",
            f"-I{engine / 'includes/glfw-3.3.2.bin.WIN64/include/GLFW'}",
            f"-I{root / 'headless/src'}",
            f"-I{root / 'shared/lua-runtime'}",
            f"-I{root / 'third_party/json/single_include'}",
            f"-I{root / 'third_party/lua'}",
        ]
        objects = [build / f"native-{index}.o" for index in range(len(sources))]

        def compile_source(pair: tuple[Path, Path]) -> None:
            source, output = pair
            source_flags = flags
            if source.name in {"ImgResources.cpp", "ImgKeys.cpp"}:
                source_flags = ["-std=c++17", *flags[1:]]
            subprocess.run(["g++", *source_flags, "-c", str(source), "-o", str(output)], cwd=build, check=True)

        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(compile_source, zip(sources, objects)))
        lua = root / "third_party/lua"
        lua_sources = sorted(
            path for path in lua.glob("*.c") if path.name not in {"lua.c", "luac.c", "ltests.c", "onelua.c"}
        )
        subprocess.run(["gcc", "-DLUA_USE_LINUX", "-O0", "-c", *map(str, lua_sources)], cwd=build, check=True)
        subprocess.run(
            [
                "g++",
                "-Wl,--gc-sections",
                *map(str, objects),
                *map(str, sorted(build.glob("l*.o"))),
                "-pthread",
                "-l:liblz4.so.1",
                "-lm",
                "-ldl",
                "-o",
                str(cls.executable),
            ],
            cwd=build,
            check=True,
        )

    def run_contract(self, scenario: str) -> None:
        subprocess.run([str(self.executable), scenario], cwd=self.executable.parent, check=True, timeout=10)

    def test_native_keys_hold_without_lua_replay_and_clear_only_owned_input(self) -> None:
        self.run_contract("keys")

    def test_real_native_admission_animation_repeat_and_a_survives_b_or_clear(self) -> None:
        self.run_contract("skills")

    def test_no_action_skill_is_not_replayed_until_a_real_intent_edge(self) -> None:
        self.run_contract("no-action")

    def test_only_held_potions_are_rate_limited_across_replacement_and_clear(self) -> None:
        self.run_contract("potions")

    def test_native_action_idle_is_not_physical_settled_and_scene_releases_everything(self) -> None:
        self.run_contract("lifecycle")

    def test_global_native_actions_do_not_fabricate_tick_ownership(self) -> None:
        self.run_contract("provenance")
