"""同容器 harness 的启动、私密状态及稳定角色绑定合同。"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from beidou_game_ai.cli import run
from beidou_game_ai.client import GameClientError


class LocalLauncherContract(unittest.IsolatedAsyncioTestCase):
    async def test_llm_exit_keeps_existing_native_task_and_stable_binding_across_reconnection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harness-launch-") as directory:
            root = Path(directory)
            (root / "state").mkdir()
            role = root / "role.md"
            role.write_text("保留已有角色养成约束。")
            provider = root / "provider.toml"
            provider.write_text("model_provider = 'local'\n")
            auth = root / "auth.json"
            auth.write_text("{}\n")
            args = argparse.Namespace(
                cli=root / "beidou-pilot",
                state=root / "harness",
                role=role,
                provider_config=provider,
                auth_file=auth,
                read_only=False,
                paused=False,
                model="gpt-6-luna",
                task="观察当前角色。",
            )
            bindings = []
            controllers = []
            initialized = asyncio.Event()
            server = SimpleNamespace(close=AsyncMock())
            native_task = {"id": "native-task-running", "status": "running"}
            game = SimpleNamespace(
                observe=AsyncMock(return_value={"running": True, "script": native_task}),
                cancel=AsyncMock(),
                close=AsyncMock(),
                require_idle=AsyncMock(),
            )

            def controller_factory(server, game, state, model, role, task, binding, *, read_only):
                bindings.append(binding)
                controller = SimpleNamespace(mode="starting", done=asyncio.Event(), server=server)
                controllers.append(controller)

                async def initialize():
                    initialized.set()

                async def events():
                    await controller.done.wait()

                async def control(command):
                    self.assertEqual("stop", command)
                    controller.mode = "stopped"
                    controller.done.set()

                controller.initialize = initialize
                controller.events = events
                controller.control = control
                controller.message = AsyncMock()
                controller.status = lambda: {"mode": controller.mode}
                controller.emit = lambda event, data: None
                return controller

            async def commands(controller):
                await controller.done.wait()

            environment = {
                "CLIENT_ROOT": str(root),
                "MAPLE_BACKEND": "headless",
                "MAPLE_INSTANCE": "default",
                "BEIDOU_WORKBENCH_ID": "stable-directory-id",
                "HOME": str(root / "home"),
                "OPENAI_API_KEY": "local-contract-only",
                "BEIDOU_EXEC_TOKEN": "a" * 32,
            }
            registration = {
                "backend": "headless",
                "instance": "default",
                "container_id": "container-a",
                "image": "sha256:client-image",
                "source_revision": "source-a",
                "pid": os.getpid(),
                "run_dir": str(root / "runtime"),
                "character_id": 17,
                "world": 0,
                "channel": 0,
                "target": {
                    "project": "isolated-game",
                    "service": "game",
                    "network": "isolated-network",
                    "expected_image": "sha256:server-image",
                },
                "target_ip": "172.31.0.2",
                "target_container_id": "server-a",
                "started_at": "2026-11-11T00:00:00Z",
            }
            with (
                patch("beidou_game_ai.cli.AppServer.start", new=AsyncMock(return_value=server)) as start,
                patch("beidou_game_ai.cli.Controller", side_effect=controller_factory),
                patch("beidou_game_ai.cli.GameClient", return_value=game),
                patch("beidou_game_ai.cli.commands", side_effect=commands),
                patch.dict(os.environ, environment),
            ):
                for run_id, container_id in (("run-a", "container-a"), ("run-b", "container-b")):
                    initialized.clear()
                    os.environ["RUN_ID"] = run_id
                    os.environ["HOSTNAME"] = container_id
                    registration.update(run_id=run_id, container_id=container_id)
                    (root / "state/container.json").write_text(json.dumps(registration))
                    running = asyncio.create_task(run(args))
                    await initialized.wait()
                    if run_id == "run-a":
                        os.kill(os.getpid(), signal.SIGTERM)
                    else:
                        await controllers[-1].control("stop")
                    await asyncio.wait_for(running, 2)

                self.assertEqual(bindings[0], bindings[1])
                self.assertEqual("stable-directory-id", bindings[0]["workbench_id"])
                self.assertEqual(17, bindings[0]["character_id"])
                self.assertNotIn("run_id", bindings[0])
                self.assertNotIn("client_root", bindings[0])
                self.assertEqual(2, server.close.await_count)
                self.assertEqual(2, game.observe.await_count)
                game.cancel.assert_not_awaited()
                game.close.assert_not_awaited()
                game.require_idle.assert_not_awaited()
                self.assertEqual("running", native_task["status"])
                for controller in controllers:
                    self.assertIn("native-task-running", controller.message.await_args.args[0])
                command = start.await_args.args[0]
                self.assertEqual(
                    ["/opt/beidou-game-ai/entrypoint.sh", "app-server", "--stdio", "--strict-config"], command
                )
                child_environment = start.await_args.kwargs["env"]
                self.assertEqual(str(root / "harness/codex"), child_environment["CODEX_HOME"])
                self.assertEqual(str(root / "harness/home"), child_environment["HOME"])
                self.assertEqual(str(root / "home"), os.environ["HOME"])
                self.assertEqual("0", child_environment["BEIDOU_GAME_AI_READ_ONLY"])
                self.assertEqual(str(provider), child_environment["BEIDOU_GAME_AI_PROVIDER_CONFIG"])
                self.assertEqual(str(auth), child_environment["BEIDOU_GAME_AI_AUTH_FILE"])
                self.assertEqual("local-contract-only", child_environment["OPENAI_API_KEY"])
                self.assertNotIn("BEIDOU_EXEC_TOKEN", child_environment)
                self.assertEqual(root / "harness/codex.stderr.log", start.await_args.kwargs["stderr"])

    async def test_one_llm_session_per_instance_and_independent_read_only_observer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harness-owner-") as directory:
            root = Path(directory)
            (root / "state").mkdir()
            role = root / "role.md"
            role.write_text("保留当前角色约束。")
            args = argparse.Namespace(
                cli=root / "beidou-pilot",
                state=root / "owner",
                role=role,
                provider_config=None,
                auth_file=None,
                read_only=False,
                paused=True,
                model="gpt-6-luna",
                task="继续角色计划。",
            )
            controllers = asyncio.Queue()

            def controller_factory(server, game, state, model, role, task, binding, *, read_only):
                controller = SimpleNamespace(mode="starting", done=asyncio.Event(), server=server)

                async def initialize():
                    return None

                async def events():
                    await controller.done.wait()

                async def control(command):
                    controller.mode = "stopped"
                    controller.done.set()

                controller.initialize = initialize
                controller.events = events
                controller.control = control
                controller.status = lambda: {"mode": controller.mode}
                controller.emit = lambda event, data: None
                controllers.put_nowait(controller)
                return controller

            async def commands(controller):
                await controller.done.wait()

            with (
                patch.dict(
                    os.environ, {"CLIENT_ROOT": str(root), "MAPLE_BACKEND": "headless", "BEIDOU_WORKBENCH_ID": "owner"}
                ),
                patch(
                    "beidou_game_ai.cli.load_runtime",
                    return_value=SimpleNamespace(
                        character_id=17, world=0, target={"project": "isolated-game", "service": "game"}
                    ),
                ),
                patch(
                    "beidou_game_ai.cli.AppServer.start",
                    new=AsyncMock(return_value=SimpleNamespace(close=AsyncMock())),
                ) as start,
                patch("beidou_game_ai.cli.Controller", side_effect=controller_factory),
                patch("beidou_game_ai.cli.commands", side_effect=commands),
            ):
                owner_task = asyncio.create_task(run(args))
                owner = await controllers.get()
                try:
                    other = argparse.Namespace(**{**vars(args), "state": root / "observer"})
                    with self.assertRaises(GameClientError) as competing:
                        await run(other)
                    self.assertEqual("harness_busy", competing.exception.code)
                    with self.assertRaises(GameClientError) as shared_state:
                        await run(argparse.Namespace(**{**vars(args), "read_only": True}))
                    self.assertEqual("harness_state_busy", shared_state.exception.code)
                    self.assertEqual(1, start.await_count)

                    other.read_only = True
                    observer_task = asyncio.create_task(run(other))
                    observer = await controllers.get()
                    await observer.control("stop")
                    await asyncio.wait_for(observer_task, 2)
                    self.assertEqual(2, start.await_count)
                    self.assertFalse(owner.done.is_set())
                finally:
                    await owner.control("stop")
                    await asyncio.wait_for(owner_task, 2)
