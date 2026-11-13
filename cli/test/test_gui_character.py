"""GUI 建角离线合同：原生桥动作、页面识别、外观轮转与结果核验。

只使用临时目录和测试内构造的假桥，不接触真实客户端、账号或网络。
"""

from dataclasses import replace
import fcntl
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from beidou_pilot.errors import ClientError
from beidou_pilot.gui_character import (
    _appearance_step,
    _apply_appearance,
    _creation_window,
    _final_state,
    _navigate_category,
    _open_creation,
    _set_gender,
    _submit_creation,
    _submit_name,
    _wait_creation_result,
    create_once,
    identify_creation_page,
    mark_final_submit,
    observe_result,
    persist_result,
    plan_observed_appearance_step,
    query_result,
    record_attempt,
    record_final_dispatch,
    require_supported_creation,
    validate_appearance_transition,
    verify_created_character,
)
from beidou_pilot.profile import CharacterCreation


INSTANCE = "instance"
RUN = "run"
ADDRESS = "0x1234"
PANEL_ADDRESS = "0x1111"
CATEGORY_ADDRESS = "0x2222"
NAME_ADDRESS = "0x3333"
RAW = [21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005]
PARAMS = CharacterCreation("Example", 1, *RAW, True)

CATEGORY_SIGNATURE = ["0xaf7360", "0xaf7314", "0xaf7310"]
NAME_SIGNATURE = ["0xaf7564", "0xaf7518", "0xaf7514"]
APPEARANCE_SIGNATURE = ["0xaf777c", "0xaf7730", "0xaf772c"]
CREATE_PANEL_SIGNATURE = ["0xaf6d90", "0xaf6d44", "0xaf6d40"]
PAGE_SHAPES = {
    "category": (CATEGORY_SIGNATURE, 700, 460),
    "name": (NAME_SIGNATURE, 201, 224),
    "appearance": (APPEARANCE_SIGNATURE, 225, 377),
}


def page_window(page, *, address=ADDRESS, width=None, height=None, **fields):
    signature, expected_width, expected_height = PAGE_SHAPES[page]
    return {
        "address": address,
        "vtables": list(signature),
        "width": expected_width if width is None else width,
        "height": expected_height if height is None else height,
        **fields,
    }


def create_panel(*, address=PANEL_ADDRESS, width=101, height=131):
    return {"address": address, "vtables": list(CREATE_PANEL_SIGNATURE), "width": width, "height": height}


def appearance_window(*, address=ADDRESS, raw=None, job=1, selector=1, buttons=None):
    return page_window(
        "appearance",
        address=address,
        raw_appearance_candidates=list(RAW if raw is None else raw),
        raw_job_candidate=job,
        raw_appearance_selector=selector,
        buttons=[{"control_id": 1000, "enabled": True}] if buttons is None else buttons,
    )


def stage(
    windows=(),
    *,
    characters=(),
    raw_step=2,
    stage_name="CHARACTER_SELECT",
    login=None,
    instance=INSTANCE,
    run=RUN,
    unavailable=(),
):
    login_state = {
        "characters_available": True,
        "request_pending": False,
        "transition_pending": False,
        "characters": list(characters),
        "raw_step": raw_step,
    }
    if login is not None:
        login_state.update(login)
    return {
        "instance_id": instance,
        "client": {"run_id": run},
        "unavailable": list(unavailable),
        "stage": stage_name,
        "login": login_state,
        "windows": list(windows),
    }


def attempt_identity(record):
    return {"request_id": record["request_id"], "instance_id": INSTANCE, "run_id": RUN}


class FakeNativeBridge:
    """只记录原生动作并返回测试构造的快照；不读写真实桥目录。"""

    def __init__(self, directory):
        self.directory = directory
        self.calls: list[tuple[object, ...]] = []
        self.snapshot_state = {
            "instance_id": INSTANCE,
            "run_id": RUN,
            "scripts": [],
            "command": {"status": "idle"},
            "held_keys": [],
        }
        self.on_action = None
        self.rejected_actions: set[str] = set()

    def snapshot(self):
        return self.snapshot_state

    def login_action(self, action, *arguments, timeout=2.0):
        self.calls.append((action, *arguments))
        if action in self.rejected_actions:
            raise ClientError("gui_native_action_rejected", "原生桥拒绝了测试动作。", {"action": action})
        if self.on_action is not None:
            self.on_action(action, *arguments)
        return {
            "protocol": 1,
            "instance_id": INSTANCE,
            "run_id": RUN,
            "action": action,
            "status": "dispatched",
            "reason": None,
        }


class FakeClock:
    """让等待循环按睡眠推进单调时钟，避免真实等待或死循环。"""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.01)


class GuiCharacterCase(unittest.TestCase):
    """共享临时运行目录、假后端、假桥与可推进时钟。"""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bridge_directory = self.root / "bridge"
        self.bridge_directory.mkdir()
        self.stage = stage()
        self.backend = MagicMock(name="backend")
        self.backend.name = "beidou"
        self.backend.root = self.root
        self.backend.instance = "default"
        self.backend.read.return_value = self.stage
        self.bridge = FakeNativeBridge(self.bridge_directory)
        self.runtime = SimpleNamespace(running=True, run_id=RUN, run_dir=self.root)
        self.clock = FakeClock()
        for item in (
            patch("beidou_pilot.gui_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.gui_character.BridgeClient", return_value=self.bridge),
            patch("beidou_pilot.gui_character.time", self.clock),
        ):
            item.start()
            self.addCleanup(item.stop)

    def show(self, windows, **overrides):
        self.stage = stage(windows, **overrides)
        self.backend.read.return_value = self.stage
        return self.stage

    def record(self, params=PARAMS):
        return record_attempt(self.root, instance_id=INSTANCE, run_id=RUN, params=params, previous_ids=set())

    def arguments(self, record):
        return {"directory": self.root, **attempt_identity(record)}

    def write_name_checked(self, record):
        (self.root / "gui-character-name-checked").write_text(record["request_id"], encoding="utf-8")

    def native(self, **overrides):
        self.bridge.snapshot_state = {**self.bridge.snapshot_state, **overrides}
        return self.bridge.snapshot_state


class GuiCharacterPageTest(unittest.TestCase):
    def test_identifies_each_unique_creation_page(self):
        for page in ("category", "name", "appearance"):
            with self.subTest(page=page):
                scene = stage([page_window(page)])
                self.assertEqual(
                    identify_creation_page(scene, instance_id=INSTANCE, run_id=RUN), page, "唯一签名和尺寸的建角页应被识别"
                )

    def test_first_matching_page_wins_when_multiple_pages_are_present(self):
        scene = stage([page_window("name"), page_window("category"), page_window("appearance")])
        self.assertEqual(
            identify_creation_page(scene, instance_id=INSTANCE, run_id=RUN), "category", "页面识别应按类别、姓名、外观顺序"
        )

    def test_unknown_for_wrong_size_or_foreign_window(self):
        cases = {
            "尺寸不符": stage([page_window("category", width=699)]),
            "未知窗口": stage([{"vtables": ["0xdeadbeef"], "width": 700, "height": 460, "address": ADDRESS}]),
            "重复匹配": stage([page_window("category"), page_window("category", address="0x5555")]),
            "无窗口": stage([]),
        }
        for label, scene in cases.items():
            with self.subTest(case=label):
                self.assertEqual(
                    identify_creation_page(scene, instance_id=INSTANCE, run_id=RUN), "unknown", "无法唯一确认的页面应返回 unknown"
                )

    def test_unknown_for_identity_pending_or_unavailable_state(self):
        base = stage([page_window("category")])
        cases = {
            "实例不符": {**base, "instance_id": "other"},
            "客户端运行不符": {**base, "client": {"run_id": "other"}},
            "客户端缺失": {**base, "client": None},
            "登录状态缺失": {**base, "login": None},
            "观察不完整": {**base, "unavailable": ["client_unavailable"]},
            "请求等待中": {**base, "login": {**base["login"], "request_pending": True}},
            "过渡等待中": {**base, "login": {**base["login"], "transition_pending": True}},
            "窗口清单无效": {**base, "windows": None},
        }
        for label, scene in cases.items():
            with self.subTest(case=label):
                self.assertEqual(
                    identify_creation_page(scene, instance_id=INSTANCE, run_id=RUN), "unknown", "身份或登录状态不明时应拒绝识别"
                )

    def test_window_lookup_returns_unique_address_and_window(self):
        category = page_window("category", address=CATEGORY_ADDRESS)
        address, window = _creation_window(stage([category]), "category")
        self.assertEqual(address, CATEGORY_ADDRESS, "应返回唯一匹配窗口的原生地址")
        self.assertIs(window, category, "应返回匹配到的窗口观察")

    def test_window_lookup_rejects_ambiguous_or_malformed_windows(self):
        cases = {
            "重复签名": [page_window("category"), page_window("category")],
            "尺寸不符": [page_window("category", width=699)],
            "地址为零": [page_window("category", address="0x0")],
            "地址非十六进制": [page_window("category", address="not-an-address")],
            "地址非字符串": [page_window("category", address=1234)],
            "地址缺失": [{"vtables": list(CATEGORY_SIGNATURE), "width": 700, "height": 460}],
        }
        for label, windows in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ClientError) as raised:
                    _creation_window(stage(windows), "category")
                self.assertEqual(raised.exception.code, "gui_character_state_unknown", "窗口身份不确定时禁止输入")

    def test_window_lookup_rejects_unknown_page_and_missing_window_list(self):
        for scene, page in ((stage([page_window("category")]), "unknown"), ({"windows": None}, "category")):
            with self.subTest(page=page):
                with self.assertRaises(ClientError) as raised:
                    _creation_window(scene, page)
                self.assertEqual(raised.exception.code, "gui_character_state_unknown", "未知页面应拒绝")


