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

    def java_arguments(self):
        return (self.root / 'argv').read_text().splitlines()

    def test_help_does_not_invoke_java(self):
        result = self.run_cli('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('register', result.stdout)
        self.assertFalse((self.root / 'argv').exists())

    def test_official_commands_are_passed_through_verbatim(self):
        for args in [('version',), ('apis',), ('apis', 'give'), ('login',)]:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(self.java_arguments(),
                                 ['-Duser.home=/run/beidou-runtime', '-jar',
                                  '/run/beidou-dev/beidou-cli.jar', *args])

    def test_call_passes_method_path_and_body_through(self):
        body = '{"worldId":0,"playerId":3,"type":3,"quantity":1}'
        result = self.run_cli('call', '--force', 'POST', '/give/v1/resource', body)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['code'], 20000)
        self.assertEqual(self.java_arguments()[3:], ['call', '--force', 'POST', '/give/v1/resource', body])

    def test_batch_is_passed_through(self):
        result = self.run_cli('batch', stdin='GET /server/v1/version\nGET /server/v1/online\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.java_arguments()[3:], ['batch'])

    def test_register_uses_stdin_and_projects_business_code(self):
        sample = {'name': 'example', 'password': 'a "b" \\ c', 'language': 3}
        result = self.run_cli('register', stdin=json.dumps(sample) + '\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'code': 20000})
        self.assertEqual(self.java_arguments(), ['@/dev/stdin'])
        request = (self.root / 'request').read_text().splitlines()
        self.assertEqual(request[-5:-1], ['call', '--force', 'POST', '/account/v1'])
        self.assertEqual(json.loads(json.loads(request[-1])), sample)

    def test_register_projects_business_failures(self):
        result = self.run_cli('register', stdin='{"name":"x","password":"y","language":3}\n', code=40000)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'code': 40000})
        self.assertEqual(result.stderr, '')

    def test_register_rejects_multiple_lines_or_bad_json(self):
        for stdin in ['{}\n{}\n', 'not-json\n', '\n']:
            with self.subTest(stdin=stdin):
                self.assertEqual(self.run_cli('register', stdin=stdin).returncode, 2)
                self.assertFalse((self.root / 'argv').exists())

    def test_give_alias_keeps_fixed_endpoint(self):
        result = self.run_cli('give', '0', '42', 'item', '2000000', '1')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'code': 20000})
        request = (self.root / 'request').read_text().splitlines()
        self.assertEqual(request[-5:-1], ['call', '--force', 'POST', '/give/v1/resource'])
        self.assertEqual(json.loads(json.loads(request[-1])),
                         {'worldId': 0, 'playerId': 42, 'type': 5, 'id': 2000000, 'quantity': 1})

    def test_give_alias_rejects_unsupported_values(self):
        for args in [('give', '0', '0', 'item', '2000000', '1'),
                     ('give', '0', '1', 'item', '2000000', '40000'),
                     ('give', '0', '1', 'unknown', '1')]:
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args).returncode, 2)
                self.assertFalse((self.root / 'argv').exists())


if __name__ == '__main__':
    unittest.main()
