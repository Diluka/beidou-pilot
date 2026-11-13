"""通过本地文件协议观察并控制当前游戏进程内的原生桥。"""

from contextlib import AbstractContextManager, contextmanager, nullcontext
import fcntl
import json
import math
from pathlib import Path
import re
import time
from typing import Iterator, Literal, NotRequired, TypedDict, cast
import uuid

from .errors import ClientError, JsonObject
from .runtime import load_runtime
from .strategies import TickGear, parse_script_execution


# 脚本可持续执行，原更新停止采样仍须有界发现并进入停止收尾。
CONTINUOUS_STATE_MAX_AGE = 5.0


class BridgeCharacter(TypedDict):
    id: int
    name: str
    level: int
    job: int
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    strength: int
    dexterity: int
    intelligence: int
    luck: int
    ability_points: int
    skill_points: int
    experience: int


class BridgePosition(TypedDict):
    x: float
    y: float


class BridgeCommand(TypedDict):
    id: str | None
    status: Literal["idle", "running", "completed", "cancelled", "rejected"]
    reason: str | None


class RejectedCommand(TypedDict):
    id: str
    status: Literal["rejected"]
    reason: str


class BridgeTask(TypedDict):
    name: str
    revision: NotRequired[int]
    priority: int
    status: Literal["running", "waiting", "completed", "cancelled"]
    wait: Literal["none", "sleep", "action", "raw_keys", "release", "control"]
    reason: str | None
    error: str | None


BridgeControl = TypedDict("BridgeControl", {
    "owner": str | None,
    "pending": str | None,
    "from": str | None,
    "to": str | None,
    "reason": str | None,
})


class BridgeTick(TypedDict):
    index: int
    gear: TickGear
    time: float
    delta: float
    scene_generation: int
    overrun: bool
    budget_ms: float
    overrun_policy: Literal["abort", "skip"]
    abort_commit: bool
    overruns: int


class BridgePlayer(TypedDict):
    moving: Literal["left", "right", "up", "down"] | None
    action: str | None
    phase: Literal["idle", "running", "releasing"]
    busy: bool
    held: list[str]
    pending_action: str | None
    reason: str
    effect: str
    dispatched: bool
    control_released: bool
    skill_id: NotRequired[int]
    item_id: NotRequired[int]


class BridgeScript(TypedDict):
    id: str
    status: Literal["running", "completed", "cancelled", "rejected"]
    reason: str | None
    error: str | None
    resumes: int
    budget_yields: int
    last_resume_us: float
    max_resume_us: float
    tasks: NotRequired[list[BridgeTask]]
    control: NotRequired[BridgeControl]
    mode: NotRequired[Literal["coroutine", "tick"]]
    control_released: NotRequired[bool]
    tick: NotRequired[BridgeTick]
    player: NotRequired[BridgePlayer]


class BridgeMonster(TypedDict):
    object_id: int
    template_id: int | None
    name: str | None
    x: float
    y: float
    active: bool
    hp_percent: NotRequired[int | None]
    hp_sequence: NotRequired[int | None]
    hp_source: NotRequired[str | None]


class NativeSkillResult(TypedDict):
    skill_id: int
    native_result: int
    dispatched: NotRequired[bool]
    reason: NotRequired[str | None]


class BridgeSnapshot(TypedDict):
    protocol: Literal[1]
    instance_id: str
    pid: int
    run_id: str
    seq: int
    observed_at_ms: int
    scene_generation: int
    ready: bool
    map_id: int | None
    character: BridgeCharacter | None
    position: BridgePosition | None
    held_keys: list[int]
    command: BridgeCommand
    rejected_command: RejectedCommand | None
    input_events: int
    script: NotRequired[BridgeScript | None]
    scripts: NotRequired[list[BridgeScript]]
    last_skill: NotRequired[NativeSkillResult | None]
    monsters: NotRequired[list[BridgeMonster] | None]
    capabilities: NotRequired[dict[str, bool] | None]
    held_actions: NotRequired[list[str]]
    facing: NotRequired[Literal["Left", "Right"] | None]
    dead: NotRequired[bool | None]
    revive_requestable: NotRequired[bool | None]


