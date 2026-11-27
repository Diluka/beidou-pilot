"""工作台新实例启动的离线 Docker 合同，不运行 Docker 或游戏。"""
import json
from pathlib import Path
import sys

from .test_workbench_build import WorkbenchFixture


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
    s['client'] = {'Id':'client', 'Image':a[-1], 'State':{'Running':True}, 'Config':{'User':'1000:1000', 'Env':env, 'Labels':labels}, 'HostConfig':{'Privileged':False, 'NetworkMode':'fixture_game', 'PortBindings':{}}}
    p.write_text(json.dumps(s))
elif a[0] == 'compose':
    keys = ['CLIENT_ROOT', 'CLIENT_RUNTIME_ROOT', 'WORKBENCH_ROOT', 'CLIENT_IMAGE_ID', 'TARGET_CONTAINER_ID', 'TARGET_NETWORK', 'TARGET_IP', 'MAPLE_LOGIN_MODE', 'CHARACTER_ID', 'WORLD_ID', 'MAPLE_INSTANCE']
    values = {key: os.environ[key] for key in keys}
    s['compose_env'] = values
    root = Path(values['CLIENT_ROOT'])
    (root / 'state').mkdir(parents=True)
    (root / 'state/container.json').write_text('{}')
    labels = {'beidou.workbench': values['WORKBENCH_ROOT'], 'beidou.client.root': str(root), 'beidou.client.instance': values['MAPLE_INSTANCE'], 'beidou.task': 'client-v17-maintained', 'beidou.backend': 'beidou', 'beidou.character.id': values['CHARACTER_ID']}
    s['client'] = {'Id': 'client', 'Image': values['CLIENT_IMAGE_ID'], 'State': {'Running': True}, 'Config': {'User': '1000:1000', 'Env': ['CLIENT_ROOT=' + values['CLIENT_RUNTIME_ROOT']], 'Labels': labels}, 'HostConfig': {'Privileged': False, 'NetworkMode': 'fixture_game', 'PortBindings': {}}}
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


