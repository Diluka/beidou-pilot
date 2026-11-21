import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from beidou_pilot.runtime import load_runtime


class ContainerRuntimeTest(unittest.TestCase):
    def test_loads_container_registration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state').mkdir()
            (root / 'state/container.json').write_text(json.dumps(dict(
                backend='headless', instance='default', run_id='run', container_id='container',
                image='image', source_revision='revision', pid=1, run_dir='/work/run',
                character_id=123, world=0, channel=2,
                target=dict(project='p', service='s', network='n'),
                target_ip='host.docker.internal', target_container_id='target', started_at='now',
            )))
            with patch.dict(os.environ, {'RUN_ID': 'run', 'HOSTNAME': 'container'}):
                runtime = load_runtime(root, 'headless')
            self.assertEqual(('headless', 'default', 'run', 123, 2), (runtime.backend, runtime.instance, runtime.run_id,
                                                                     runtime.character_id, runtime.channel))
            self.assertEqual(Path('/work/run'), runtime.run_dir)
            self.assertEqual('host.docker.internal', runtime.target_ip)
