"""Compile and run the GUI native skill-up offline contracts."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class NativeSkillUpTests(unittest.TestCase):
    def compile_and_run(self, name):
        source = ROOT / 'beidou-ijl15' / 'tests' / name
        with tempfile.TemporaryDirectory() as tmp:
            executable = pathlib.Path(tmp) / 'test'
            subprocess.run([
                'g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT / 'shared/lua-runtime'), str(source), '-o', str(executable),
            ], check=True)
            subprocess.run([str(executable)], check=True)

    def test_protocol(self):
        self.compile_and_run('native_skill_up_protocol.cpp')

    def test_facts(self):
        self.compile_and_run('native_skill_up_facts.cpp')
