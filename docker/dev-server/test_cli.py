"""Offline contract tests: invoke the container entry with a fake Java process."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ENTRY = Path(__file__).with_name('cli.sh').resolve()


class DevServerCliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        java = self.root / 'jdk-fixture/bin/java'
        java.parent.mkdir(parents=True)
        java.write_text('''#!/bin/sh
printf '%s\\n' "$@" > argv
if [ "$1" = @/dev/stdin ]; then tee request >/dev/null; fi
printf 'fixture diagnostic; not for display\\n' >&2
printf '{\\n  "code" : %s,\\n  "message" : "internal fixture detail",\\n  "data" : true\\n}\\n' "${FAKE_CODE:-20000}"
''')
        java.chmod(0o755)

    def run_cli(self, *args, stdin='', code=20000):
        return subprocess.run(['sh', str(ENTRY), *args], cwd=self.root,
                              env={**os.environ, 'FAKE_CODE': str(code)},
                              input=stdin, capture_output=True, text=True)

    def test_local_read(self):
        result = self.run_cli('call', 'GET', '/server/v1/online')
        self.assertEqual(result.returncode, 0)
        self.assertIs(json.loads(result.stdout)['data'], True)
        self.assertEqual((self.root/'argv').read_text().splitlines()[-3:], ['call', 'GET', '/server/v1/online'])

    def test_reject_unsupported_operations_without_invoking_java(self):
        for args in [('call', 'GET', '/other'), ('call', 'POST', '/server/v1/version'),
                     ('batch',), ('config',), ('register', 'unexpected'), ('version', '--other'),
                     ('apis', '@fixture'), ('give', '0', '0', 'item', '2000000', '1'),
                     ('give', '0', '1', 'item', '2000000', '40000')]:
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args).returncode, 2)
                self.assertFalse((self.root/'argv').exists())

    def test_mutation_has_fixed_path_and_only_projects_code(self):
        result = self.run_cli('give', '0', '42', 'item', '2000000', '1')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'code': 20000})
        self.assertEqual(result.stderr, '')
        argv = (self.root/'argv').read_text().splitlines()
        self.assertEqual(argv[-5:-1], ['call', '--force', 'POST', '/give/v1/resource'])
        self.assertEqual(json.loads(argv[-1]), {'worldId': 0, 'playerId': 42, 'type': 5, 'id': 2000000, 'quantity': 1})

    def test_registration_uses_stdin_and_projects_business_failures(self):
        sample = {'name': 'example', 'password': 'a "b" \\ c', 'language': 3}
        result = self.run_cli('register', stdin=json.dumps(sample)+'\n', code=40000)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'code': 40000})
        self.assertEqual(result.stderr, '')
        self.assertEqual((self.root/'argv').read_text().splitlines(), ['@/dev/stdin'])
        request = (self.root/'request').read_text().splitlines()
        self.assertEqual(request[-5:-1], ['call', '--force', 'POST', '/account/v1'])
        self.assertEqual(json.loads(json.loads(request[-1])), sample)

    def test_registration_rejects_multiple_lines(self):
        self.assertEqual(self.run_cli('register', stdin='{}\n{}\n').returncode, 2)
        self.assertFalse((self.root/'argv').exists())


if __name__ == '__main__':
    unittest.main()
