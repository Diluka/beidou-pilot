import importlib.util
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from beidou_pilot.errors import ClientError


spec = importlib.util.spec_from_file_location('container_entrypoint', Path(__file__).resolve().parents[2] / 'docker/runtime/entrypoint.py')
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


class GuiAccountContainerTest(unittest.TestCase):
    def run_entrypoint(self, root, mode, account):
        root.joinpath('account.json').write_text(json.dumps(account))
        root.joinpath('account.json').chmod(0o600)
        root.joinpath('server.json').write_text(json.dumps(dict(project='p', service='s', network='n', expected_image='i')))
        env = dict(CLIENT_ROOT=str(root), MAPLE_BACKEND='beidou', MAPLE_INSTANCE='default', RUN_ID='run',
                   MAPLE_LOGIN_MODE=mode, HOSTNAME='container', CLIENT_IMAGE_ID='image', TARGET_IP='127.0.0.1', TARGET_CONTAINER_ID='target')
        original_read = Path.read_text
        def read_text(path, *args, **kwargs):
            if str(path) == '/opt/beidou-pilot/REVISION':
                return 'revision'
            return original_read(path, *args, **kwargs)
        with patch.dict(os.environ, env, clear=True), patch.object(Path, 'read_text', read_text), \
             patch.object(entrypoint, 'verify_binaries'), patch.object(os, 'chown'), patch.object(os, 'umask'), \
             patch.object(os, 'execv') as execute:
            entrypoint.main()
            execute.assert_called_once_with('/opt/beidou/entrypoint.sh', ['/opt/beidou/entrypoint.sh'])

    def test_account_without_character_starts_gui(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stderr = io.StringIO()
            with patch('sys.stderr', stderr):
                self.run_entrypoint(root, 'account', dict(username='user', password='secret'))
            event = json.loads(stderr.getvalue())
            self.assertEqual('login_awaiting_request', event['event'])
            self.assertIn('等待显式 login', event['message'])
            self.assertIn('尚未确认登录', event['message'])
            self.assertNotIn('secret', stderr.getvalue())
            registration = json.loads(root.joinpath('state/container.json').read_text())
            self.assertIsNone(registration['character_id'])
            self.assertNotIn('secret', json.dumps(registration))

    def test_character_mode_still_requires_cid(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ClientError) as error:
                self.run_entrypoint(Path(directory), 'character', dict(username='user', password='secret'))
            self.assertEqual(error.exception.code, 'profile_invalid')

    def test_compose_passes_explicit_mode_and_allows_missing_label(self):
        compose = (Path(__file__).resolve().parents[2] / 'docker/compose.yaml').read_text()
        self.assertIn('MAPLE_LOGIN_MODE: ${MAPLE_LOGIN_MODE:-character}', compose)
        self.assertIn('beidou.character.id: ${CHARACTER_ID:-}', compose)
