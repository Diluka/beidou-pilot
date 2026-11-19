"""Structural guards for GUI AutoAp installation, not a Windows or runtime test."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from beidou_pilot.auto_ap import auto_ap
from beidou_pilot.errors import ClientError


class GuiAutoApInstallStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        cls.source = (root / "beidou-ijl15/ezorsia/AgentBridge.cpp").read_text(encoding="utf-8")

    def test_install_is_requested_only_after_runtime_tick(self) -> None:
        source = self.source
        # The only invocation is inside the AutoAp pending dispatch branch;
        # UpdateHook's idle path must not initialize the optional hook.
        self.assertEqual(source.count("PrepareNativeAutoAp("), 2)  # definition + invocation
        dispatch = source.split("bool DeliverTickInput() {", 1)[1].split("void Tick() {", 1)[0]
        branch = dispatch.split("if (tickInput.DispatchPending() && intent.kind == MapleControl::ActionKind::AutoAp", 1)[1]
        branch = branch.split("if (tickInput.DispatchPending() && intent.kind == MapleControl::ActionKind::Revive", 1)[0]
        self.assertIn("PrepareNativeAutoAp(error)", branch)
        self.assertLess(branch.index("PrepareNativeAutoAp(error)"), branch.index("tickInput.TakeDispatch(now)"))
        tick = source.split("void Tick() {", 1)[1].split("void DriveAutoApModal()", 1)[0]
        self.assertLess(tick.index("tickRuntime.Tick(changed)"), tick.index("DeliverTickInput()"))
        update = source.split("void __fastcall UpdateHook(", 1)[1].split("bool AgentBridge::Install()", 1)[0]
        self.assertNotIn("PrepareNativeAutoAp", update)
        self.assertNotIn("auto-ap-diagnostic.enable", source)

    def test_uncertain_install_is_not_reported_as_unsupported(self) -> None:
        prepare = self.source.split("bool PrepareNativeAutoAp(std::string& error) {", 1)[1].split(
            "bool DeliverTickInput() {", 1)[0]
        self.assertIn('error = "auto_ap_install_unknown"', prepare)
        self.assertIn('error = "auto_ap_unsupported"', prepare)
        self.assertIn("NativeAutoApHash::Unavailable", prepare)
        self.assertIn("NativeAutoApHash::Mismatch", prepare)
        self.assertIn("DetourTransactionCommit()", prepare)

    def test_install_state_policy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "native-auto-ap-transaction"
            subprocess.run(["g++", "-std=c++14", "-Wall", "-Wextra", "-Werror",
                            str(root / "beidou-ijl15/tests/native_auto_ap_transaction.cpp"),
                            "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True, timeout=10)

    def test_unknown_install_remains_unknown_and_is_not_retried(self) -> None:
        backend = Mock()
        backend.name = "headless"
        backend.read.return_value = {"character": {"id": 7, "strength": 10, "dexterity": 4,
            "intelligence": 4, "luck": 4, "ability_points": 2}, "native_values_valid": True}
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
             patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 7}), \
             patch("beidou_pilot.auto_ap.compile_strategy", return_value="script"):
            bridge.return_value.snapshot.return_value = {"scripts": []}
            bridge.return_value.run_script.side_effect = ClientError(
                "bridge_script_error", "failed", {"script": {"error": "auto_ap_install_unknown"}})
            with self.assertRaises(ClientError) as caught:
                auto_ap(backend)
            self.assertEqual(caught.exception.code, "unknown")
            self.assertIn("切勿重试", caught.exception.message)
            bridge.return_value.run_script.assert_called_once()