class GuiCharacterFinalStateTest(unittest.TestCase):
    def test_accepts_only_exactly_matching_creation_state(self):
        self.assertEqual(
            _final_state(stage([appearance_window()]), PARAMS, instance_id=INSTANCE, run_id=RUN),
            {"address": ADDRESS},
            "外观、职业、性别与创建按钮全部匹配时才允许最终确认",
        )

    def test_rejects_any_raw_appearance_mismatch(self):
        for index in range(8):
            with self.subTest(field=index):
                raw = list(RAW)
                raw[index] += 1
                scene = stage([appearance_window(raw=raw)])
                self.assertIsNone(
                    _final_state(scene, PARAMS, instance_id=INSTANCE, run_id=RUN), "任一外观槽不符时不得提交"
                )

    def test_rejects_job_gender_or_create_button_state(self):
        cases = {
            "职业不符": stage([appearance_window(job=2)]),
            "性别不符": stage([appearance_window(selector=0)]),
            "按钮禁用": stage([appearance_window(buttons=[{"control_id": 1000, "enabled": False}])]),
            "按钮缺失": stage([appearance_window(buttons=[])]),
            "按钮重复": stage(
                [appearance_window(buttons=[{"control_id": 1000, "enabled": True}] * 2)]
            ),
            "按钮清单无效": stage(
                [{key: value for key, value in appearance_window().items() if key != "buttons"}]
            ),
            "未在创建页": stage([page_window("name")]),
            "登录等待中": stage([appearance_window()], login={"request_pending": True}),
        }
        for label, scene in cases.items():
            with self.subTest(case=label):
                self.assertIsNone(
                    _final_state(scene, PARAMS, instance_id=INSTANCE, run_id=RUN), "最终创建条件不完整时不得提交"
                )


class GuiCharacterAppearancePlanTest(unittest.TestCase):
    def test_plan_steps_through_each_wire_field_in_order(self):
        names = ("face", "hair", "hair_color", "skin", "top", "bottom", "shoes", "weapon")
        for index, name in enumerate(names):
            with self.subTest(field=name):
                target = replace(PARAMS, **{name: RAW[index] + 1})
                self.assertEqual(
                    plan_observed_appearance_step(target, RAW, [set() for _ in range(8)]),
                    {"status": "step", "field": index, "control_id": 1011 + index},
                    "应按封包字段顺序给出下一个轮转槽",
                )

    def test_plan_matches_and_detects_unavailable_cycles(self):
        self.assertEqual(
            plan_observed_appearance_step(PARAMS, list(RAW), [set() for _ in range(8)]),
            {"status": "matched"},
            "原始值全部匹配时无需输入",
        )
        seen = [set() for _ in range(8)]
        seen[0].add(RAW[0] - 1)
        raw = list(RAW)
        raw[0] -= 1
        self.assertEqual(
            plan_observed_appearance_step(PARAMS, raw, seen),
            {"status": "unavailable", "field": 0},
            "目标槽已出现过的候选值不应重复轮转",
        )

    def test_plan_returns_unknown_for_malformed_observation(self):
        for raw, seen in (
            (RAW[:-1], [set() for _ in range(8)]),
            ([str(value) for value in RAW], [set() for _ in range(8)]),
            (list(RAW), [set() for _ in range(7)]),
            ("not-a-list", [set() for _ in range(8)]),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    plan_observed_appearance_step(PARAMS, raw, seen), {"status": "unknown"}, "原始值不完整时保持 unknown"
                )

    def test_plan_rejects_invalid_parameters_before_planning(self):
        with self.assertRaises(ClientError) as raised:
            plan_observed_appearance_step(CharacterCreation("", 1, *RAW, True), RAW, [set() for _ in range(8)])
        self.assertEqual(raised.exception.code, "character_creation_invalid", "参数无效时应直接拒绝")

    def test_transition_requires_exactly_one_changed_field(self):
        after = list(RAW)
        after[3] += 1
        self.assertTrue(validate_appearance_transition(RAW, after, 3), "仅目标槽变化应确认一次外观动作")
        self.assertFalse(validate_appearance_transition(RAW, RAW, 3), "槽值未变化不得确认")
        both = list(after)
        both[5] += 1
        self.assertFalse(validate_appearance_transition(RAW, both, 3), "其他槽同时变化不得确认")
        self.assertFalse(validate_appearance_transition(RAW, after, 2), "观察到的槽位不符不得确认")

    def test_transition_rejects_malformed_observations(self):
        after = list(RAW)
        after[0] += 1
        for before, changed, field in (
            (RAW[:-1], after, 0),
            (RAW, after[:-1], 0),
            (RAW, after, 8),
            (RAW, after, -1),
            (RAW, after, "0"),
            ([bool(value) for value in RAW], after, 0),
            ("raw", after, 0),
        ):
            with self.subTest(field=field):
                self.assertFalse(validate_appearance_transition(before, changed, field), "异常观察不得确认为一次外观动作")


class GuiCharacterAttemptContractTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def record(self, previous_ids=(), params=PARAMS):
        return record_attempt(
            self.root, instance_id=INSTANCE, run_id=RUN, params=params, previous_ids=set(previous_ids)
        )

    def test_attempt_is_persisted_once_before_any_input(self):
        record = self.record([7])
        self.assertEqual(json.loads((self.root / "gui-character-attempt.json").read_text(encoding="utf-8")), record)
        self.assertEqual(record["previous_ids"], [7])
        self.assertEqual(record["status"], "unknown")
        self.assertRegex(record["request_id"], r"^[0-9a-f]{32}$")
        with self.assertRaises(ClientError) as raised:
            self.record([7])
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "同一运行目录禁止二次认领建角")
        self.assertEqual(raised.exception.details["request_id"], record["request_id"])
        self.assertEqual(raised.exception.details["run_id"], RUN)

    def test_attempt_rejects_invalid_identity_and_previous_ids(self):
        cases = (
            {"instance_id": "bad id", "run_id": RUN, "previous_ids": set(), "code": "login_bridge_invalid_identity"},
            {"instance_id": INSTANCE, "run_id": "", "previous_ids": set(), "code": "login_bridge_invalid_identity"},
            {"instance_id": INSTANCE, "run_id": RUN, "previous_ids": {0}, "code": "login_bridge_invalid_state"},
            {"instance_id": INSTANCE, "run_id": RUN, "previous_ids": {2**31}, "code": "login_bridge_invalid_state"},
            {"instance_id": INSTANCE, "run_id": RUN, "previous_ids": {True}, "code": "login_bridge_invalid_state"},
        )
        for case in cases:
            with self.subTest(instance_id=case["instance_id"], previous_ids=case["previous_ids"]):
                with self.assertRaises(ClientError) as raised:
                    record_attempt(
                        self.root,
                        instance_id=case["instance_id"],
                        run_id=case["run_id"],
                        params=PARAMS,
                        previous_ids=case["previous_ids"],
                    )
                self.assertEqual(raised.exception.code, case["code"], "无效身份或旧 CID 不得写入尝试")
                self.assertFalse((self.root / "gui-character-attempt.json").exists())

    def test_attempt_rejects_invalid_parameters(self):
        with self.assertRaises(ClientError) as raised:
            self.record(params=CharacterCreation("", 1, *RAW, True))
        self.assertEqual(raised.exception.code, "character_creation_invalid", "参数无效时不得写入尝试")

    def test_attempt_write_failure_keeps_request_identity_unknown(self):
        with patch("beidou_pilot.gui_character.os.fsync", side_effect=OSError("simulated disk error")):
            with self.assertRaises(ClientError) as raised:
                self.record()
        self.assertEqual(raised.exception.code, "login_bridge_write_failed", "尝试写入失败时结果未知")
        self.assertRegex(raised.exception.details["request_id"], r"^[0-9a-f]{32}$")

    def test_final_submit_marker_requires_attempt_identity_and_is_single_use(self):
        with self.assertRaises(ClientError) as raised:
            mark_final_submit(self.root, instance_id=INSTANCE, run_id=RUN, request_id="a" * 32)
        self.assertEqual(raised.exception.code, "login_bridge_write_failed", "缺少尝试记录时不得写最终确认标记")
        record = self.record()
        with self.assertRaises(ClientError) as raised:
            mark_final_submit(self.root, instance_id=INSTANCE, run_id="other", request_id=record["request_id"])
        self.assertEqual(raised.exception.code, "gui_character_identity_unconfirmed", "身份不符时不得写最终确认标记")
        mark_final_submit(self.root, instance_id=INSTANCE, run_id=RUN, request_id=record["request_id"])
        self.assertEqual((self.root / "gui-character-final-submit").read_text(encoding="utf-8"), record["request_id"])
        with self.assertRaises(ClientError) as raised:
            mark_final_submit(self.root, instance_id=INSTANCE, run_id=RUN, request_id=record["request_id"])
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "最终确认标记只允许写一次")

    def test_final_submit_marker_rejects_invalid_request_format(self):
        for request_id in ("short", "b" * 31, "B" * 32):
            with self.subTest(request_id=request_id):
                with self.assertRaises(ClientError) as raised:
                    mark_final_submit(self.root, instance_id=INSTANCE, run_id=RUN, request_id=request_id)
                self.assertEqual(raised.exception.code, "login_bridge_invalid_request", "请求身份格式无效时应拒绝")

    def test_final_dispatch_requires_explicit_success_and_markers(self):
        record = self.record()
        args = {"instance_id": INSTANCE, "run_id": RUN, "request_id": record["request_id"]}
        with self.assertRaises(ClientError) as raised:
            record_final_dispatch(self.root, **args, dispatched=True)
        self.assertEqual(raised.exception.code, "login_bridge_write_failed", "缺少最终确认标记时不得记录回执")
        mark_final_submit(self.root, **args)
        for dispatched in (False, 1, None):
            with self.subTest(dispatched=dispatched):
                with self.assertRaises(ClientError) as raised:
                    record_final_dispatch(self.root, **args, dispatched=dispatched)
                self.assertEqual(raised.exception.code, "gui_character_action_unknown", "只接受明确的成功回执")
        with self.assertRaises(ClientError) as raised:
            record_final_dispatch(self.root, **{**args, "request_id": "b" * 32}, dispatched=True)
        self.assertEqual(raised.exception.code, "gui_character_identity_unconfirmed", "请求身份不符时不得记录回执")
        record_final_dispatch(self.root, **args, dispatched=True)
        self.assertEqual(
            (self.root / "gui-character-final-dispatched").read_text(encoding="utf-8"), record["request_id"]
        )
        with self.assertRaises(ClientError) as raised:
            record_final_dispatch(self.root, **args, dispatched=True)
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "最终回执只允许记录一次")


class GuiCharacterResultContractTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def verify(self, state, *, name="Example", previous_ids=None):
        return verify_created_character(
            state,
            instance_id=INSTANCE,
            run_id=RUN,
            name=name,
            previous_ids=set() if previous_ids is None else previous_ids,
        )

    def test_completed_requires_one_new_matching_character_id(self):
        state = stage(characters=[{"id": 19, "name": "Example"}])
        self.assertEqual(
            self.verify(state),
            {"status": "completed", "instance_id": INSTANCE, "run_id": RUN, "character_id": 19},
            "唯一新增且同名的角色才可判定建角完成",
        )
        self.assertEqual(self.verify(state, previous_ids={19})["status"], "unknown", "没有新增 CID 时不得判定完成")
        state["login"]["characters"].append({"id": 20, "name": "Other"})
        self.assertEqual(self.verify(state)["status"], "unknown", "一次请求只能核验唯一新增角色")
        self.assertEqual(
            self.verify(state, name="Other", previous_ids={19})["status"], "completed", "旧列表外唯一新增且同名时应完成"
        )
        self.assertEqual(self.verify(state, name="Missing", previous_ids={19})["status"], "unknown", "新增角色名不符时不得完成")

    def test_unknown_when_character_list_or_identity_is_unclear(self):
        base = stage(characters=[{"id": 19, "name": "Example"}])
        cases = {
            "请求等待中": {**base, "login": {**base["login"], "request_pending": True}},
            "过渡等待中": {**base, "login": {**base["login"], "transition_pending": True}},
            "角色列表未就绪": {**base, "login": {**base["login"], "characters_available": False}},
            "不是角色选择页": {**base, "stage": "LOGIN"},
            "观察不完整": {**base, "unavailable": ["client_unavailable"]},
            "运行身份不符": {**base, "client": {"run_id": "other"}},
            "实例身份不符": {**base, "instance_id": "other"},
            "角色列表非法": {**base, "login": {**base["login"], "characters": "not-a-list"}},
            "CID 非法": {**base, "login": {**base["login"], "characters": [{"id": 0, "name": "Example"}]}},
            "角色名为空": {**base, "login": {**base["login"], "characters": [{"id": 19, "name": ""}]}},
        }
        for label, state in cases.items():
            with self.subTest(case=label):
                self.assertEqual(self.verify(state)["status"], "unknown", "观察不完整时只能保持 unknown")

    def test_unknown_when_previous_ids_are_not_a_subset(self):
        state = stage(characters=[{"id": 19, "name": "Example"}])
        self.assertEqual(self.verify(state, previous_ids={19, 30})["status"], "unknown", "旧角色列表必须完整包含在观察中")

    def test_unknown_for_empty_name(self):
        state = stage(characters=[{"id": 19, "name": "Example"}])
        self.assertEqual(self.verify(state, name="")["status"], "unknown", "空姓名无法核验新增角色")


class GuiCharacterResultPersistenceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = stage(characters=[{"id": 19, "name": "Example"}])
        self.record = record_attempt(
            self.root, instance_id=INSTANCE, run_id=RUN, params=PARAMS, previous_ids=set()
        )
        self.identity = attempt_identity(self.record)

    def persist(self, state=None):
        return persist_result(
            self.root,
            bridge_directory=self.root,
            state=self.state if state is None else state,
            **self.identity,
        )

    def mark(self):
        mark_final_submit(self.root, **self.identity)

    def dispatch(self):
        self.mark()
        record_final_dispatch(self.root, **self.identity, dispatched=True)

    def test_query_result_keeps_unknown_until_login_bridge_has_terminal_result(self):
        self.assertEqual(query_result(self.root, **self.identity)["status"], "unknown", "缺失结果文件时保持 unknown")
        self.dispatch()
        self.assertEqual(self.persist()["character_id"], 19, "最终确认派发后应从新鲜角色列表核验完成")
        self.assertEqual(query_result(self.root, **self.identity)["character_id"], 19, "完成结果应写入登录桥结果目录")
        with self.assertRaises(ClientError) as raised:
            query_result(self.root, **{**self.identity, "run_id": "other"})
        self.assertEqual(raised.exception.code, "login_bridge_invalid_result", "身份不符的结果文件不得读取")

    def test_persist_stays_unknown_until_both_final_markers_exist(self):
        self.assertEqual(self.persist()["status"], "unknown", "未发送最终确认前不得持久化建角结果")
        self.mark()
        self.assertEqual(self.persist()["status"], "unknown", "只有最终确认标记仍不能证明动作已派发")
        record_final_dispatch(self.root, **self.identity, dispatched=True)
        self.assertEqual(self.persist()["character_id"], 19, "两个最终标记齐备后才允许持久化结果")

    def test_existing_terminal_result_is_authoritative(self):
        results = self.root / "login-results"
        results.mkdir()
        terminal = {"protocol": 1, "operation": "create_character", **self.identity, "status": "rejected"}
        (results / (self.identity["request_id"] + ".json")).write_text(json.dumps(terminal), encoding="utf-8")
        self.assertEqual(self.persist(), terminal, "已有终态结果不得被后续观察覆盖")
        self.assertEqual(query_result(self.root, **self.identity), terminal, "查询应返回同一终态结果")

    def test_completed_requires_fresh_unambiguous_character_list(self):
        self.dispatch()
        self.state["login"]["request_pending"] = True
        self.assertEqual(self.persist()["status"], "unknown", "请求等待中不得核验完成")
        self.state["login"]["request_pending"] = False
        self.state["login"]["characters"] = []
        self.assertEqual(self.persist()["status"], "unknown", "没有新增角色不得核验完成")
        self.state["login"]["characters"] = [{"id": 19, "name": "Other"}]
        self.assertEqual(self.persist()["status"], "unknown", "新增角色名不符不得核验完成")

    def test_invalid_attempt_record_keeps_result_unknown(self):
        self.dispatch()
        attempt = json.loads((self.root / "gui-character-attempt.json").read_text(encoding="utf-8"))
        for mutation in ({**attempt, "request_id": "b" * 32}, {**attempt, "previous_ids": [0]}, {**attempt, "protocol": 2}):
            (self.root / "gui-character-attempt.json").write_text(json.dumps(mutation), encoding="utf-8")
            self.assertEqual(self.persist()["status"], "unknown", "尝试记录身份或旧 CID 无效时不得核验完成")

    def test_nonterminal_result_is_upgraded_from_fresh_characters(self):
        self.dispatch()
        results = self.root / "login-results"
        results.mkdir()
        path = results / (self.identity["request_id"] + ".json")
        path.write_text(
            json.dumps({"protocol": 1, "operation": "create_character", **self.identity, "status": "accepted"}),
            encoding="utf-8",
        )
        self.assertEqual(self.persist()["status"], "completed", "非终态结果可由新鲜角色列表升级为完成")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["character_id"], 19)
        stale = {**self.state, "login": {**self.state["login"], "characters": [{"id": 20, "name": "Example"}]}}
        self.assertEqual(self.persist(state=stale)["character_id"], 19, "已完成结果不得被矛盾观察改写")

    def test_interrupted_write_never_corrupts_existing_result(self):
        self.dispatch()
        results = self.root / "login-results"
        results.mkdir()
        path = results / (self.identity["request_id"] + ".json")
        path.write_text(
            json.dumps({"protocol": 1, "operation": "create_character", **self.identity, "status": "accepted"}),
            encoding="utf-8",
        )
        with patch.object(Path, "replace", side_effect=OSError("simulated interruption")):
            with self.assertRaises(ClientError) as raised:
                self.persist()
        self.assertEqual(raised.exception.code, "login_bridge_write_failed", "写入中断时结果保持未知")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "accepted", "中断不得破坏已有结果")
        self.assertEqual(self.persist()["status"], "completed", "重试持久化可从新鲜角色列表完成")

    def test_unreadable_terminal_result_is_never_overwritten(self):
        self.dispatch()
        results = self.root / "login-results"
        results.mkdir()
        path = results / (self.identity["request_id"] + ".json")
        terminal = {"protocol": 1, "operation": "create_character", **self.identity, "status": "rejected"}
        path.write_text(json.dumps(terminal), encoding="utf-8")
        original_open = Path.open

        def guarded_open(target, *positional, **keywords):
            if target == path:
                raise PermissionError("simulated unreadable result")
            return original_open(target, *positional, **keywords)

        with patch.object(Path, "open", guarded_open):
            with self.assertRaises(ClientError) as raised:
                self.persist()
        self.assertEqual(raised.exception.code, "login_bridge_unavailable", "无法读取终态结果时不得覆盖")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), terminal, "终态结果文件应保持原样")

    def test_invalid_existing_result_is_rejected_without_overwrite(self):
        self.dispatch()
        results = self.root / "login-results"
        results.mkdir()
        path = results / (self.identity["request_id"] + ".json")
        for payload in ("not-json", json.dumps({"protocol": 1, "operation": "create_character", **self.identity, "run_id": "other"})):
            with self.subTest(payload=payload[:20]):
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ClientError) as raised:
                    self.persist()
                self.assertEqual(raised.exception.code, "login_bridge_invalid_result", "无效结果不得解读为完成")
                self.assertEqual(path.read_text(encoding="utf-8"), payload, "无效结果不得被覆盖")


