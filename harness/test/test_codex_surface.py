"""真实固定 Codex 对受控假端点的请求合同，不访问模型服务或游戏。"""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from typing import cast
import unittest
import uuid

from beidou_game_ai.protocol import AppServer, JsonObject, JsonValue
from beidou_game_ai.controller import GAME_TOOLS


class CodexSurfaceContract(unittest.IsolatedAsyncioTestCase):
    async def test_minimal_request_and_developer_question_round_trip(self) -> None:
        image = os.environ.get("BEIDOU_GAME_AI_IMAGE", "local/beidou-game-ai:0.167.0")
        available = subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0
        if not available:
            if "BEIDOU_GAME_AI_IMAGE" in os.environ or os.environ.get("CI"):
                self.fail("合同要求的 Codex 镜像不存在；CI 必须先构建镜像。")
            self.skipTest("尚未构建固定 Codex 镜像；仅本地开发可跳过，CI 不允许。")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        evidence = Path(os.environ.get("BEIDOU_GAME_AI_EVIDENCE", directory.name))
        evidence.mkdir(parents=True, exist_ok=True)
        identifier = "beidou-harness-contract-" + uuid.uuid4().hex[:12]
        network_id = subprocess.run(
            ["docker", "network", "create", "--internal", "--label", "beidou.dev.task=38", identifier],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        network = json.loads(
            subprocess.run(
                ["docker", "network", "inspect", network_id], check=True, capture_output=True, text=True
            ).stdout
        )[0]
        self.assertTrue(network["Internal"])
        gateway = network["IPAM"]["Config"][0]["Gateway"]
        requests: list[JsonObject] = []
        request_sizes: list[int] = []
        request_paths: list[str] = []

        class Endpoint(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_arguments: str) -> None:
                pass

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append(cast(JsonObject, json.loads(body)))
                request_sizes.append(len(body))
                request_paths.append(self.path)
                (evidence / "requests.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2) + "\n")
                if len(requests) == 1:
                    (evidence / "request.json").write_text(json.dumps(requests[0], ensure_ascii=False, indent=2) + "\n")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                if len(requests) == 1:
                    output: JsonObject = {
                        "id": "ct_observe",
                        "type": "custom_tool_call",
                        "call_id": "call_observe",
                        "name": "exec",
                        "input": 'text("AVAILABLE_TOOLS_38=" + JSON.stringify(ALL_TOOLS.map(tool => tool.name))); text(await tools.game__game_observe({}))',
                    }
                elif len(requests) == 4:
                    output = {
                        "id": "ct_hunt",
                        "type": "custom_tool_call",
                        "call_id": "call_hunt",
                        "name": "exec",
                        "input": 'text("RESUMED_TOOLS_86=" + JSON.stringify(ALL_TOOLS.map(tool => tool.name))); text(await tools.game__game_hunt({target:"100100",skill_id:1001004,range:75,seconds:60}))',
                    }
                elif len(requests) == 2:
                    output = {
                        "id": "fc_developer",
                        "type": "function_call",
                        "call_id": "call_developer",
                        "name": "request_user_input",
                        "arguments": json.dumps(
                            {
                                "questions": [
                                    {
                                        "id": "evidence",
                                        "header": "复验",
                                        "question": "需要开发 AI 提供复验范围。",
                                        "options": [
                                            {"label": "移动", "description": "只核对安全移动。"},
                                            {"label": "停止", "description": "只核对停止结果。"},
                                        ],
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    }
                else:
                    output = {
                        "id": "message_done",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "contract_done", "annotations": []}],
                    }
                events: list[JsonObject] = [
                    {
                        "type": "response.created",
                        "response": {
                            "id": "response_contract",
                            "object": "response",
                            "status": "in_progress",
                            "output": [],
                        },
                    },
                    {"type": "response.output_item.added", "output_index": 0, "item": output},
                    {"type": "response.output_item.done", "output_index": 0, "item": output},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "response_contract",
                            "object": "response",
                            "status": "completed",
                            "output": [output],
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "total_tokens": 110,
                                "input_tokens_details": {"cached_tokens": 0},
                                "output_tokens_details": {"reasoning_tokens": 0},
                            },
                        },
                    },
                ]
                for event in events:
                    self.wfile.write(
                        ("event: " + cast(str, event["type"]) + "\ndata: " + json.dumps(event) + "\n\n").encode()
                    )
                self.wfile.flush()

        endpoint = ThreadingHTTPServer((gateway, 0), Endpoint)
        worker = Thread(target=endpoint.serve_forever, daemon=True)
        worker.start()
        provider = root / "provider.toml"
        provider.write_text(
            f"""model_provider = "contract"
[features]
enable_request_compression = false
[model_providers.contract]
name = "Only a local contract endpoint"
base_url = "http://{gateway}:{endpoint.server_address[1]}/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
""",
            encoding="utf-8",
        )
        provider.chmod(0o644)  # 此文件没有认证；镜像 UID1000 只读它。
        command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "-i",
            "--name",
            identifier,
            "--network",
            identifier,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--tmpfs",
            "/home/game/.codex:rw,nosuid,nodev,uid=1000,gid=1000,mode=700,size=64m",
            "--mount",
            f"type=bind,src={provider},dst=/run/game-ai/provider.toml,readonly",
            image,
        ]
        server: AppServer | None = None
        try:
            server = await AppServer.start(command, root / "app-server.stderr.log")
            await asyncio.wait_for(
                server.call(
                    "initialize",
                    {
                        "clientInfo": {"name": "game_contract", "version": "0.1"},
                        "capabilities": {"experimentalApi": True},
                    },
                ),
                15,
            )
            await server.notify("initialized", {})
            configuration = cast(JsonObject, await server.call("config/read", {"cwd": "/game", "includeLayers": True}))
            effective = cast(JsonObject, configuration["config"])
            (evidence / "metadata.json").write_text(
                json.dumps(
                    {
                        "project_doc_max_bytes": effective.get("project_doc_max_bytes"),
                        "features": {
                            key: cast(JsonObject, effective.get("features", {})).get(key)
                            for key in (
                                "shell_tool",
                                "apps",
                                "multi_agent",
                                "memories",
                                "goals",
                                "hooks",
                                "plugins",
                                "image_generation",
                                "view_image",
                                "code_mode_host",
                                "sleep_tool",
                                "code_mode_only",
                                "code_mode_only_strict_3p_tools",
                                "default_mode_request_user_input",
                                "code_mode",
                            )
                        },
                        "model_context_window": effective.get("model_context_window"),
                        "model_auto_compact_token_limit": effective.get("model_auto_compact_token_limit"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            skills = cast(JsonObject, await server.call("skills/list", {"cwds": ["/game"], "forceReload": True}))
            self.assertFalse(any(cast(JsonObject, item)["skills"] for item in cast(list[JsonValue], skills["data"])))
            mcps = cast(JsonObject, await server.call("mcpServerStatus/list", {"limit": 100}))
            self.assertEqual([], mcps["data"])
            base_instructions = "GAME_BASE_38：只按游戏事实作决策。"
            developer_instructions = "GAME_ROLE_38：保留养成约束，必要时向开发 AI 询问。"
            tools = GAME_TOOLS
            thread = cast(
                JsonObject,
                await server.call(
                    "thread/start",
                    {
                        "model": "gpt-6-luna",
                        "cwd": "/game",
                        "sandbox": "read-only",
                        "approvalPolicy": "never",
                        "baseInstructions": base_instructions,
                        "developerInstructions": developer_instructions,
                        "dynamicTools": [
                            {"type": "namespace", "name": "game", "description": "专用游戏工具。", "tools": tools}
                        ],
                        "allowProviderModelFallback": False,
                    },
                ),
            )
            self.assertEqual([], thread.get("instructionSources", []))
            thread_id = cast(str, cast(JsonObject, thread["thread"])["id"])
            await server.call(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": "请按给出的受控回复进行协作合同验证，不操作游戏。"}],
                },
            )
            answered = False
            observed = False
            methods: list[str] = []
            tool_events: list[JsonObject] = []
            async with asyncio.timeout(25):
                while True:
                    event = await server.events.get()
                    method = cast(str, event["method"])
                    methods.append(method)
                    if method in {"item/completed", "warning", "configWarning"}:
                        tool_events.append(event)
                        (evidence / "tool-events.json").write_text(
                            json.dumps(tool_events, ensure_ascii=False, indent=2) + "\n"
                        )
                    if method == "item/tool/call":
                        params = cast(JsonObject, event["params"])
                        self.assertEqual(("game", "game_observe"), (params.get("namespace"), params["tool"]))
                        await server.respond(
                            cast(int | str, event["id"]),
                            {"success": True, "contentItems": [{"type": "inputText", "text": "OBSERVE_CONTRACT_38"}]},
                        )
                        observed = True
                    if method == "item/tool/requestUserInput":
                        params = cast(JsonObject, event["params"])
                        self.assertEqual(
                            "evidence", cast(JsonObject, cast(list[JsonValue], params["questions"])[0])["id"]
                        )
                        await server.respond(
                            cast(int | str, event["id"]),
                            {"answers": {"evidence": {"answers": ["DEV_ANSWER_38：仅复验安全移动。"]}}},
                        )
                        answered = True
                    if method == "turn/completed":
                        turn = cast(JsonObject, cast(JsonObject, event["params"])["turn"])
                        self.assertEqual("completed", turn["status"], turn.get("error"))
                        if answered and any(
                            "DEV_ANSWER_38" in json.dumps(request, ensure_ascii=False) for request in requests
                        ):
                            break
                    self.assertNotEqual("transport/closed", method, methods)
            self.assertTrue(observed, methods)
            self.assertTrue(answered, methods)
            resumed = cast(
                JsonObject,
                await server.call(
                    "thread/resume",
                    {
                        "threadId": thread_id,
                        "model": "gpt-6-luna",
                        "cwd": "/game",
                        "baseInstructions": base_instructions,
                        "developerInstructions": developer_instructions,
                        "excludeTurns": True,
                    },
                ),
            )
            self.assertEqual(thread_id, cast(JsonObject, resumed["thread"])["id"])
            await server.call(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": "验证续接后的既有狩猎工具，仅使用本地假结果，不操作游戏。"}],
                },
            )
            hunted = False
            async with asyncio.timeout(25):
                while True:
                    event = await server.events.get()
                    method = cast(str, event["method"])
                    if method == "item/tool/call":
                        params = cast(JsonObject, event["params"])
                        self.assertEqual(("game", "game_hunt"), (params.get("namespace"), params["tool"]))
                        self.assertEqual(
                            {"target": "100100", "skill_id": 1001004, "range": 75, "seconds": 60}, params["arguments"]
                        )
                        await server.respond(
                            cast(int | str, event["id"]),
                            {
                                "success": True,
                                "contentItems": [{"type": "inputText", "text": "HUNT_CONTRACT_86:starting"}],
                            },
                        )
                        hunted = True
                    if method == "turn/completed":
                        turn = cast(JsonObject, cast(JsonObject, event["params"])["turn"])
                        self.assertEqual("completed", turn["status"], turn.get("error"))
                        break
                    self.assertNotEqual("transport/closed", method)
            self.assertTrue(hunted)
            self.assertGreaterEqual(len(requests), 3)
            self.assertTrue(
                any("OBSERVE_CONTRACT_38" in json.dumps(request, ensure_ascii=False) for request in requests[1:])
            )
            tool_outputs: list[str] = []
            for request in requests[1:]:
                for item in cast(list[JsonValue], request.get("input", [])):
                    result = cast(JsonObject, item)
                    if result.get("type") == "custom_tool_call_output":
                        output = result["output"]
                        if isinstance(output, str):
                            tool_outputs.append(output)
                        else:
                            tool_outputs.extend(
                                cast(str, cast(JsonObject, part)["text"]) for part in cast(list[JsonValue], output)
                            )
            registry = next(
                (
                    re.search(r"AVAILABLE_TOOLS_38=(\[[^\n]*\])", output)
                    for output in tool_outputs
                    if "AVAILABLE_TOOLS_38=" in output
                ),
                None,
            )
            self.assertIsNotNone(registry, "exec 未返回实际可调用工具清单。")
            available_tools = cast(list[str], json.loads(cast(re.Match[str], registry).group(1)))
            self.assertEqual(
                {"game__game_observe", "game__game_run_lua", "game__game_script_status", "game__game_hunt"},
                set(available_tools),
            )
            resumed_registry = next(
                re.search(r"RESUMED_TOOLS_86=(\[[^\n]*\])", output)
                for output in tool_outputs
                if "RESUMED_TOOLS_86=" in output
            )
            self.assertIsNotNone(resumed_registry)
            self.assertEqual(set(available_tools), set(json.loads(cast(re.Match[str], resumed_registry).group(1))))
            first = requests[0]
            prompt = json.dumps(first.get("input"), ensure_ascii=False) + str(first.get("instructions", ""))
            self.assertTrue(base_instructions in prompt, "自定义游戏基础指令未进入请求。")
            self.assertTrue(developer_instructions in prompt, "自定义角色约束未进入请求。")
            for inherited in (
                "You are Codex",
                "# General Principles",
                "### Available skills",
                "AGENTS.md instructions for",
            ):
                self.assertFalse(inherited in prompt, "请求含未授权的开发指令标记：" + inherited)
            offered = cast(list[JsonValue], first.get("tools", []))
            for item in cast(list[JsonValue], first.get("input", [])):
                block = cast(JsonObject, item)
                if block.get("type") == "additional_tools":
                    offered = [*offered, *cast(list[JsonValue], block["tools"])]
            names: set[str] = set()
            description_bytes: dict[str, int] = {}
            for entry in offered:
                tool = cast(JsonObject, entry)
                if tool.get("type") == "namespace":
                    for child in cast(list[JsonValue], tool["tools"]):
                        function = cast(JsonObject, child)
                        names.add(cast(str, function["name"]))
                        description_bytes[str(tool["name"]) + "." + str(function["name"])] = len(
                            cast(str, function.get("description", "")).encode()
                        )
                else:
                    names.add(cast(str, tool["name"]))
                    description_bytes[cast(str, tool["name"])] = len(cast(str, tool.get("description", "")).encode())
            callable_names = set(names)
            for entry in offered:
                tool = cast(JsonObject, entry)
                children = cast(list[JsonValue], tool["tools"]) if tool.get("type") == "namespace" else [tool]
                for child in children:
                    function = cast(JsonObject, child)
                    if function["name"] == "exec":
                        callable_names.update(re.findall(r"### `([^`]+)`", cast(str, function.get("description", ""))))
            (evidence / "surface.json").write_text(
                json.dumps(
                    {
                        "tool_names": sorted(names),
                        "callable_names": sorted(callable_names),
                        "request_paths": request_paths,
                        "model": first["model"],
                        "scenario": "synthetic contract; no real model or game",
                        "tool_description_bytes": description_bytes,
                        "request_body_bytes": request_sizes[0],
                        "input_serialized_bytes": len(json.dumps(first.get("input", []), ensure_ascii=False).encode()),
                        "tool_definitions_serialized_bytes": len(json.dumps(offered, ensure_ascii=False).encode()),
                        "developer_messages_serialized_bytes": sum(
                            len(json.dumps(item, ensure_ascii=False).encode())
                            for item in cast(list[JsonValue], first.get("input", []))
                            if cast(JsonObject, item).get("role") == "developer"
                            and cast(JsonObject, item).get("type") != "additional_tools"
                        ),
                        "instruction_sources": thread.get("instructionSources", []),
                        "developer_inputs": [
                            item
                            for item in cast(list[JsonValue], first.get("input", []))
                            if cast(JsonObject, item).get("role") == "developer"
                            and cast(JsonObject, item).get("type") != "additional_tools"
                        ],
                        "question_answer_round_trip": answered,
                        "runtime_available_tools": available_tools,
                        "game_observe_dispatch": observed,
                        "resumed_game_hunt_dispatch": hunted,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            actual_functions = {name.removeprefix("game__") for name in callable_names}
            self.assertTrue(
                {"request_user_input", "game_observe", "game_run_lua", "game_script_status", "game_hunt"}.issubset(
                    actual_functions
                ),
                actual_functions,
            )
            self.assertTrue(
                actual_functions.issubset(
                    {
                        "exec",
                        "wait",
                        "request_user_input",
                        "request_user_input_async",
                        "game_observe",
                        "game_run_lua",
                        "game_script_status",
                        "game_hunt",
                    }
                ),
                actual_functions,
            )
            self.assertTrue(any("DEV_ANSWER_38" in json.dumps(request, ensure_ascii=False) for request in requests[1:]))
        finally:
            if server is not None:
                closing = asyncio.create_task(server.close())
                try:
                    await asyncio.wait_for(asyncio.shield(closing), 10)
                except TimeoutError:
                    subprocess.run(["docker", "stop", "--time", "5", identifier], check=True, capture_output=True)
                    await closing
            endpoint.shutdown()
            endpoint.server_close()
            worker.join()
            subprocess.run(["docker", "network", "rm", network_id], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
