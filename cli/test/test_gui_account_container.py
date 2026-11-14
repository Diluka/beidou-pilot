import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
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
            self.assertEqual('Z:\\data', os.environ['MAPLE_DATA_ROOT'])
            self.assertEqual('/data', json.loads(root.joinpath('config/resources.json').read_text())['game_data'])

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

    def test_gui_privilege_boundary_forwards_the_configured_catalog_root(self):
        source = (Path(__file__).resolve().parents[2] / 'docker/gui/entrypoint.sh').read_text()
        # Exercise the actual env arguments after reset, without running network,
        # uid/capability setup or starting a GUI on the test host.
        forwarded, remainder = source.split('\n  env ', 1)[1].rsplit(' /opt/beidou/bootstrap.sh', 1)
        self.assertEqual('\n', remainder)
        configured = dict(CLIENT_ROOT='/work', RUN_ID='fixture', MAPLE_INSTANCE='default',
                          CLIENT_IMAGE_ID='image', MAPLE_RESOURCES_CONFIG='/work/config/resources.json',
                          MAPLE_BRIDGE_DIR=r'Z:\work\runtime\bridge', MAPLE_DATA_ROOT=r'Z:\data',
                          NOT_FOR_GUI='must-be-cleared')
        result = subprocess.run(['bash', '-eu', '-c', 'setpriv --reset-env env ' + forwarded + ' /usr/bin/env'],
                                env={**os.environ, **configured}, text=True, capture_output=True, check=True)
        observed = dict(line.split('=', 1) for line in result.stdout.splitlines())
        self.assertEqual(configured['MAPLE_DATA_ROOT'], observed.get('MAPLE_DATA_ROOT'))
        self.assertEqual(configured['MAPLE_BRIDGE_DIR'], observed.get('MAPLE_BRIDGE_DIR'))
        self.assertNotIn('NOT_FOR_GUI', observed)

    def test_compose_passes_explicit_mode_and_allows_missing_label(self):
        compose = (Path(__file__).resolve().parents[2] / 'docker/compose.yaml').read_text()
        self.assertIn('MAPLE_LOGIN_MODE: ${MAPLE_LOGIN_MODE:-character}', compose)
        self.assertIn('beidou.character.id: ${CHARACTER_ID:-}', compose)