class GuiCharacterNativeActionTest(GuiCharacterCase):
    def test_open_creation_sends_single_creation_panel_button(self):
        panel = create_panel()
        self.show([panel])
        category = page_window("category", address=CATEGORY_ADDRESS)

        def act(action, *arguments):
            if action == "ui_button" and arguments == (PANEL_ADDRESS, "1001"):
                self.show([category])

        self.bridge.on_action = act
        record = self.record()
        result = _open_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "category_page"}, "空角色列表应经原生按钮打开类别页")
        self.assertEqual(self.bridge.calls, [("ui_button", PANEL_ADDRESS, "1001")], "只应发送一次建角按钮动作")
        self.assertEqual(
            (self.root / "gui-character-open-attempt").read_text(encoding="utf-8"),
            record["request_id"],
            "建角按钮动作前应先记账",
        )

    def test_open_creation_rejects_nonempty_or_unknown_character_list(self):
        panel = create_panel()
        record = self.record()
        cases = {
            "非空列表": stage([panel], characters=[{"id": 19, "name": "Other"}]),
            "列表未就绪": stage([panel], login={"characters_available": False}),
            "非选择页": stage([panel], stage_name="LOGIN"),
            "原始步骤不符": stage([panel], raw_step=4),
            "请求等待中": stage([panel], login={"request_pending": True}),
        }
        for label, scene in cases.items():
            with self.subTest(case=label):
                self.backend.read.return_value = scene
                with self.assertRaises(ClientError) as raised:
                    _open_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
                self.assertEqual(raised.exception.code, "gui_character_state_unknown", "角色列表或页面状态不明时禁止输入")
                self.assertEqual(self.bridge.calls, [], "未确认空角色列表前不得发送原生动作")

    def test_open_creation_requires_unique_creation_panel(self):
        record = self.record()
        cases = {
            "面板缺失": [],
            "面板重复": [create_panel(), create_panel(address="0x9999")],
            "尺寸不符": [{"vtables": list(CREATE_PANEL_SIGNATURE), "width": 100, "height": 131, "address": PANEL_ADDRESS}],
        }
        for label, windows in cases.items():
            with self.subTest(case=label):
                self.backend.read.return_value = stage(windows)
                with self.assertRaises(ClientError) as raised:
                    _open_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
                self.assertEqual(raised.exception.code, "gui_character_state_unknown", "建角按钮窗口不唯一时禁止输入")
                self.assertEqual(self.bridge.calls, [], "窗口身份不确定时不得发送原生动作")

    def test_open_creation_refuses_later_stage_markers_and_replays(self):
        panel = create_panel()
        self.show([panel], characters=[])
        record = self.record()
        for marker in (
            "gui-character-final-submit",
            "gui-character-appearance-attempt",
            "gui-character-name-attempt",
            "gui-character-category-attempt",
        ):
            with self.subTest(marker=marker):
                path = self.root / marker
                path.write_text(record["request_id"], encoding="utf-8")
                with self.assertRaises(ClientError) as raised:
                    _open_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
                self.assertEqual(raised.exception.code, "gui_character_already_attempted", "后续阶段已开始时应拒绝重放")
                path.unlink()
        self.assertEqual(self.bridge.calls, [], "拒绝重放时不得发送原生动作")

    def test_native_action_rejection_propagates_without_retry(self):
        self.show([create_panel()])
        self.bridge.rejected_actions = {"ui_button"}
        record = self.record()
        with self.assertRaises(ClientError) as raised:
            _open_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_native_action_rejected", "原生桥拒绝动作应显式上抛")
        self.assertEqual(self.bridge.calls, [("ui_button", PANEL_ADDRESS, "1001")], "原生拒绝后不得重试")
        self.assertTrue((self.root / "gui-character-open-attempt").exists(), "拒绝前已记账的动作不得重放")

    def test_open_creation_timeout_returns_unknown_before_input(self):
        self.show([create_panel()])
        record = self.record()
        result = _open_creation(self.backend, PARAMS, **self.arguments(record), deadline=0)
        self.assertEqual(result, {"status": "unknown", "reason": "timeout"}, "期限已过时返回 unknown")
        self.assertEqual(self.bridge.calls, [], "期限已过时不得发送原生动作")
        self.assertFalse((self.root / "gui-character-open-attempt").exists(), "期限已过时不得记账")

    def test_open_creation_unknown_when_category_page_never_appears(self):
        self.show([create_panel()])
        record = self.record()
        result = _open_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "unknown", "reason": "next_page_unconfirmed"}, "类别页未出现时保持 unknown")
        self.assertEqual(self.bridge.calls, [("ui_button", PANEL_ADDRESS, "1001")], "类别页未出现不得重放按钮动作")
        with self.assertRaises(ClientError) as raised:
            _open_creation(self.backend, PARAMS, **self.arguments(record), deadline=10)
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "已记账的按钮动作不得重放")
        self.assertEqual(self.bridge.calls, [("ui_button", PANEL_ADDRESS, "1001")], "重放被拒时不得再次发送动作")

    def test_navigate_category_sends_single_confirm_button(self):
        self.show([page_window("category", address=CATEGORY_ADDRESS)])
        name_page = page_window("name", address=NAME_ADDRESS)

        def act(action, *arguments):
            if action == "ui_button" and arguments == (CATEGORY_ADDRESS, "1003"):
                self.show([name_page])

        self.bridge.on_action = act
        record = self.record()
        result = _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "name_page"}, "类别页确认后应观察姓名页")
        self.assertEqual(self.bridge.calls, [("ui_button", CATEGORY_ADDRESS, "1003")], "只应发送一次类别确认动作")
        self.assertEqual(
            (self.root / "gui-character-category-attempt").read_text(encoding="utf-8"),
            record["request_id"],
            "类别确认动作前应先记账",
        )

    def test_navigate_category_rejects_wrong_page_and_replays(self):
        self.show([page_window("name", address=NAME_ADDRESS)])
        record = self.record()
        with self.assertRaises(ClientError) as raised:
            _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "页面不符时禁止输入")
        self.assertEqual(self.bridge.calls, [], "页面不符时不得发送动作")
        self.show([page_window("category", address=CATEGORY_ADDRESS)])
        first = _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(first, {"status": "unknown", "reason": "next_page_unconfirmed"}, "姓名页未出现时保持 unknown")
        self.assertEqual(self.bridge.calls, [("ui_button", CATEGORY_ADDRESS, "1003")], "类别确认只应发送一次")
        with self.assertRaises(ClientError) as raised:
            _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=10)
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "已记账的类别确认不得重放")
        self.assertEqual(self.bridge.calls, [("ui_button", CATEGORY_ADDRESS, "1003")], "重放被拒时不得再次发送动作")

    def test_submit_name_passes_ascii_bytes_once(self):
        self.show([page_window("name", address=NAME_ADDRESS)])
        appearance = page_window("appearance", address=ADDRESS)

        def act(action, *arguments):
            if action == "check_name" and arguments == (NAME_ADDRESS, b"Example"):
                self.show([appearance])

        self.bridge.on_action = act
        record = self.record()
        result = _submit_name(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "appearance_page"}, "姓名核查通过后应观察外观页")
        self.assertEqual(
            self.bridge.calls,
            [("check_name", NAME_ADDRESS, b"Example")],
            "姓名应按 ASCII bytes 交给原生 check_name",
        )
        self.assertEqual(
            (self.root / "gui-character-name-checked").read_text(encoding="utf-8"),
            record["request_id"],
            "观察到外观页后才应确认姓名已核查",
        )

    def test_submit_name_rejects_unsupported_parameters_before_input(self):
        self.show([page_window("name", address=NAME_ADDRESS)])
        record = self.record()
        for label, params, code in (
            ("非 ASCII 姓名", CharacterCreation("角色", 1, *RAW, True), "unsupported_capability"),
            ("职业不支持", CharacterCreation("Example", 2, *RAW, True), "unsupported_capability"),
        ):
            with self.subTest(case=label):
                with self.assertRaises(ClientError) as raised:
                    _submit_name(self.backend, params, **self.arguments(record), deadline=2)
                self.assertEqual(raised.exception.code, code, "不支持的参数不得发送原生动作")
        self.assertEqual(self.bridge.calls, [], "参数被拒时不得发送姓名核查")

    def test_submit_name_requires_name_page_and_deadline(self):
        self.show([page_window("category", address=CATEGORY_ADDRESS)])
        record = self.record()
        with self.assertRaises(ClientError) as raised:
            _submit_name(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "非姓名页不得发起姓名核查")
        self.show([page_window("name", address=NAME_ADDRESS)])
        result = _submit_name(self.backend, PARAMS, **self.arguments(record), deadline=0)
        self.assertEqual(result, {"status": "unknown", "reason": "timeout"}, "期限已过时返回 unknown")
        self.assertEqual(self.bridge.calls, [], "被拒时不得发送姓名核查")

    def test_submit_name_unknown_when_appearance_page_never_appears(self):
        self.show([page_window("name", address=NAME_ADDRESS)])
        record = self.record()
        result = _submit_name(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "unknown", "reason": "next_page_unconfirmed"}, "外观页未出现时保持 unknown")
        self.assertEqual(self.bridge.calls, [("check_name", NAME_ADDRESS, b"Example")], "姓名核查只应发送一次")
        with self.assertRaises(ClientError) as raised:
            _submit_name(self.backend, PARAMS, **self.arguments(record), deadline=10)
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "已记账的姓名核查不得重放")

    def prepare_gender(self, *, female, selector, job=1):
        record = self.record(CharacterCreation("Example", 1, *RAW, female))
        self.write_name_checked(record)
        self.show([appearance_window(selector=selector, job=job)])
        return record

    def test_gender_is_skipped_when_female_selector_already_matches(self):
        record = self.prepare_gender(female=True, selector=1)
        result = _set_gender(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "matched"}, "外观性别已匹配时不得输入")
        self.assertEqual(self.bridge.calls, [], "性别已匹配时不得发送原生动作")
        self.assertFalse((self.root / "gui-character-gender-attempt").exists(), "性别已匹配时不得记账")

    def test_gender_is_skipped_when_male_selector_already_matches(self):
        params = CharacterCreation("Example", 1, *RAW, False)
        record = self.prepare_gender(female=False, selector=0)
        result = _set_gender(self.backend, params, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "matched"}, "外观性别已匹配时不得输入")
        self.assertEqual(self.bridge.calls, [], "性别已匹配时不得发送原生动作")

    def test_gender_switch_to_female_uses_native_button_1019(self):
        record = self.prepare_gender(female=True, selector=0)

        def act(action, *arguments):
            if action == "ui_button" and arguments == (ADDRESS, "1019"):
                self.show([appearance_window(selector=1)])

        self.bridge.on_action = act
        result = _set_gender(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "matched"}, "性别切换后应确认选择值")
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1019")], "性别切换只应发送一次原生按钮动作")

    def test_gender_switch_to_male_uses_native_button_1019(self):
        params = CharacterCreation("Example", 1, *RAW, False)
        record = self.prepare_gender(female=False, selector=1)

        def act(action, *arguments):
            if action == "ui_button" and arguments == (ADDRESS, "1019"):
                self.show([appearance_window(selector=0)])

        self.bridge.on_action = act
        result = _set_gender(self.backend, params, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "matched"}, "性别切换后应确认选择值")
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1019")], "性别切换只应发送一次原生按钮动作")

    def test_gender_requires_checked_name_and_valid_selector(self):
        record = self.record()
        self.show([appearance_window(selector=0)])
        with self.assertRaises(ClientError) as raised:
            _set_gender(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "姓名核查未确认时不得切换性别")
        self.write_name_checked(record)
        for label, window in (
            ("职业不符", appearance_window(selector=0, job=2)),
            ("选择值非法", {**appearance_window(selector=0), "raw_appearance_selector": 2}),
            ("选择值缺失", {key: value for key, value in appearance_window(selector=0).items() if key != "raw_appearance_selector"}),
        ):
            with self.subTest(case=label):
                self.show([window])
                with self.assertRaises(ClientError) as raised:
                    _set_gender(self.backend, PARAMS, **self.arguments(record), deadline=2)
                self.assertEqual(raised.exception.code, "gui_character_state_unknown", "性别或职业不可确认时禁止输入")
        self.assertEqual(self.bridge.calls, [], "前置条件不满足时不得发送性别动作")

    def test_gender_rejects_page_change_after_dispatch(self):
        record = self.prepare_gender(female=True, selector=0)

        def act(action, *arguments):
            self.show([page_window("name", address=NAME_ADDRESS)])

        self.bridge.on_action = act
        with self.assertRaises(ClientError) as raised:
            _set_gender(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_action_unknown", "切换后页面变化时应停止输入")
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1019")], "异常后不得重放性别动作")

    def test_gender_rejects_job_change_after_dispatch(self):
        record = self.prepare_gender(female=True, selector=0)

        def act(action, *arguments):
            self.show([appearance_window(selector=1, job=2)])

        self.bridge.on_action = act
        with self.assertRaises(ClientError) as raised:
            _set_gender(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "切换后职业变化时应停止输入")
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1019")], "异常后不得重放性别动作")

    def test_gender_timeout_after_dispatch_returns_unknown_and_blocks_replay(self):
        record = self.prepare_gender(female=True, selector=0)
        result = _set_gender(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"status": "unknown", "reason": "timeout"}, "性别值未变化时应返回 unknown")
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1019")], "性别动作只应发送一次")
        with self.assertRaises(ClientError) as raised:
            _set_gender(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "性别切换未确认时禁止重放")
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1019")], "重放被拒时不得再次发送动作")

    def test_appearance_step_uses_one_rotation_for_first_differing_slot(self):
        raw = list(RAW)
        raw[3] = -1
        raw[5] = -1
        record = self.record()
        self.show([appearance_window(raw=raw)])

        def act(action, *arguments):
            if action == "ui_button" and arguments == (ADDRESS, "1014"):
                after = list(raw)
                after[3] = RAW[3]
                self.show([appearance_window(raw=after)])

        self.bridge.on_action = act
        result = _appearance_step(
            self.backend, PARAMS, [set() for _ in range(8)], **self.arguments(record), deadline=2
        )
        self.assertEqual(result["status"], "changed", "一次原生轮转只应改变一个目标槽")
        self.assertEqual(result["field"], 3, "应选择第一个待调整的外观槽")
        self.assertEqual(result["raw"], [RAW[index] if index == 3 else raw[index] for index in range(8)], "应返回轮转后的原始值")
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1014")], "应使用 1011+槽位 的原生按钮")

    def test_appearance_step_requires_exact_raw_observation(self):
        record = self.record()
        cases = {
            "原始值缺失": {key: value for key, value in appearance_window().items() if key != "raw_appearance_candidates"},
            "原始值不足": appearance_window(raw=RAW[:-1]),
            "原始值类型错误": appearance_window(raw=[str(value) for value in RAW]),
            "职业不符": appearance_window(job=2),
            "性别不符": appearance_window(selector=0),
        }
        for label, window in cases.items():
            with self.subTest(case=label):
                self.show([window])
                with self.assertRaises(ClientError) as raised:
                    _appearance_step(
                        self.backend, PARAMS, [set() for _ in range(8)], **self.arguments(record), deadline=2
                    )
                self.assertEqual(raised.exception.code, "gui_character_state_unknown", "原始观察不完整时禁止轮转")
        self.assertEqual(self.bridge.calls, [], "观察不完整时不得发送外观动作")

    def test_appearance_step_rejects_illegal_transitions(self):
        record = self.record()
        raw = list(RAW)
        raw[0] = RAW[0] - 1
        cases = {
            "其他槽变化": lambda: [RAW[0], RAW[1] + 1, *raw[2:]],
            "目标槽未变化": lambda: list(raw),
            "页面变化": lambda: None,
        }
        for label, change in cases.items():
            with self.subTest(case=label):
                self.show([appearance_window(raw=raw)])

                def act(action, *arguments, change=change, label=label):
                    if label == "页面变化":
                        self.show([page_window("name", address=NAME_ADDRESS)])
                    else:
                        self.show([appearance_window(raw=change())])

                self.bridge.on_action = act
                with self.assertRaises(ClientError) as raised:
                    _appearance_step(
                        self.backend, PARAMS, [set() for _ in range(8)], **self.arguments(record), deadline=2
                    )
                self.assertEqual(raised.exception.code, "gui_character_action_unknown", "不符合单槽变化的轮转不得确认")
        self.assertEqual(len(self.bridge.calls), len(cases), "每次非法轮转只应发送一次动作")

    def test_appearance_step_refuses_after_final_submit(self):
        record = self.record()
        (self.root / "gui-character-final-submit").write_text(record["request_id"], encoding="utf-8")
        self.show([appearance_window(raw=[value - 1 for value in RAW])])
        with self.assertRaises(ClientError) as raised:
            _appearance_step(self.backend, PARAMS, [set() for _ in range(8)], **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "最终确认开始后不得再发送外观动作")
        self.assertEqual(self.bridge.calls, [], "最终确认后不得发送外观动作")

    def test_appearance_step_timeout_returns_unknown_before_input(self):
        record = self.record()
        self.show([appearance_window(raw=[value - 1 for value in RAW])])
        result = _appearance_step(
            self.backend, PARAMS, [set() for _ in range(8)], **self.arguments(record), deadline=0
        )
        self.assertEqual(result, {"status": "unknown", "reason": "timeout"}, "期限已过时返回 unknown")
        self.assertEqual(self.bridge.calls, [], "期限已过时不得发送外观动作")

    def test_apply_appearance_rotates_until_all_fields_match(self):
        raw = list(RAW)
        raw[0] = RAW[0] - 1
        raw[2] = RAW[2] + 1
        record = self.record()
        self.show([appearance_window(raw=raw)])
        pending = {0: RAW[0], 2: RAW[2]}

        def act(action, *arguments):
            if action != "ui_button":
                return
            control = int(arguments[1])
            field = control - 1011
            current = self.stage["windows"][0]["raw_appearance_candidates"]
            if field in pending and current[field] != pending[field]:
                after = list(current)
                after[field] = pending[field]
                self.show([appearance_window(raw=after)])

        self.bridge.on_action = act
        result = _apply_appearance(self.backend, PARAMS, **self.arguments(record), timeout=5)
        self.assertEqual(result, {"status": "matched"}, "逐槽轮转后应达到目标外观")
        self.assertEqual(
            self.bridge.calls,
            [("ui_button", ADDRESS, "1011"), ("ui_button", ADDRESS, "1013")],
            "应按待调整槽位依次轮转",
        )
        self.assertEqual(self.stage["windows"][0]["raw_appearance_candidates"], RAW, "轮转结束后原始值应与参数匹配")
        self.assertEqual((self.root / "gui-character-appearance-attempt").read_text(encoding="utf-8"), record["request_id"])

    def test_apply_appearance_reports_cycle_unavailable(self):
        record = self.record()
        raw = list(RAW)
        raw[0] = RAW[0] - 1
        self.show([appearance_window(raw=raw)])

        def act(action, *arguments):
            if action == "ui_button" and arguments == (ADDRESS, "1011"):
                window = self.stage["windows"][0]
                after = list(window["raw_appearance_candidates"])
                after[0] = 21005 if after[0] != 21005 else 21000
                self.show([appearance_window(raw=after)])

        self.bridge.on_action = act
        result = _apply_appearance(self.backend, PARAMS, **self.arguments(record), timeout=5)
        self.assertEqual(result, {"status": "unavailable", "field": 0}, "候选值循环出现时应报告不可达")
        self.assertEqual(len(self.bridge.calls), 2, "循环后不得无限重试")

    def test_apply_appearance_replay_and_invalid_timeout_are_rejected(self):
        record = self.record()
        self.show([appearance_window()])
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ClientError) as raised:
                    _apply_appearance(self.backend, PARAMS, **self.arguments(record), timeout=timeout)
                self.assertEqual(raised.exception.code, "usage", "外观等待时间须为正有限数")
                self.assertFalse((self.root / "gui-character-appearance-attempt").exists())
        with patch("beidou_pilot.gui_character._appearance_step", return_value={"status": "changed"}) as step:
            values = iter(range(1000))
            self.clock.monotonic = lambda: next(values) * 0.5
            result = _apply_appearance(self.backend, PARAMS, **self.arguments(record), timeout=1)
            self.assertEqual(result, {"status": "unknown", "reason": "timeout"}, "期限已过时返回 unknown")
            self.assertEqual(step.call_count, 1)
            with self.assertRaises(ClientError) as raised:
                _apply_appearance(self.backend, PARAMS, **self.arguments(record), timeout=1)
            self.assertEqual(raised.exception.code, "gui_character_already_attempted", "外观调整只允许尝试一次")
            self.assertEqual(step.call_count, 1, "重放被拒时不得再次发送外观动作")

    def test_final_submit_sends_single_create_button_and_records_markers(self):
        record = self.record()
        self.write_name_checked(record)
        self.show([appearance_window()])
        result = _submit_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result, {"request_id": record["request_id"], "instance_id": INSTANCE, "run_id": RUN, "status": "unknown"})
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1000")], "最终确认只应发送一次创建按钮动作")
        self.assertEqual((self.root / "gui-character-final-submit").read_text(encoding="utf-8"), record["request_id"])
        self.assertEqual((self.root / "gui-character-final-dispatched").read_text(encoding="utf-8"), record["request_id"])
        with self.assertRaises(ClientError) as raised:
            _submit_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "最终确认已尝试时禁止重放")
        self.assertEqual(self.bridge.calls, [("ui_button", ADDRESS, "1000")], "重放被拒时不得再次发送创建动作")

    def test_final_submit_requires_checked_name_and_matching_state(self):
        record = self.record()
        self.show([appearance_window()])
        with self.assertRaises(ClientError) as raised:
            _submit_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "姓名核查未确认时禁止最终提交")
        self.write_name_checked(record)
        raw = list(RAW)
        raw[0] += 1
        self.show([appearance_window(raw=raw)])
        result = _submit_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result["status"], "unknown", "最终状态不匹配时返回 unknown")
        self.assertEqual(self.bridge.calls, [], "最终状态不匹配时不得发送创建动作")
        self.assertFalse((self.root / "gui-character-final-submit").exists(), "未确认最终状态时不得写最终确认标记")

    def test_final_submit_deadline_returns_unknown_without_input(self):
        record = self.record()
        self.write_name_checked(record)
        self.show([appearance_window()])
        result = _submit_creation(self.backend, PARAMS, **self.arguments(record), deadline=0)
        self.assertEqual(result["status"], "unknown", "期限已过时返回 unknown")
        self.assertEqual(self.bridge.calls, [], "期限已过时不得发送创建动作")
        self.assertFalse((self.root / "gui-character-final-submit").exists())

    def test_final_submit_changed_second_observation_blocks_dispatch(self):
        record = self.record()
        self.write_name_checked(record)
        matching = stage([appearance_window()])
        raw = list(RAW)
        raw[0] += 1
        changed = stage([appearance_window(raw=raw)])
        self.backend.read.side_effect = [matching, changed]
        result = _submit_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(result["status"], "unknown", "两次观察不一致时不得确认最终提交")
        self.assertEqual(self.bridge.calls, [], "两次观察不一致时不得发送创建动作")
        self.assertTrue((self.root / "gui-character-final-submit").exists(), "最终确认标记只能在尝试前写入")
        with self.assertRaises(ClientError) as raised:
            _submit_creation(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "最终确认尝试后禁止重放")


