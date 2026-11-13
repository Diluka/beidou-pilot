"""工作台新实例启动的离线 Docker 合同，不运行 Docker 或游戏。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from .test_workbench_build import WorkbenchBuildContract


DOCKER = r'''
import json, os, subprocess, sys
from pathlib import Path
p = Path(os.environ['BUILD_DOCKER_STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
s['calls'].append(a)
p.write_text(json.dumps(s))
if a[0] == 'ps':
    print('server' if any('com.docker.compose.service=' in x for x in a) else ('client' if s.get('client') and not any('beidou.character.id=' in x for x in a) else ''))
elif a[0] == 'inspect':
    obj = s['server'] if a[1] == 'server' else s['client']
    print(obj['Id'] if '--format' in a else json.dumps([obj]))
elif a[:2] == ['network', 'inspect']:
    print(json.dumps([{'Internal': not s.get('bad_network'), 'Labels': {'com.docker.compose.project': 'fixture'}}]))
elif a[:2] == ['image', 'inspect']:
    image = s['images'].get(a[2])
    if not image: sys.exit(1)
    print(image['Id'] if '--format' in a else json.dumps([image]))
elif a[0] == 'run' and '--entrypoint' in a:
    index = a.index('beidou_pilot.profile')
    profile = Path(os.environ['WB']) / a[index + 1].removeprefix('/work/')
    result = subprocess.run([sys.executable, '-m', 'beidou_pilot.profile', str(profile), *a[index + 2:]], capture_output=True, text=True)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    sys.exit(result.returncode)
elif a[0] == 'run' and '-d' in a:
    labels = dict(x.split('=', 1) for x in [a[i+1] for i, v in enumerate(a[:-1]) if v == '--label'])
    env = [a[i+1] for i, v in enumerate(a[:-1]) if v == '--env']
    root = Path(labels['beidou.client.root'])
    (root / 'state').mkdir(parents=True)
    (root / 'state/container.json').write_text('{}')
    s['client'] = {'Id':'client', 'Image':a[-1], 'State':{'Running':True}, 'Config':{'User':'1000:1000', 'Env':env, 'Labels':labels}, 'HostConfig':{'Privileged':False, 'NetworkMode':'fixture-net', 'PortBindings':{}}}
    p.write_text(json.dumps(s))
elif a[0] == 'compose':
    keys = ['CLIENT_ROOT', 'CLIENT_RUNTIME_ROOT', 'WORKBENCH_ROOT', 'CLIENT_IMAGE_ID', 'TARGET_CONTAINER_ID', 'MAPLE_LOGIN_MODE', 'CHARACTER_ID', 'WORLD_ID', 'MAPLE_INSTANCE']
    values = {key: os.environ[key] for key in keys}
    s['compose_env'] = values
    root = Path(values['CLIENT_ROOT'])
    (root / 'state').mkdir(parents=True)
    (root / 'state/container.json').write_text('{}')
    labels = {'beidou.workbench': values['WORKBENCH_ROOT'], 'beidou.client.root': str(root), 'beidou.client.instance': values['MAPLE_INSTANCE'], 'beidou.task': 'client-v17-maintained', 'beidou.backend': 'beidou', 'beidou.character.id': values['CHARACTER_ID']}
    s['client'] = {'Id': 'client', 'Image': values['CLIENT_IMAGE_ID'], 'State': {'Running': True}, 'Config': {'User': '1000:1000', 'Env': ['CLIENT_ROOT=' + values['CLIENT_RUNTIME_ROOT']], 'Labels': labels}, 'HostConfig': {'Privileged': False, 'NetworkMode': 'fixture-net', 'PortBindings': {}}}
    p.write_text(json.dumps(s))
elif a[0] == 'exec':
    root = Path(s['client']['Config']['Labels']['beidou.client.root'])
    if not (root / 'state/container.json').is_file():
        print('runtime not ready', file=sys.stderr)
        sys.exit(8)
    print('{}')
else:
    print('unexpected operation '+repr(a), file=sys.stderr)
    sys.exit(99)
'''


class WorkbenchLoginStartContract(unittest.TestCase):
    setUp = WorkbenchBuildContract.setUp
    git = WorkbenchBuildContract.git

    def prepare(self, cid=False, bad_network=False):
        data = self.directory / 'data'
        data.mkdir()
        (self.repository / 'private/workbenches/resources.json').write_text(json.dumps({'game_data': str(data)}))
        account = {'username': 'fixture-secret-user', 'password': 'fixture-secret-password', 'world': 1, 'channel': 2}
        if cid:
            account['character_id'] = 42
        path = self.workbench / 'account.json'
        path.write_text(json.dumps(account))
        path.chmod(0o600)
        (self.workbench / 'workbench.json').write_text(json.dumps({'ref': self.revision, 'timeout': 37, 'server': {'project': 'fixture', 'service': 'game', 'expected_image': 'server-image', 'network': 'fixture-net'}}))
        state = json.loads(self.state_path.read_text())
        state.update(server={'Id': 'server', 'Image': 'server-image', 'State': {'Running': True}, 'HostConfig': {'NetworkMode': 'fixture-net', 'PortBindings': {}}, 'NetworkSettings': {'Networks': {'fixture-net': {'IPAddress': '172.20.0.2'}}}}, bad_network=bad_network)
        state['images'][f'local/beidou-pilot-headless:{self.revision}'] = {'Id': 'client-image', 'Config': {'Labels': {'org.opencontainers.image.revision': self.revision, 'beidou.backend': 'headless'}}}
        self.state_path.write_text(json.dumps(state))
        docker = self.directory / 'bin/docker'
        docker.write_text(f'#!{sys.executable}\n' + DOCKER)
        docker.chmod(0o700)
        self.environment['WB'] = str(self.workbench)

    def prepare_gui(self, cid=False):
        self.prepare(cid=cid)
        gui = self.directory / 'gui'
        gui.mkdir()
        resources = self.repository / 'private/workbenches/resources.json'
        value = json.loads(resources.read_text())
        value['gui_client'] = str(gui)
        resources.write_text(json.dumps(value))
        settings = self.workbench / 'workbench.json'
        value = json.loads(settings.read_text())
        value['backend'] = 'beidou'
        settings.write_text(json.dumps(value))
        state = json.loads(self.state_path.read_text())
        state['images'][f'local/beidou-pilot-beidou:{self.revision}'] = {'Id': 'gui-image', 'Config': {'Labels': {'org.opencontainers.image.revision': self.revision, 'beidou.backend': 'beidou'}}}
        self.state_path.write_text(json.dumps(state))

    def invoke(self, *args):
        return subprocess.run(['bash', str(self.entry), str(self.workbench), *args], env=self.environment, capture_output=True, text=True, timeout=15)

    def test_login_starts_account_instance_without_exposing_credentials(self):
        self.prepare()
        result = self.invoke('login', '--accept-terms', '--gender', 'female')
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        state = json.loads(self.state_path.read_text())
        calls = state['calls']
        profile = next(c for c in calls if c[0] == 'run' and '--entrypoint' in c)
        self.assertEqual(['--mode', 'account'], profile[-2:])
        client = state['client']
        self.assertIn('MAPLE_LOGIN_MODE=account', client['Config']['Env'])
        self.assertIn('MAPLE_ACCEPT_TERMS=1', client['Config']['Env'])
        self.assertIn('MAPLE_FEMALE=1', client['Config']['Env'])
        self.assertEqual(str(self.workbench), client['Config']['Labels']['beidou.workbench'])
        self.assertEqual('default', client['Config']['Labels']['beidou.client.instance'])
        self.assertNotIn('beidou.character.id', client['Config']['Labels'])
        execution = next(c for c in calls if c[0] == 'exec')
        self.assertEqual(['beidou-pilot', '--json', 'login', '--timeout', '37'], execution[execution.index('beidou-pilot'):])
        record = json.loads((self.workbench / 'runtime/default/host.json').read_text())
        self.assertEqual(('client', 'client-image', 'server'), (record['container_id'], record['image'], record['target_container_id']))
        for secret in ('fixture-secret-user', 'fixture-secret-password'):
            self.assertNotIn(secret, json.dumps(calls) + result.stdout + result.stderr)

    def test_open_still_uses_character_profile(self):
        self.prepare(cid=True)
        result = self.invoke('open')
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        state = json.loads(self.state_path.read_text())
        profile = next(c for c in state['calls'] if c[0] == 'run' and '--entrypoint' in c)
        self.assertNotIn('--mode', profile)
        self.assertEqual('42', state['client']['Config']['Labels']['beidou.character.id'])
        self.assertFalse(any(x.startswith('MAPLE_LOGIN_MODE=') for x in state['client']['Config']['Env']))
        execution = next(c for c in state['calls'] if c[0] == 'exec')
        self.assertIn('open', execution)

    @unittest.skipUnless(Path('/dev/dri/renderD128').is_char_device(), '宿主缺少 GUI 渲染设备，无法通过入口的设备检查')
    def test_gui_account_start_and_repeat_preserve_instance(self):
        self.prepare_gui()
        first = self.invoke('login')
        self.assertNotEqual(0, first.returncode)
        self.assertEqual('unsupported_capability', json.loads(first.stdout)['error']['code'])
        state = json.loads(self.state_path.read_text())
        self.assertEqual('account', state['compose_env']['MAPLE_LOGIN_MODE'])
        self.assertEqual('', state['compose_env']['CHARACTER_ID'])
        self.assertEqual('client', json.loads((self.workbench / 'runtime/default/host.json').read_text())['container_id'])
        self.assertFalse(any(c[0] == 'exec' for c in state['calls']))
        count = len(state['calls'])
        repeat = self.invoke('login')
        self.assertEqual('unsupported_capability', json.loads(repeat.stdout)['error']['code'])
        after = json.loads(self.state_path.read_text())
        self.assertEqual(state['client'], after['client'])
        self.assertFalse(any(c[0] in ('run', 'compose', 'exec', 'rm', 'stop') for c in after['calls'][count:]))

    @unittest.skipUnless(Path('/dev/dri/renderD128').is_char_device(), '宿主缺少 GUI 渲染设备，无法通过入口的设备检查')
    def test_gui_open_passes_character_identity_to_compose(self):
        self.prepare_gui(cid=True)
        result = self.invoke('open')
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        state = json.loads(self.state_path.read_text())
        self.assertEqual('character', state['compose_env']['MAPLE_LOGIN_MODE'])
        self.assertEqual('42', state['compose_env']['CHARACTER_ID'])
        compose = (Path(__file__).resolve().parents[2] / 'docker/compose.yaml').read_text()
        self.assertIn('beidou.character.id: ${CHARACTER_ID:-}', compose)
        self.assertEqual('42', state['client']['Config']['Labels']['beidou.character.id'])
        self.assertTrue(any(c[0] == 'exec' and 'open' in c for c in state['calls']))

    def test_missing_account_and_invalid_network_do_not_start_client(self):
        self.prepare()
        (self.workbench / 'account.json').unlink()
        result = self.invoke('login')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('private_file_permissions', json.loads(result.stdout)['error']['code'])
        state = json.loads(self.state_path.read_text())
        self.assertFalse(state.get('client'))
        (self.workbench / 'account.json').write_text('{}')
        (self.workbench / 'account.json').chmod(0o600)
        state['bad_network'] = True
        self.state_path.write_text(json.dumps(state))
        result = self.invoke('login')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('target_invalid', json.loads(result.stdout)['error']['code'])
        self.assertFalse(json.loads(self.state_path.read_text()).get('client'))