class WorkbenchLoginStartContract(WorkbenchFixture):

    def prepare(self, cid=False, env='dev'):
        if env != 'dev':
            self.role = env + '/fixture'
            self.workbench = self.private_root / self.role
            self.workbench.mkdir(parents=True)
        data = self.directory / 'data'
        data.mkdir()
        gui = self.directory / 'gui'
        gui.mkdir()
        bridge = self.directory / 'bridge'
        bridge.mkdir()
        (bridge / 'manifest.json').write_text('{}')
        (bridge / 'ijl15.dll').write_bytes(b'bridge fixture')
        (self.config / 'resources.json').write_text(json.dumps({'game_data': str(data), 'gui_client': str(gui)}))
        account = {'username': 'fixture-secret-user', 'password': 'fixture-secret-password', 'world': 1, 'channel': 2}
        if cid:
            account['character_id'] = 42
        path = self.workbench / 'account.json'
        path.write_text(json.dumps(account))
        path.chmod(0o600)
        (self.workbench / 'workbench.json').write_text(json.dumps({
            'ref': self.revision, 'timeout': 37, 'backend': 'beidou', 'bridge_artifact': str(bridge)}))
        image_id = 'sha256:' + '1' * 64
        project = 'fixture-' + env
        (self.config / (env + '.server.json')).write_text(json.dumps({'project': project, 'service': 'beidou-server-all'}))
        labels = {'beidou.workbench.environment': 'dev'} if env == 'dev' else {}
        network = project + '_default' if env == 'dev' else 'bridge'
        state = json.loads(self.state_path.read_text())
        state.update(server={'Id': 'server', 'Image': image_id, 'State': {'Running': True},
            'Config': {'Labels': labels},
            'HostConfig': {'NetworkMode': network, 'PortBindings': {}},
            'NetworkSettings': {'Networks': {network: {'IPAddress': '172.20.0.2'}}}})
        state['images'][f'local/beidou-pilot-beidou:{self.revision}'] = {'Id': 'gui-image', 'Config': {'Labels': {'org.opencontainers.image.revision': self.revision, 'beidou.backend': 'beidou'}}}
        self.state_path.write_text(json.dumps(state))
        docker = self.directory / 'bin/docker'
        docker.write_text(f'#!{sys.executable}\n' + DOCKER)
        docker.chmod(0o700)
        self.environment['WB'] = str(self.workbench)
        # 仅夹具中替换宿主设备边界；不影响生产脚本的设备检查。
        self.entry.write_text(self.entry.read_text().replace('[ -c /dev/dri/renderD128 ]', 'true')
                              .replace('$(stat -c %g /dev/dri/renderD128)', '1000'))

    def prepare_gui(self, cid=False, env='dev'):
        self.prepare(cid=cid, env=env)

    def test_login_starts_account_instance_without_exposing_credentials(self):
        self.prepare()
        result = self.invoke('login', '--accept-terms', '--gender', 'female')
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        state = json.loads(self.state_path.read_text())
        calls = state['calls']
        profile = next(c for c in calls if c[0] == 'run' and '--entrypoint' in c)
        self.assertEqual(['--mode', 'account'], profile[-2:])
        client = state['client']
        self.assertEqual('account', state['compose_env']['MAPLE_LOGIN_MODE'])
        self.assertEqual('', state['compose_env']['CHARACTER_ID'])
        self.assertEqual(str(self.workbench), client['Config']['Labels']['beidou.workbench'])
        self.assertEqual('default', client['Config']['Labels']['beidou.client.instance'])
        self.assertEqual('', client['Config']['Labels']['beidou.character.id'])
        execution = next(c for c in calls if c[0] == 'exec')
        self.assertEqual(['beidou-pilot', '--json', 'login', '--timeout', '37', '--accept-terms', '--gender', 'female'],
                         execution[execution.index('beidou-pilot'):])
        record = json.loads((self.workbench / 'runtime/default/host.json').read_text())
        self.assertEqual(('client', 'gui-image', 'server'), (record['container_id'], record['image'], record['target_container_id']))
        for secret in ('fixture-secret-user', 'fixture-secret-password'):
            self.assertNotIn(secret, json.dumps(calls) + result.stdout + result.stderr)

    def test_open_still_uses_character_profile(self):
        self.prepare(cid=True)
        result = self.invoke('open')
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        state = json.loads(self.state_path.read_text())
        profile = next(c for c in state['calls'] if c[0] == 'run' and '--entrypoint' in c)
        self.assertNotIn('--mode', profile)
        self.assertEqual('character', state['compose_env']['MAPLE_LOGIN_MODE'])
        self.assertEqual('42', state['compose_env']['CHARACTER_ID'])
        self.assertEqual('42', state['client']['Config']['Labels']['beidou.character.id'])
        execution = next(c for c in state['calls'] if c[0] == 'exec')
        self.assertIn('open', execution)

    def test_gui_account_start_and_repeat_preserve_instance(self):
        self.prepare_gui()
        first = self.invoke('login', '--accept-terms', '--gender', 'female')
        self.assertEqual(0, first.returncode, first.stderr + first.stdout)
        state = json.loads(self.state_path.read_text())
        command = next(c for c in state['calls'] if c[0] == 'compose')
        self.assertEqual(str(self.repository / 'docker/compose.yaml'), command[command.index('-f') + 1])
        self.assertIn('--no-build', command)
        self.assertEqual('account', state['compose_env']['MAPLE_LOGIN_MODE'])
        self.assertEqual('fixture-dev_default', state['compose_env']['TARGET_NETWORK'])
        self.assertEqual('beidou-server-all', state['compose_env']['TARGET_IP'])
        self.assertEqual('', state['compose_env']['CHARACTER_ID'])
        self.assertEqual('client', json.loads((self.workbench / 'runtime/default/host.json').read_text())['container_id'])
        execution = [c for c in state['calls'] if c[0] == 'exec']
        self.assertEqual(1, len(execution))
        self.assertEqual(['beidou-pilot', '--json', 'login', '--timeout', '37', '--accept-terms', '--gender', 'female'], execution[0][execution[0].index('beidou-pilot'):])
        self.assertNotIn('fixture-secret-password', json.dumps(state['calls']) + first.stdout + first.stderr)
        count = len(state['calls'])
        repeat = self.invoke('login')
        self.assertEqual(0, repeat.returncode, repeat.stderr + repeat.stdout)
        after = json.loads(self.state_path.read_text())
        self.assertEqual(state['client'], after['client'])
        calls = after['calls'][count:]
        self.assertFalse(any(c[0] in ('run', 'compose', 'rm', 'stop') for c in calls))
        execution = [c for c in calls if c[0] == 'exec']
        self.assertEqual(1, len(execution))
        self.assertEqual(['beidou-pilot', '--json', 'login', '--timeout', '37'], execution[0][execution[0].index('beidou-pilot'):])

    def test_live_gui_uses_host_gateway_and_does_not_require_game_network(self):
        self.prepare_gui(env='live')
        result = self.command('live/fixture', 'login')
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        state = json.loads(self.state_path.read_text())
        self.assertEqual('bridge', state['compose_env']['TARGET_NETWORK'])
        self.assertEqual('host.docker.internal', state['compose_env']['TARGET_IP'])
        target = json.loads((self.workbench / 'runtime/default/host.json').read_text())['target']
        self.assertEqual('bridge', target['network'])
        compose = (Path(__file__).resolve().parents[2] / 'docker/compose.yaml').read_text()
        self.assertIn('network_mode: ${TARGET_NETWORK:', compose)
        self.assertNotIn('external: true', compose)

    def test_gui_start_without_options_only_observes(self):
        self.prepare_gui()
        result = self.invoke('login')
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        calls = json.loads(self.state_path.read_text())['calls']
        execution = [c for c in calls if c[0] == 'exec']
        self.assertEqual(1, len(execution))
        self.assertEqual(['beidou-pilot', '--json', 'login', '--timeout', '37'], execution[0][execution[0].index('beidou-pilot'):])

    def test_gui_start_gender_only_does_not_infer_consent(self):
        self.prepare_gui()
        result = self.invoke('login', '--gender', 'male')
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        calls = json.loads(self.state_path.read_text())['calls']
        execution = [c for c in calls if c[0] == 'exec']
        self.assertEqual(1, len(execution))
        self.assertEqual(['beidou-pilot', '--json', 'login', '--timeout', '37', '--gender', 'male'], execution[0][execution[0].index('beidou-pilot'):])

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

    def test_cross_partition_cache_is_not_created_or_mounted(self):
        self.prepare(cid=True)
        live = self.private_root / 'live/other'
        live.mkdir(parents=True)
        alias = self.workbench / 'cache-link'
        alias.symlink_to(live, target_is_directory=True)
        config = self.workbench / 'workbench.json'
        settings = json.loads(config.read_text())
        for destination in (live / 'cache', alias / 'cache'):
            with self.subTest(destination=destination):
                config.write_text(json.dumps({**settings, 'cache_dir': str(destination)}))
                result = self.invoke('open')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('cache_dir_unavailable', json.loads(result.stdout)['error']['code'])
                self.assertFalse((live / 'cache').exists())
                calls = json.loads(self.state_path.read_text())['calls']
                self.assertFalse(any(c[0] in ('run', 'compose') for c in calls))

    def test_missing_account_and_server_without_network_do_not_start_client(self):
        self.prepare()
        (self.workbench / 'account.json').unlink()
        result = self.invoke('login')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('private_file_permissions', json.loads(result.stdout)['error']['code'])
        state = json.loads(self.state_path.read_text())
        self.assertFalse(state.get('client'))
        (self.workbench / 'account.json').write_text('{}')
        (self.workbench / 'account.json').chmod(0o600)
        state['server']['NetworkSettings']['Networks'] = {}
        self.state_path.write_text(json.dumps(state))
        result = self.invoke('login')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('target_invalid', json.loads(result.stdout)['error']['code'])
        self.assertFalse(json.loads(self.state_path.read_text()).get('client'))