class GuiCharacterObserveContractTest(GuiCharacterCase):
    def test_rejects_changed_runtime_or_native_identity(self):
        self.show([page_window("category", address=CATEGORY_ADDRESS)])
        record = self.record()

        self.runtime.run_id = "other"
        with self.assertRaises(ClientError) as raised:
            _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "运行实例身份变化时禁止输入")
        self.runtime.run_id = RUN

        for label, native_state in (
            ("原生实例变化", {"instance_id": "other", "run_id": RUN}),
            ("原生运行变化", {"instance_id": INSTANCE, "run_id": "other"}),
        ):
            with self.subTest(case=label):
                self.native(**native_state)
                with self.assertRaises(ClientError) as raised:
                    _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=2)
                self.assertEqual(raised.exception.code, "gui_character_identity_unconfirmed", "原生桥身份变化时禁止输入")
                self.native(instance_id=INSTANCE, run_id=RUN)
        self.assertEqual(self.bridge.calls, [], "身份异常时不得发送原生动作")

    def test_rejects_busy_native_input(self):
        self.show([page_window("category", address=CATEGORY_ADDRESS)])
        record = self.record()
        cases = {
            "脚本运行中": {"scripts": [{"status": "running", "control_released": True}]},
            "脚本未释放输入": {"scripts": [{"status": "completed", "control_released": False}]},
            "命令运行中": {"command": {"status": "running"}},
            "残留按键": {"held_keys": [65]},
        }
        for label, native_state in cases.items():
            with self.subTest(case=label):
                self.native(**native_state)
                with self.assertRaises(ClientError) as raised:
                    _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=2)
                self.assertEqual(raised.exception.code, "input_busy", "原生输入不空闲时禁止 GUI 输入")
                self.native(scripts=[], command={"status": "idle"}, held_keys=[])
        self.assertEqual(self.bridge.calls, [], "输入不空闲时不得发送原生动作")

    def test_rejects_changed_stage_identity_or_incomplete_observation(self):
        self.show([page_window("category", address=CATEGORY_ADDRESS)])
        record = self.record()
        cases = {
            "实例变化": {**self.stage, "instance_id": "other"},
            "客户端运行变化": {**self.stage, "client": {"run_id": "other"}},
            "观察不完整": {**self.stage, "unavailable": ["client_unavailable"]},
            "登录状态缺失": {**self.stage, "login": None},
        }
        for label, scene in cases.items():
            with self.subTest(case=label):
                self.backend.read.return_value = scene
                with self.assertRaises(ClientError) as raised:
                    _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=2)
                self.assertEqual(raised.exception.code, "gui_character_state_unknown", "页面观察身份不明时禁止输入")
        self.assertEqual(self.bridge.calls, [], "观察异常时不得发送原生动作")

    def test_rejects_non_beidou_backend(self):
        self.show([page_window("category", address=CATEGORY_ADDRESS)])
        record = self.record()
        self.backend.name = "headless"
        with self.assertRaises(ClientError) as raised:
            _navigate_category(self.backend, PARAMS, **self.arguments(record), deadline=2)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "非 GUI 客户端不得执行建角动作")