def script_by_id(state: BridgeSnapshot, script_id: str) -> BridgeScript | None:
    """新桥按会话数组定位；旧桥只暴露当前单会话。"""
    if "scripts" in state:
        return next((script for script in state["scripts"] if script["id"] == script_id), None)
    script = state.get("script")
    return script if script is not None and script["id"] == script_id else None


def _validate_script(script: object, *, require_mode: bool = False) -> None:
    if (not isinstance(script, dict) or not isinstance(script.get("id"), str)
            or script.get("status") not in ("running", "completed", "cancelled", "rejected")
            or any(field not in script or (script[field] is not None and not isinstance(script[field], str))
                   for field in ("reason", "error"))
            or any(type(script.get(field)) is not int or script[field] < 0
                   for field in ("resumes", "budget_yields"))
            or any(type(script.get(field)) not in (int, float) or not math.isfinite(script[field])
                   or script[field] < 0 for field in ("last_resume_us", "max_resume_us"))
            or ((require_mode or "mode" in script) and script.get("mode") not in ("coroutine", "tick"))
            or ("control_released" in script and type(script["control_released"]) is not bool)):
        raise ClientError("invalid_bridge_state", "原生桥的脚本执行状态字段无效。")
    if "tasks" in script:
        tasks = script["tasks"]
        if (not isinstance(tasks, list) or any(not isinstance(task, dict)
                or not isinstance(task.get("name"), str) or not task["name"]
                or ("revision" in task and (type(task["revision"]) is not int or task["revision"] <= 0))
                or type(task.get("priority")) is not int or not -0x80000000 <= task["priority"] <= 0x7FFFFFFF
                or task.get("status") not in ("running", "waiting", "completed", "cancelled")
                or task.get("wait") not in ("none", "sleep", "action", "raw_keys", "release", "control")
                or any(field not in task or (task[field] is not None and not isinstance(task[field], str))
                       for field in ("reason", "error")) for task in tasks)):
            raise ClientError("invalid_bridge_state", "原生桥的Lua任务状态字段无效。")
    if "control" in script:
        control = script["control"]
        if (not isinstance(control, dict) or any(field not in control
                or (control[field] is not None and not isinstance(control[field], str))
                for field in ("owner", "pending", "from", "to", "reason"))):
            raise ClientError("invalid_bridge_state", "原生桥的Lua控制权字段无效。")
    if script.get("mode") == "tick":
        tick, player = script.get("tick"), script.get("player")
        if (not isinstance(tick, dict)
                or type(tick.get("gear")) is not int or tick["gear"] not in (1, 2, 3, 4)
                or any(type(tick.get(field)) is not int or tick[field] < 0
                       for field in ("index", "scene_generation", "overruns"))
                or any(type(tick.get(field)) not in (int, float) or not math.isfinite(tick[field])
                       or tick[field] < 0 for field in ("time", "delta", "budget_ms"))
                or tick["budget_ms"] <= 0 or tick.get("overrun_policy") not in ("abort", "skip")
                or any(type(tick.get(field)) is not bool for field in ("overrun", "abort_commit"))
                or type(script.get("control_released")) is not bool):
            raise ClientError("invalid_bridge_state", "原生桥的tick调度字段无效。")
        if (not isinstance(player, dict) or player.get("phase") not in ("idle", "running", "releasing")
                or "moving" not in player or player["moving"] not in (None, "left", "right", "up", "down")
                or any(field not in player or player[field] is not None and not isinstance(player[field], str)
                       for field in ("action", "pending_action"))
                or any(not isinstance(player.get(field), str) for field in ("reason", "effect"))
                or any(type(player.get(field)) is not bool for field in ("busy", "dispatched", "control_released"))
                or any(field in player and (type(player[field]) is not int or not 1 <= player[field] <= 0x7FFFFFFF)
                       for field in ("skill_id", "item_id"))
                or not isinstance(player.get("held"), list)
                or any(key not in ("left", "right", "up", "down", "jump", "attack", "pickup")
                       for key in player["held"])):
            raise ClientError("invalid_bridge_state", "原生桥的tick角色操作状态字段无效。")


