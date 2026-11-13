import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from beidou_pilot.errors import ClientError
from beidou_pilot.profile import LoginProfile
from beidou_pilot.runtime import load_runtime


class ContainerRuntimeIdentityTest(unittest.TestCase):
    def test_nullable_identity_and_character_verification(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state').mkdir()
            value = dict(backend='headless', instance='default', run_id='run', container_id='container',
                         image='image', source_revision='revision', pid=1, run_dir='/work/run',
                         character_id=None, world=0, channel=0,
                         target=dict(project='p', service='s', network='n', expected_image='i'),
                         target_ip='ip', target_container_id='target', started_at='now')
            path = root / 'state/container.json'
            with patch.dict(os.environ, {'RUN_ID': 'run', 'HOSTNAME': 'container'}):
                for cid in (None, 123, 2**31 - 1, 2**31, 0, True):
                    value['character_id'] = cid
                    path.write_text(json.dumps(value))
                    if cid == 0 or cid is True or cid == 2**31:
                        with self.assertRaises(ClientError):
                            load_runtime(root, 'headless')
                        continue
                    runtime = load_runtime(root, 'headless')
                    self.assertEqual(runtime.character_id, cid)
                    with self.assertRaises(ClientError):
                        runtime.verify_request(LoginProfile('u', 'p', 456))
                    if cid == 123:
                        runtime.verify_request(LoginProfile('u', 'p', 123))