class GuiCharacterWaitResultTest(GuiCharacterCase):
    def wait_arguments(self, request_id="a" * 32):
        return {
            "directory": self.root,
            "bridge_directory": self.bridge_directory,
            "request_id": request_id,
            "instance_id": INSTANCE,
            "run_id": RUN,
        }

    def test_completed_result_is_returned_without_reading_stage(self):
        completed = {"status": "completed", "character_id": 19}
        with patch("beidou_pilot.gui_character.query_result", return_value=completed):
            result = _wait_creation_result(self.backend, **self.wait_arguments(), deadline=float("inf"))
        self.assertEqual(result, completed, "登录桥已有终态结果时应直接返回")
        self.backend.read.assert_not_called()

    def test_two_stable_observations_are_required_before_persisting(self):
        completed = {"status": "completed", "character_id": 19}
        self.show([page_window("category")], characters=[])
        with (
            patch("beidou_pilot.gui_character.query_result", return_value={"status": "unknown"}),
            patch("beidou_pilot.gui_character.persist_result", return_value=completed) as persist,
        ):
            result = _wait_creation_result(self.backend, **self.wait_arguments(), deadline=float("inf"))
            self.assertEqual(result, completed, "两次相同观察后才应持久化建角结果")
            persist.assert_called_once()
            self.assertEqual(persist.call_args.kwargs["state"], self.stage, "持久化必须使用新鲜观察")
            self.assertEqual(self.backend.read.call_count, 2)

    def test_identity_or_runtime_change_returns_unknown_without_persisting(self):
        self.show([page_window("category")], characters=[])
        cases = {
            "运行已退出": lambda: setattr(self.runtime, "running", False),
            "运行身份变化": lambda: setattr(self.runtime, "run_id", "other"),
            "原生实例变化": lambda: self.native(instance_id="other"),
            "原生运行变化": lambda: self.native(run_id="other"),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                self.runtime.running, self.runtime.run_id = True, RUN
                self.native(instance_id=INSTANCE, run_id=RUN)
                mutate()
                with (
                    patch("beidou_pilot.gui_character.query_result", return_value={"status": "unknown"}),
                    patch("beidou_pilot.gui_character.persist_result") as persist,
                ):
                    result = _wait_creation_result(self.backend, **self.wait_arguments(), deadline=float("inf"))
                self.assertEqual(result["status"], "unknown", "实例或身份改变时结果保持未知")
                persist.assert_not_called()

    def test_deadline_and_query_errors_return_unknown(self):
        with (
            patch("beidou_pilot.gui_character.query_result", return_value={"status": "unknown"}),
            patch("beidou_pilot.gui_character.persist_result") as persist,
        ):
            result = _wait_creation_result(self.backend, **self.wait_arguments(), deadline=0)
        self.assertEqual(result["status"], "unknown", "期限已过时结果保持未知")
        persist.assert_not_called()
        with patch("beidou_pilot.gui_character.query_result", side_effect=ClientError("login_bridge_unavailable", "offline")):
            result = _wait_creation_result(self.backend, **self.wait_arguments(), deadline=float("inf"))
        self.assertEqual(result["status"], "unknown", "结果不可读取时保持未知")

    def test_observe_result_validates_timeout_and_counts_from_now(self):
        self.clock.monotonic = lambda: 5.0
        for timeout in (0, 2):
            with self.subTest(timeout=timeout), patch(
                "beidou_pilot.gui_character._wait_creation_result", return_value={"status": "unknown"}
            ) as wait:
                result = observe_result(self.backend, **self.wait_arguments(), timeout=timeout)
                self.assertEqual(result["status"], "unknown")
                wait.assert_called_once()
                self.assertEqual(wait.call_args.kwargs["deadline"], 5.0 + timeout, "相对等待时间应换算为绝对期限")
        for timeout in (-1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ClientError) as raised:
                    observe_result(self.backend, **self.wait_arguments(), timeout=timeout)
                self.assertEqual(raised.exception.code, "usage", "结果等待时间须为非负有限数")


class GuiCharacterFlowTest(GuiCharacterCase):
    def install_creation_sequence(self):
        """按原生动作驱动页面流转，模拟空角色列表上的完整原生建角序列。"""
        panel = create_panel()
        category = page_window("category", address=CATEGORY_ADDRESS)
        name = page_window("name", address=NAME_ADDRESS)
        raw = [value - 1 for value in RAW]
        appearance = appearance_window(raw=raw, selector=0)
        pages = {
            "start": stage([panel]),
            "category": stage([category]),
            "name": stage([name]),
            "appearance": stage([appearance]),
        }
        self.stage = pages["start"]
        self.backend.read.return_value = self.stage

        def act(action, *arguments):
            if action == "ui_button" and arguments == (PANEL_ADDRESS, "1001"):
                self.stage = pages["category"]
            elif action == "ui_button" and arguments == (CATEGORY_ADDRESS, "1003"):
                self.stage = pages["name"]
            elif action == "check_name" and arguments == (NAME_ADDRESS, b"Example"):
                self.stage = pages["appearance"]
            elif action == "ui_button" and arguments == (ADDRESS, "1019"):
                window = pages["appearance"]["windows"][0]
                window["raw_appearance_selector"] = 1
            elif (
                action == "ui_button"
                and len(arguments) == 2
                and arguments[0] == ADDRESS
                and arguments[1].isdigit()
                and 1011 <= int(arguments[1]) <= 1018
            ):
                window = pages["appearance"]["windows"][0]
                field = int(arguments[1]) - 1011
                after = list(window["raw_appearance_candidates"])
                after[field] = RAW[field]
                window["raw_appearance_candidates"] = after
            elif action == "ui_button" and arguments == (ADDRESS, "1000"):
                pass
            else:
                raise AssertionError("未预期的原生动作: %r %r" % (action, arguments))
            self.backend.read.return_value = self.stage

        self.bridge.on_action = act
        return pages

    def test_full_creation_sequence_uses_native_actions_in_order(self):
        self.install_creation_sequence()
        completed = {"status": "completed", "character_id": 19}
        with patch("beidou_pilot.gui_character._wait_creation_result", return_value=completed) as wait:
            result = create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(result, completed, "完整原生建角序列应返回登录桥结果")
        self.assertEqual(
            self.bridge.calls,
            [
                ("ui_button", PANEL_ADDRESS, "1001"),
                ("ui_button", CATEGORY_ADDRESS, "1003"),
                ("check_name", NAME_ADDRESS, b"Example"),
                ("ui_button", ADDRESS, "1019"),
                *[("ui_button", ADDRESS, str(1011 + index)) for index in range(8)],
                ("ui_button", ADDRESS, "1000"),
            ],
            "完整建角应依次发送打开、类别、姓名、性别、外观轮转与最终确认动作",
        )
        attempt = json.loads((self.root / "gui-character-attempt.json").read_text(encoding="utf-8"))
        self.assertEqual(attempt["params"], {"name": "Example", "job": 1, "face": RAW[0], "hair": RAW[1],
                                             "hair_color": RAW[2], "skin": RAW[3], "top": RAW[4],
                                             "bottom": RAW[5], "shoes": RAW[6], "weapon": RAW[7], "female": True})
        self.assertEqual(attempt["previous_ids"], [], "空角色列表的旧 CID 集合应为空")
        for marker in (
            "gui-character-open-attempt",
            "gui-character-category-attempt",
            "gui-character-name-attempt",
            "gui-character-name-checked",
            "gui-character-appearance-attempt",
            "gui-character-final-submit",
            "gui-character-final-dispatched",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(
                    (self.root / marker).read_text(encoding="utf-8"), attempt["request_id"], "每步动作前应先记账"
                )
        wait.assert_called_once()
        self.assertEqual(wait.call_args.kwargs["bridge_directory"], self.bridge.directory, "结果等待应读取原生桥目录")
        self.assertEqual(wait.call_args.kwargs["request_id"], attempt["request_id"])

    def test_create_rejects_nonempty_list_or_existing_name_before_attempt(self):
        cases = {
            "非空列表": ([{"id": 19, "name": "Other"}], "unsupported_capability"),
            "同名冲突": ([{"id": 19, "name": "Example"}], "gui_character_name_exists"),
            "CID 非法": ([{"id": 0, "name": "Other"}], "gui_character_state_unknown"),
            "重复 CID": ([{"id": 19, "name": "A"}, {"id": 19, "name": "B"}], "gui_character_state_unknown"),
            "角色名为空": ([{"id": 19, "name": ""}], "gui_character_state_unknown"),
        }
        for label, (characters, code) in cases.items():
            with self.subTest(case=label):
                self.show([create_panel()], characters=characters)
                with self.assertRaises(ClientError) as raised:
                    create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
                self.assertEqual(raised.exception.code, code, "角色列表不满足建角前置条件时应拒绝")
                self.assertFalse((self.root / "gui-character-attempt.json").exists(), "拒绝时不得写入建角尝试")
                self.assertEqual(self.bridge.calls, [], "拒绝时不得发送原生动作")

    def test_create_requires_character_select_identity_and_lock(self):
        self.show([create_panel()])
        cases = {
            "非角色选择页": stage([create_panel()], stage_name="LOGIN"),
            "列表未就绪": stage([create_panel()], login={"characters_available": False}),
            "请求等待中": stage([create_panel()], login={"request_pending": True}),
            "过渡等待中": stage([create_panel()], login={"transition_pending": True}),
            "观察不完整": stage([create_panel()], unavailable=["client_unavailable"]),
        }
        for label, scene in cases.items():
            with self.subTest(case=label):
                self.backend.read.return_value = scene
                with self.assertRaises(ClientError) as raised:
                    create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
                self.assertEqual(raised.exception.code, "gui_character_state_unknown", "页面或观察不明确时禁止输入")
                self.assertEqual(self.bridge.calls, [], "状态不明时不得发送原生动作")
        self.backend.read.return_value = stage([create_panel()])
        (self.root / "gui-character.lock").touch()
        with (self.root / "gui-character.lock").open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ClientError) as raised:
                create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(raised.exception.code, "input_busy", "同一运行目录的建角锁应互斥")

    def test_create_requires_runtime_identity_and_run_directory(self):
        self.show([create_panel()])
        self.runtime.run_id = "other"
        with self.assertRaises(ClientError) as raised:
            create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(raised.exception.code, "gui_character_identity_unconfirmed", "运行实例身份不符时禁止输入")
        self.runtime.run_id = RUN
        other = self.root / "other-run"
        other.mkdir()
        self.runtime.run_dir = other
        with self.assertRaises(ClientError) as raised:
            create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(raised.exception.code, "gui_character_identity_unconfirmed", "运行目录不符时禁止输入")

    def test_create_rejects_non_positive_timeout(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ClientError) as raised:
                    create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=timeout)
                self.assertEqual(raised.exception.code, "usage", "建角等待时间须为正有限数")

    def test_create_existing_attempt_cannot_be_replayed(self):
        record = self.record()
        with self.assertRaises(ClientError) as raised:
            create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(raised.exception.code, "gui_character_already_attempted", "已有建角尝试时禁止重发")
        self.assertEqual(raised.exception.details["request_id"], record["request_id"])
        (self.root / "gui-character-attempt.json").write_text("not-json", encoding="utf-8")
        with self.assertRaises(ClientError) as raised:
            create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(raised.exception.code, "gui_character_state_unknown", "尝试记录不可读取时禁止重发")

    def test_native_rejection_maps_to_unknown_without_replay(self):
        self.install_creation_sequence()
        self.bridge.rejected_actions = {"check_name"}
        result = create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(result["status"], "unknown", "原生桥拒绝动作时结果保持未知")
        self.assertEqual(result["reason"], "gui_native_action_rejected", "应保留原生拒绝原因")
        self.assertEqual(
            self.bridge.calls,
            [
                ("ui_button", PANEL_ADDRESS, "1001"),
                ("ui_button", CATEGORY_ADDRESS, "1003"),
                ("check_name", NAME_ADDRESS, b"Example"),
            ],
            "原生拒绝后不得重放任何动作",
        )
        self.assertTrue((self.root / "gui-character-attempt.json").exists(), "拒绝前已持久化建角尝试")

    def test_mid_flow_identity_change_maps_to_unknown(self):
        self.install_creation_sequence()

        def change_runtime(action, *arguments):
            if action == "ui_button" and arguments == (PANEL_ADDRESS, "1001"):
                self.runtime.run_id = "other"

        self.bridge.on_action = change_runtime
        result = create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(result["status"], "unknown", "流程中实例身份变化时结果保持未知")
        self.assertEqual(result["reason"], "gui_character_state_unknown", "应保留实例身份变化原因")
        self.assertEqual(self.bridge.calls, [("ui_button", PANEL_ADDRESS, "1001")], "身份变化后不得继续发送动作")

    def test_unexpected_step_result_maps_to_unknown(self):
        self.show([create_panel()])
        record_path = self.root / "gui-character-attempt.json"
        with patch("beidou_pilot.gui_character._open_creation", return_value={"status": "unknown", "reason": "next_page_unconfirmed"}):
            result = create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(result["status"], "unknown", "步骤未达预期时结果保持未知")
        self.assertEqual(result["reason"], "next_page_unconfirmed")
        self.assertTrue(record_path.exists(), "失败前仍应保留建角尝试记录")
        self.assertEqual(self.bridge.calls, [], "步骤失败后不得发送后续动作")

    def test_missing_final_marker_is_operation_unconfirmed(self):
        self.show([create_panel()])
        with (
            patch("beidou_pilot.gui_character._open_creation", return_value={"status": "category_page"}),
            patch("beidou_pilot.gui_character._navigate_category", return_value={"status": "name_page"}),
            patch("beidou_pilot.gui_character._submit_name", return_value={"status": "appearance_page"}),
            patch("beidou_pilot.gui_character._set_gender", return_value={"status": "matched"}),
            patch("beidou_pilot.gui_character._apply_appearance", return_value={"status": "matched"}),
            patch("beidou_pilot.gui_character._submit_creation", return_value={"status": "unknown"}),
        ):
            result = create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(result["status"], "unknown", "最终确认回执未落盘时结果保持未知")
        self.assertEqual(result["reason"], "final_dispatch_unconfirmed", "缺少最终回执应明确标记为派发未确认")
        self.assertTrue(result["request_id"])

    def test_oserror_during_step_is_operation_unconfirmed(self):
        self.show([create_panel()])
        with patch("beidou_pilot.gui_character._open_creation", side_effect=OSError("simulated crash")):
            result = create_once(self.backend, PARAMS, directory=self.root, instance_id=INSTANCE, run_id=RUN, timeout=5)
        self.assertEqual(result["status"], "unknown", "步骤执行异常时结果保持未知")
        self.assertEqual(result["reason"], "operation_unconfirmed")
        self.assertEqual(self.bridge.calls, [])


class GuiCharacterSupportedParametersTest(unittest.TestCase):
    def test_only_ascii_named_adventurer_is_supported(self):
        require_supported_creation(PARAMS)
        require_supported_creation(CharacterCreation("Z" * 12, 1, 0, 0, 0, 0, 0, 0, 0, 0, False))
        for params, code in (
            (CharacterCreation("Example", 2, *RAW, True), "unsupported_capability"),
            (CharacterCreation("中文", 1, *RAW, True), "unsupported_capability"),
            (CharacterCreation("Example\x7f", 1, *RAW, True), "unsupported_capability"),
            (CharacterCreation("", 1, *RAW, True), "character_creation_invalid"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(ClientError) as raised:
                    require_supported_creation(params)
                self.assertEqual(raised.exception.code, code, "不支持的建角参数应显式拒绝")


if __name__ == "__main__":
    unittest.main()