class BridgeClient:
    def __init__(self, client_root: Path, backend: str = "beidou", instance: str = "default") -> None:
        from .instances import InstancePaths

        self.root = client_root.resolve()
        self.backend = backend
        self.instance = instance
        paths = InstancePaths(self.root, backend, instance)
        self.directory = paths.bridge

    def snapshot(self, max_age: float = 1.0) -> BridgeSnapshot:
        """只读当前登记会话的新鲜采样；文件存在不能证明桥已就绪。"""
        if not math.isfinite(max_age) or not max_age > 0:
            raise ClientError("invalid_bridge_options", "桥接快照有效期须大于0秒。")
        runtime = load_runtime(self.root, self.backend, self.instance)
        if not runtime.running:
            raise ClientError("bridge_session_unavailable", "本容器的客户端进程已退出。")
        try:
            raw = json.loads((self.directory / "state.json").read_text())
        except OSError as error:
            raise ClientError("bridge_unavailable", "无法读取本容器的原生桥。",
                              {"reason": str(error)}) from error
        except json.JSONDecodeError as error:
            raise ClientError("invalid_bridge_state", "原生桥不是有效JSON。",
                              {"reason": error.msg}) from error
        if (not isinstance(raw, dict) or type(raw.get("protocol")) is not int or raw["protocol"] != 1
                or not isinstance(raw.get("instance_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]+", raw["instance_id"])
                or not isinstance(raw.get("run_id"), str)
                or any(type(raw.get(field)) is not int for field in
                       ("pid", "seq", "observed_at_ms", "scene_generation", "input_events"))
                or raw["pid"] <= 0 or min(raw["seq"], raw["scene_generation"], raw["input_events"]) < 0
                or type(raw.get("ready")) is not bool
                or "map_id" not in raw or (raw["map_id"] is not None and type(raw["map_id"]) is not int)
                or "character" not in raw or "position" not in raw
                or "rejected_command" not in raw
                or not isinstance(raw.get("held_keys"), list)
                or any(type(key) is not int or not 1 <= key <= 255 for key in raw["held_keys"])
                or not isinstance(raw.get("command"), dict)):
            raise ClientError("invalid_bridge_state", "原生桥的协议、身份或状态字段无效。")
        if any(raw.get(field) is not None and type(raw[field]) is not bool
               for field in ("dead", "revive_requestable")):
            raise ClientError("invalid_bridge_state", "原生死亡观察字段无效。")
        command = raw["command"]
        character, position, rejected = raw["character"], raw["position"], raw["rejected_command"]
        if ("id" not in command or (command["id"] is not None and not isinstance(command["id"], str))
                or command.get("status") not in ("idle", "running", "completed", "cancelled", "rejected")
                or "reason" not in command
                or (command["reason"] is not None and not isinstance(command["reason"], str))
                or (rejected is not None and (not isinstance(rejected, dict)
                    or not isinstance(rejected.get("id"), str) or rejected.get("status") != "rejected"
                    or not isinstance(rejected.get("reason"), str)))
                or (position is not None and (not isinstance(position, dict)
                    or any(type(position.get(field)) not in (int, float) or not math.isfinite(position[field])
                           for field in ("x", "y"))))
                or (character is not None and (not isinstance(character, dict)
                    or not isinstance(character.get("name"), str)
                    or any(type(character.get(field)) is not int for field in
                           ("id", "level", "job", "hp", "max_hp", "mp", "max_mp", "strength",
                            "dexterity", "intelligence", "luck", "ability_points", "skill_points", "experience"))))):
            raise ClientError("invalid_bridge_state", "原生桥的角色、坐标或命令结果字段无效。")
        if "script" in raw and raw["script"] is not None:
            _validate_script(raw["script"])
        if "scripts" in raw:
            if not isinstance(raw["scripts"], list):
                raise ClientError("invalid_bridge_state", "原生桥的脚本会话列表无效。")
            for script in raw["scripts"]:
                _validate_script(script, require_mode=True)
            ids = [script["id"] for script in raw["scripts"]]
            if len(ids) != len(set(ids)):
                raise ClientError("invalid_bridge_state", "原生桥的脚本会话ID重复。")
        if "last_skill" in raw and raw["last_skill"] is not None:
            skill = raw["last_skill"]
            if not isinstance(skill, dict) or any(type(skill.get(field)) is not int
                                                  for field in ("skill_id", "native_result")) or (
                    "dispatched" in skill and type(skill["dispatched"]) is not bool) or (
                    "reason" in skill and skill["reason"] is not None and not isinstance(skill["reason"], str)):
                raise ClientError("invalid_bridge_state", "原生桥的技能调用结果字段无效。")
        if "capabilities" in raw and raw["capabilities"] is not None and (
                not isinstance(raw["capabilities"], dict)
                or any(type(value) is not bool for value in raw["capabilities"].values())):
            raise ClientError("invalid_bridge_state", "原生桥的能力声明字段无效。")
        if "facing" in raw and raw["facing"] not in ("Left", "Right", None):
            raise ClientError("invalid_bridge_state", "原生桥的角色朝向字段无效。")
        if "monsters" in raw and raw["monsters"] is not None:
            monsters = raw["monsters"]
            if (not isinstance(monsters, list) or any(not isinstance(monster, dict)
                    or type(monster.get("object_id")) is not int
                    or any(type(monster.get(field)) not in (int, float) or not math.isfinite(monster[field])
                           for field in ("x", "y"))
                    or "template_id" not in monster
                    or (monster["template_id"] is not None and type(monster["template_id"]) is not int)
                    or "name" not in monster or (monster["name"] is not None and not isinstance(monster["name"], str))
                    or type(monster.get("active")) is not bool for monster in monsters)):
                raise ClientError("invalid_bridge_state", "原生桥的怪物观察字段无效。")
        if "held_actions" in raw and (not isinstance(raw["held_actions"], list)
                or any(not isinstance(action, str) for action in raw["held_actions"])):
            raise ClientError("invalid_bridge_state", "原生桥的语义输入状态字段无效。")
        for monster in raw.get("monsters") or []:
            percent, sequence, source = (monster.get(field) for field in ("hp_percent", "hp_sequence", "hp_source"))
            if (percent is not None and (type(percent) is not int or not 0 <= percent <= 100)
                    or sequence is not None and (type(sequence) is not int or sequence < 0)
                    or source is not None and not isinstance(source, str)):
                raise ClientError("invalid_bridge_state", "原生桥的目标HP观察字段无效。")
        state = cast(BridgeSnapshot, raw)
        if state["run_id"] != runtime.run_id:
            raise ClientError("bridge_session_mismatch", "原生桥快照不属于当前登记的客户端会话。")
        age = time.time() - state["observed_at_ms"] / 1000
        if not 0 <= age <= max_age:
            raise ClientError("stale_bridge_state", "原生桥快照已过期或采样时间无效。",
                              {"age_seconds": round(age, 4), "max_age_seconds": max_age})
        return state

    @contextmanager
    def _control(self) -> Iterator[None]:
        try:
            handle = (self.directory / "control.lock").open("a")
        except OSError as error:
            raise ClientError("bridge_unavailable", "无法取得原生桥命令文件的控制权。",
                              {"reason": str(error)}) from error
        with handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ClientError("input_busy", "另一个命令正在控制原生桥。") from error
            yield

    def _publish(self, state: BridgeSnapshot, action: str, argument: int, values: list[str]) -> str:
        request_id = uuid.uuid4().hex
        line = " ".join(map(str, (1, state["instance_id"], state["scene_generation"],
                                  request_id, action, argument, *values))) + "\n"
        temporary = self.directory / ("command-" + request_id + ".tmp")
        try:
            with temporary.open("x", encoding="ascii") as handle:
                handle.write(line)
            temporary.replace(self.directory / "command.txt")
        except OSError as error:
            raise ClientError("bridge_command_write_failed", "无法原子发布原生桥命令；未自动重放。",
                              {"request_id": request_id, "reason": str(error)}) from error
        return request_id

    def _wait(self, before: BridgeSnapshot, request_id: str, timeout: float | None,
              cancel_file: Path | None = None, poll_interval: float = 0.01,
              wait_for_start: bool = False, script_id: str | None = None) -> BridgeSnapshot | None:
        until = time.monotonic() + timeout if timeout is not None else None
        max_age = (max(0, time.time() - before["observed_at_ms"] / 1000) + timeout + 1
                   if timeout is not None else CONTINUOUS_STATE_MAX_AGE)
        while True:
            # 换图加载会暂停原更新；继续等本请求的新序号，仍受总期限限制。
            state = self.snapshot(max_age=max_age)
            if state["instance_id"] != before["instance_id"]:
                raise ClientError("bridge_identity_changed", "原生桥进程实例已变化，旧动作结果未确认。",
                                  {"request_id": request_id})
            command = state["command"]
            rejected = state["rejected_command"]
            if state["seq"] > before["seq"] and (
                    (rejected is not None and rejected["id"] == request_id)
                    or (command["id"] == request_id and command["status"] == "rejected")):
                details: JsonObject = {"request_id": request_id,
                                       "reason": rejected["reason"] if rejected is not None and rejected["id"] == request_id
                                       else command["reason"], "held_keys": state["held_keys"]}
                if "script" in state:
                    details["script"] = cast(JsonObject | None, state["script"])
                raise ClientError("bridge_command_rejected", "原生桥拒绝了本次请求。", details)
            script = script_by_id(state, script_id) if script_id is not None else None
            if state["seq"] > before["seq"]:
                if script_id is not None and script is not None:
                    if (script["status"] != "running"
                            or wait_for_start and (script["error"] is None or script.get("mode") == "tick")):
                        return state
                elif (script_id is None and command["id"] == request_id
                      and (command["status"] in ("completed", "cancelled")
                           or wait_for_start and command["status"] == "running"
                           and state.get("script") is not None and state["script"]["error"] is None)):
                    return state
            if cancel_file is not None and cancel_file.exists():
                return None
            if until is not None and time.monotonic() >= until:
                raise ClientError("bridge_timeout", "未在期限内确认原生桥命令状态。",
                                  {"request_id": request_id, "script_id": script_id,
                                   "last_status": script["status"] if script is not None else command["status"],
                                   "held_keys": state["held_keys"]})
            time.sleep(poll_interval)

    def _stop(self, before: BridgeSnapshot, timeout: float) -> BridgeSnapshot:
        # 清理始终绑定原进程实例；换图后的同一实例仍可释放按键。
        request_id = self._publish(before, "stop", 0, [])
        state = self._wait(before, request_id, timeout)
        assert state is not None  # stop不传取消标记，等待不会以取消请求返回。
        script = state.get("script")
        if (state["command"]["status"] != "completed" or state["held_keys"]
                or (script is not None and script["status"] == "running")
                or any(item["status"] == "running" for item in state.get("scripts", []))):
            raise ClientError("bridge_release_unconfirmed", "原生桥尚未确认停止脚本并释放全部按键。",
                              {"request_id": request_id, "status": state["command"]["status"],
                               "reason": state["command"]["reason"], "held_keys": state["held_keys"],
                               "script_status": script["status"] if script is not None else None})
        return state

    def _ready_state(self, mode: Literal["coroutine", "tick"] = "coroutine") -> BridgeSnapshot:
        state = self.snapshot()
        if not state["ready"]:
            raise ClientError("bridge_not_ready", "原生桥当前没有可操作的游戏角色。")
        if "scripts" in state:
            if mode == "coroutine" and any(item["status"] == "running" and item["mode"] == "coroutine"
                                          for item in state["scripts"]):
                raise ClientError("input_busy", "coroutine引擎仍有活动脚本会话。")
        elif state["command"]["status"] == "running" or state["held_keys"]:
            raise ClientError("input_busy", "原生桥仍有未完成动作或未释放按键。")
        return state

    def _execute(self, before: BridgeSnapshot, action: str, argument: int, values: list[str],
                 timeout: float | None, cancel_file: Path | None = None,
                 poll_interval: float = 0.01,
                 wait_for_start: bool = False, script_id: str | None = None) -> tuple[BridgeSnapshot, str | None, bool]:
        if cancel_file is not None and cancel_file.exists():
            return before, None, True
        request_id = self._publish(before, action, argument, values)
        # 等待进程不拥有原生任务；中断或观察失败不改变已发布任务。
        result = self._wait(before, request_id, timeout, cancel_file, poll_interval, wait_for_start, script_id)
        if (result is not None and "scripts" not in result
                and result["held_keys"] and result["command"]["status"] != "running"):
            raise ClientError("bridge_release_unconfirmed", "动作已结束，但原生桥按键尚未释放。",
                              {"request_id": request_id, "held_keys": result["held_keys"]})
        if result is None:
            state, _ = self._cancel(before, script_id, 2)
            return state, request_id, True
        return result, request_id, False

    def run_script(self, path: Path | None = None, seconds: float | None = 30, timeout: float | None = None,
                   cancel_file: Path | None = None, *, code: str | None = None,
                   wait_for_start: bool = False,
                   admission_control: AbstractContextManager[None] | None = None) -> JsonObject:
        """执行受信Lua；锁只保护发布/受理，终态等待不拥有原生会话。"""
        if (path is None) == (code is None):
            raise ClientError("invalid_bridge_options", "Lua文件与直接源码须且只能提供一项。")
        if (seconds is not None and not 0.001 <= seconds <= 0xFFFFFFFF / 1000
                or timeout is not None and (not math.isfinite(timeout) or not timeout > 0)):
            raise ClientError("invalid_bridge_options", "脚本时限须为正数且不超过4294967.295秒；持续执行使用None。")
        try:
            source = path.read_bytes() if path is not None else cast(str, code).encode("utf-8")
            execution = parse_script_execution(source.decode("utf-8"))
        except (OSError, UnicodeError) as error:
            raise ClientError("invalid_script_file" if path is not None else "invalid_script_source",
                              "无法准备UTF-8 Lua脚本，未发布执行请求。",
                              {"path": str(path) if path is not None else None, "reason": str(error)}) from error
        started = time.monotonic()
        wait_seconds = timeout
        if wait_seconds is None:
            wait_seconds = 3 if wait_for_start else seconds + 2 if seconds is not None else None
        with admission_control or nullcontext(), self._control():
            before = self._ready_state(execution.mode)
            if "script" not in before:
                raise ClientError("bridge_script_unsupported", "当前DLL未提供Lua脚本能力，未发布脚本请求。")
            if execution.mode == "tick" and "scripts" not in before:
                raise ClientError("bridge_tick_unsupported", "当前原生桥未提供tick引擎，未发布或回退到旧引擎。")
            script_id = uuid.uuid4().hex
            try:
                scripts = self.directory / "scripts"
                scripts.mkdir(mode=0o700, exist_ok=True)
                temporary = scripts / (script_id + ".tmp")
                with temporary.open("xb") as handle:
                    handle.write(source)
                temporary.replace(scripts / (script_id + ".lua"))
            except OSError as error:
                raise ClientError("invalid_script_file" if path is not None else "invalid_script_source",
                                  "无法准备UTF-8 Lua脚本，未发布执行请求。",
                                  {"path": str(path) if path is not None else None, "reason": str(error)}) from error
            state, request_id, locally_cancelled = self._execute(
                before, "script", round(seconds * 1000) if seconds is not None else 0,
                [script_id], min(wait_seconds, 3) if wait_seconds is not None else 3,
                cancel_file, poll_interval=0.05, wait_for_start=True, script_id=script_id)
        script = script_by_id(state, script_id) if request_id is not None else None
        if not wait_for_start and not locally_cancelled and script is not None and script["status"] == "running":
            remaining = max(0, wait_seconds - (time.monotonic() - started)) if wait_seconds is not None else None
            result = self._wait(before, cast(str, request_id), remaining, cancel_file,
                                poll_interval=0.05, script_id=script_id)
            if result is None:
                with self._control():
                    state, _ = self._cancel(self.snapshot(), script_id, 2)
                locally_cancelled = True
            else:
                state = result
            script = script_by_id(state, script_id)
        if request_id is not None and script is None:
            raise ClientError("invalid_bridge_state", "脚本状态与本次脚本身份不符。",
                              {"request_id": request_id, "script_id": script_id})
        if script is not None and script["status"] != "running":
            released = script.get("control_released") if "scripts" in state else not state["held_keys"]
            if released is not True:
                raise ClientError("bridge_release_unconfirmed", "脚本已结束，但所属输入释放尚未确认。",
                                  {"request_id": request_id, "script_id": script_id,
                                   "held_keys": state["held_keys"], "script": cast(JsonObject, script)})
        cancelled = locally_cancelled or script is not None and script["status"] == "cancelled"
        report: JsonObject = {
            "source": "client-native-bridge", "instance_id": state["instance_id"], "run_id": state["run_id"],
            "request_id": request_id, "script_id": script_id, "mode": execution.mode,
            "script_file": str(path) if path is not None else None, "seconds": seconds, "continuous": seconds is None,
            "status": "cancelled" if cancelled else script["status"] if script is not None else state["command"]["status"],
            "cancelled": cancelled,
            "reason": "cancel_requested" if locally_cancelled else script["reason"] if script is not None else None,
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "script": cast(JsonObject | None, script), "last_state": cast(JsonObject, state),
        }
        if script is not None and script["error"] is not None:
            message = ("已受理Lua会话报告错误，尚在结束收尾；请按script_id观察终态及输入释放。"
                       if script["status"] == "running" else "原生Lua脚本执行失败，脚本已停止并释放所属输入。")
            raise ClientError("bridge_script_error", message, report)
        return report

    def _cancel(self, before: BridgeSnapshot, script_id: str | None, timeout: float) -> tuple[BridgeSnapshot, str]:
        if "scripts" not in before or script_id is None:
            state = self._stop(before, timeout)
            return state, cast(str, state["command"]["id"])
        request_id = self._publish(before, "cancel_script", 0, [script_id])
        state = self._wait(before, request_id, timeout, script_id=script_id)
        assert state is not None
        script = script_by_id(state, script_id)
        if script is None or script["status"] == "running" or script.get("control_released") is not True:
            raise ClientError("bridge_release_unconfirmed", "目标脚本尚未确认停止并释放所属输入。",
                              {"request_id": request_id, "script_id": script_id,
                               "held_keys": state["held_keys"], "script": cast(JsonObject | None, script)})
        return state, request_id

    def cancel_script(self, script_id: str, timeout: float = 2.0, *,
                      admission_control: AbstractContextManager[None] | None = None) -> JsonObject:
        """只取消匹配的Lua会话；其他会话持键不影响目标的释放确认。"""
        if not re.fullmatch(r"[0-9a-fA-F]{32}", script_id) or not math.isfinite(timeout) or timeout <= 0:
            raise ClientError("invalid_bridge_options", "取消须指定script status中的脚本ID与正数等待期限。")
        with admission_control or nullcontext(), self._control():
            before = self.snapshot()
            script = script_by_id(before, script_id)
            if script is None:
                current = before.get("script")
                raise ClientError("script_session_mismatch", "当前Lua会话与指定脚本不符，未发送取消。",
                                  {"script_id": script_id,
                                   "current_script_id": current["id"] if current is not None else None})
            released = (script.get("control_released") if "scripts" in before
                        else before["command"]["status"] != "running" and not before["held_keys"])
            already_stopped = script["status"] != "running" and released is True
            state, request_id = (before, None) if already_stopped else self._cancel(before, script_id, timeout)
            return {"source": "client-native-bridge", "instance_id": state["instance_id"], "run_id": state["run_id"],
                    "request_id": request_id, "script_id": script_id,
                    "status": "already_stopped" if already_stopped else "cancelled", "already_stopped": already_stopped,
                    "control_released": True, "script": cast(JsonObject | None, script_by_id(state, script_id)),
                    "held_keys": state["held_keys"], "last_state": cast(JsonObject, state)}

    def stop(self, timeout: float = 2.0) -> JsonObject:
        """释放当前实例的桥接按键；不会向后继游戏进程补发旧停止请求。"""
        if not math.isfinite(timeout) or not timeout > 0:
            raise ClientError("invalid_bridge_options", "停止等待期限须大于0秒。")
        with self._control():
            state = self._stop(self.snapshot(), timeout)
            return {"source": "client-native-bridge", "request_id": state["command"]["id"],
                    "status": "completed", "held_keys": [], "last_state": cast(JsonObject, state)}
