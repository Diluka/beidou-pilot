"""Compile the real controller handler body against a minimal scene seam."""

from pathlib import Path
import subprocess
import tempfile
import unittest


class MobControllerContract(unittest.TestCase):
    def test_controller_only_updates_existing_oid(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / "third_party/maplestory-client/Net/Handlers/MapObjectHandlers.cpp").read_text()
        start = source.index("\tvoid SpawnMobControllerHandler::handle(")
        end = source.index("\n\tvoid MobMovedHandler::handle(", start)
        harness = (root / "cli/test/mob_controller_contract.cpp").read_text()
        with tempfile.TemporaryDirectory(prefix="mob-controller-") as temporary:
            cpp = Path(temporary) / "contract.cpp"
            binary = Path(temporary) / "contract"
            cpp.write_text(harness.replace("// HANDLER_BODY", source[start:end]))
            subprocess.run(["g++", "-std=c++20", "-DHEADLESS", str(cpp), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
