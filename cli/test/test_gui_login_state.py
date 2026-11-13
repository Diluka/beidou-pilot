"""GUI 账号登录原生动作状态机的离线合同；不证明真实客户端页面识别或实际登录结果。"""

import base64
import fcntl
import json
import shutil
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from beidou_pilot.bridge import BridgeClient, require_input_idle
from beidou_pilot.errors import ClientError
from beidou_pilot.gui_login import _channel_ready, _page, _window, execute
from beidou_pilot.instances import InstancePaths
from beidou_pilot.profile import AccountProfile

INSTANCE = "instance"
RUN_ID = "run"
MISSING = object()

MANAGER = ("0xb3f13c", "0xb3f0f0", "0xb3f0ec")
SIDE_PANEL = ("0xaf7168", "0xaf711c", "0xaf7118")
LOGIN_FORM = ("0xaf7940", "0xaf78f4", "0xaf78f0")
TERMS_PAGE = ("0xaf79c8", "0xaf797c", "0xaf7978")
GENDER_PAGE = ("0xaf7298", "0xaf724c", "0xaf7248")
WORLD_PANEL = ("0xaf7a90", "0xaf7a44", "0xaf7a40")
CHANNEL_PANEL = ("0xaf7b4c", "0xaf7b00", "0xaf7afc")
SIDE_BUTTONS = ("0xaf70d0", "0xaf7084", "0xaf7080")

CHANNEL_PANEL_READY = {"count": 2, "channels": [{"index": 0, "channel": 1}, {"index": 1, "channel": 2}]}


def window(vtables, *, width=None, height=None, address="0x1"):
    value = {"vtables": list(vtables), "address": address}
    if width is not None:
        value.update(width=width, height=height)
    return value


def login_windows():
    return [
        window(MANAGER, width=1280, height=720, address="manager"),
        window(SIDE_PANEL, width=125, height=352, address="sidebar"),
        window(LOGIN_FORM, width=330, height=180, address="login"),
    ]


def terms_windows():
    return login_windows() + [window(TERMS_PAGE, width=431, height=426, address="terms")]


def gender_windows():
    return login_windows() + [window(GENDER_PAGE, width=354, height=259, address="gender")]


def world_windows():
    return [
        window(MANAGER, width=1280, height=720, address="manager"),
        window(SIDE_PANEL, width=125, height=352, address="sidebar"),
        window(WORLD_PANEL, width=400, height=100, address="world"),
        window(SIDE_BUTTONS, address="side-buttons"),
    ]


def channel_windows():
    return world_windows() + [window(CHANNEL_PANEL, width=448, height=253, address="channel")]


def login_state(**overrides):
    state = {
        "request_pending": False,
        "transition_pending": False,
        "raw_world_selection": {"count": 1, "selected_index": 0, "raw_world_id": 0},
        "characters_available": False,
        "characters": None,
    }
    state.update(overrides)
    return state


def stage(name="LOGIN", windows=(), login=MISSING, **extra):
    value = {
        "instance_id": INSTANCE,
        "client": {"run_id": RUN_ID},
        "unavailable": [],
        "stage": name,
        "windows": list(windows),
        "login": login_state() if login is MISSING else login,
    }
    value.update(extra)
    return value


def credentials_stage():
    return stage("LOGIN", login_windows())


def terms_stage():
    return stage("LOGIN", terms_windows())


def gender_stage():
    return stage("LOGIN", gender_windows())


def world_stage(**overrides):
    return stage("WORLD_SELECT", world_windows(), login_state(**overrides))


def channel_stage(panel=MISSING, **overrides):
    value = stage("CHANNEL_SELECT", channel_windows(), login_state(**overrides))
    value["channel_panel"] = CHANNEL_PANEL_READY if panel is MISSING else panel
    return value


def characters_stage():
    return stage(
        "CHARACTER_SELECT",
        (),
        login_state(characters_available=True, characters=[{"id": 7, "name": "Hero"}]),
    )


class GuiLoginPageClassificationTests(unittest.TestCase):
    """页面分类只依赖精确窗口集合与登录原始选择。"""

    def test_login_form_only_classifies_credentials(self):
        self.assertEqual(_page(credentials_stage()), "credentials", "仅登录表单窗口应识别为账号页")

    def test_terms_page_requires_exact_window_set(self):
        self.assertEqual(_page(terms_stage()), "terms", "协议窗口集合应识别为协议页")
        shuffled = stage("LOGIN", list(reversed(terms_windows())))
        self.assertEqual(_page(shuffled), "terms", "窗口顺序不影响集合匹配")
        extra = stage("LOGIN", terms_windows() + [window(("0xdead",))])
        self.assertIsNone(_page(extra), "协议页出现多余窗口时不可操作")
        missing = stage("LOGIN", [entry for entry in terms_windows() if entry["address"] != "manager"])
        self.assertIsNone(_page(missing), "协议窗口集合缺少窗口时不可操作")
        both = stage(
            "LOGIN",
            login_windows()
            + [window(TERMS_PAGE, width=431, height=426, address="terms"),
               window(GENDER_PAGE, width=354, height=259, address="gender")],
        )
        self.assertIsNone(_page(both), "协议页与性别页窗口并存时不可操作")

    def test_gender_page_requires_exact_window_set(self):
        self.assertEqual(_page(gender_stage()), "gender", "性别窗口集合应识别为性别页")
        extra = stage("LOGIN", gender_windows() + [window(("0xdead",))])
        self.assertIsNone(_page(extra), "性别页出现多余窗口时不可操作")
        missing = stage("LOGIN", [entry for entry in gender_windows() if entry["address"] != "sidebar"])
        self.assertIsNone(_page(missing), "性别窗口集合缺少窗口时不可操作")

    def test_pending_login_flags_are_not_operable(self):
        for overrides in (
            {"request_pending": True},
            {"request_pending": None},
            {"transition_pending": True},
            {"transition_pending": None},
        ):
            with self.subTest(overrides=overrides):
                value = stage("LOGIN", terms_windows(), login_state(**overrides))
                self.assertIsNone(_page(value), "登录处理中或状态不明时不应发送动作")

    def test_missing_login_or_invalid_windows_is_not_operable(self):
        self.assertIsNone(_page(stage("LOGIN", login_windows(), login=None)), "缺少登录状态时不可分类")
        for windows in (None, {"vtables": []}, [{"vtables": []}, "bad"]):
            with self.subTest(windows=windows):
                value = stage("LOGIN", login_windows())
                value["windows"] = windows
                with self.assertRaises(ClientError) as error:
                    _page(value)
                self.assertEqual(error.exception.code, "gui_login_state_unknown", "窗口清单不可用时须停止")

    def test_world_select_requires_exact_window_set_and_world_zero(self):
        self.assertEqual(_page(world_stage()), "world", "世界选择窗口集合应识别为世界页")
        self.assertIsNone(_page(stage("WORLD_SELECT", world_windows()[:-1])), "世界页缺少侧栏按钮时不可操作")
        self.assertIsNone(_page(stage("WORLD_SELECT", world_windows() + [window(("0xdead",))])),
                          "世界页出现多余窗口时不可操作")
        invalid = (
            None,
            {"count": 2, "selected_index": 0, "raw_world_id": 0},
            {"count": True, "selected_index": 0, "raw_world_id": 0},
            {"count": 1, "selected_index": -1, "raw_world_id": 0},
            {"count": 1, "selected_index": True, "raw_world_id": 0},
            {"count": 1, "selected_index": 0, "raw_world_id": None},
            {"count": 1, "selected_index": 0, "raw_world_id": 1},
        )
        for selection in invalid:
            with self.subTest(selection=selection):
                value = stage("WORLD_SELECT", world_windows(), login_state(raw_world_selection=selection))
                self.assertIsNone(_page(value), "世界原始选择不是唯一 0 号世界时不可操作")

    def test_channel_select_requires_exact_window_set(self):
        self.assertEqual(_page(channel_stage()), "channel", "频道窗口集合应识别频道页")
        self.assertIsNone(_page(stage("CHANNEL_SELECT", channel_windows()[:-1])), "频道页缺少频道窗口时不可操作")
        self.assertIsNone(_page(stage("CHANNEL_SELECT", channel_windows() + [window(("0xdead",))])),
                          "频道页出现多余窗口时不可操作")

    def test_other_stages_are_not_actionable(self):
        for name in ("CHARACTER_SELECT", "TRANSITION", "LOBBY"):
            with self.subTest(name=name):
                self.assertIsNone(_page(stage(name, ())), "非登录界面阶段不应产生登录动作")

    def test_window_lookup_requires_unique_native_size_and_address(self):
        self.assertEqual(_window(terms_stage(), TERMS_PAGE, width=431, height=426), "terms",
                         "窗口签名唯一且尺寸匹配时返回原生地址")
        wrong_width = stage("LOGIN", login_windows() + [window(TERMS_PAGE, width=430, height=426, address="terms")])
        wrong_height = stage("LOGIN", login_windows() + [window(TERMS_PAGE, width=431, height=425, address="terms")])
        boolean_size = stage("LOGIN", login_windows() + [window(TERMS_PAGE, width=True, height=426, address="terms")])
        duplicate = stage(
            "LOGIN",
            login_windows()
            + [window(TERMS_PAGE, width=431, height=426, address="terms"),
               window(TERMS_PAGE, width=431, height=426, address="terms-2")],
        )
        without_address = stage("LOGIN", login_windows() + [window(TERMS_PAGE, width=431, height=426, address="terms")])
        without_address["windows"][-1].pop("address")
        invalid_address = stage("LOGIN", login_windows() + [window(TERMS_PAGE, width=431, height=426, address=5)])
        cases = (
            ("缺少目标窗口", stage("LOGIN", login_windows())),
            ("宽度不符", wrong_width),
            ("高度不符", wrong_height),
            ("布尔尺寸", boolean_size),
            ("窗口重复", duplicate),
            ("地址缺失", without_address),
            ("地址类型错误", invalid_address),
        )
        for message, value in cases:
            with self.subTest(message=message), self.assertRaises(ClientError) as error:
                _window(value, TERMS_PAGE, width=431, height=426)
            self.assertEqual(error.exception.code, "gui_login_state_unknown", message)

    def test_window_lookup_checks_each_actionable_page_size(self):
        self.assertEqual(_window(credentials_stage(), LOGIN_FORM, width=330, height=180), "login")
        self.assertEqual(_window(terms_stage(), TERMS_PAGE, width=431, height=426), "terms")
        self.assertEqual(_window(gender_stage(), GENDER_PAGE, width=354, height=259), "gender")
        self.assertEqual(_window(world_stage(), WORLD_PANEL, width=400, height=100), "world")
        self.assertEqual(_window(channel_stage(), CHANNEL_PANEL, width=448, height=253), "channel")
        for message, value, signature, width, height in (
            ("频道窗口尺寸不符", channel_stage(), CHANNEL_PANEL, 400, 100),
            ("世界窗口尺寸不符", world_stage(), WORLD_PANEL, 448, 253),
            ("账号窗口缺少尺寸", credentials_stage(), LOGIN_FORM, None, None),
        ):
            with self.subTest(message=message):
                if width is None:
                    for entry in value["windows"]:
                        if entry["vtables"] == list(signature):
                            entry.pop("width")
                            entry.pop("height")
                with self.assertRaises(ClientError) as error:
                    _window(value, signature, width=330 if width is None else width,
                            height=180 if height is None else height)
                self.assertEqual(error.exception.code, "gui_login_state_unknown", message)

    def test_channel_ready_requires_matching_one_based_channel_and_index(self):
        profile = AccountProfile("user", "secret", 0, 0)
        self.assertTrue(_channel_ready(channel_stage(), profile), "频道面板给出 1 基频道号且索引一致时就绪")
        wrong_index = channel_stage(panel={"count": 2, "channels": [
            {"index": 1, "channel": 1}, {"index": 0, "channel": 2}]})
        self.assertFalse(_channel_ready(wrong_index, profile), "频道索引与 0 基频道不一致时不能操作")
        wrong_channel = channel_stage(panel={"count": 2, "channels": [
            {"index": 0, "channel": 2}, {"index": 1, "channel": 3}]})
        self.assertFalse(_channel_ready(wrong_channel, profile), "目标 0 基频道未出现在面板时不能操作")
        unmatched_count = channel_stage(panel={"count": 3, "channels": [{"index": 0, "channel": 1}]})
        self.assertFalse(_channel_ready(unmatched_count, profile), "面板数量与频道列表不一致时不能操作")
        duplicate = channel_stage(panel={"count": 2, "channels": [
            {"index": 0, "channel": 1}, {"index": 0, "channel": 1}]})
        self.assertFalse(_channel_ready(duplicate, profile), "目标频道重复出现时不能操作")
        for panel in (None, {"count": True, "channels": [{"index": 0, "channel": 1}]},
                      {"count": 0, "channels": []}, {"count": 21, "channels": [{}] * 21}):
            with self.subTest(panel=panel):
                self.assertFalse(_channel_ready(channel_stage(panel=panel), profile),
                                 "频道面板数量或类型异常时不能操作")
        self.assertFalse(_channel_ready(stage("LOGIN", channel_windows()), profile), "非频道选择阶段不能操作")
        boundary = channel_stage(panel={"count": 20, "channels": [
            {"index": index, "channel": index + 1} for index in range(20)]})
        self.assertTrue(_channel_ready(boundary, AccountProfile("user", "secret", 0, 19)),
                        "第 20 频道（0 基 19）应为合法边界")


class FakeClock:
    """可控单调时钟，sleep 推进期限而不真实等待。"""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class GuiLoginExecuteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.backend = Mock(name="backend")
        self.backend.name = "beidou"
        self.backend.root = self.root
        self.backend.instance = "default"
        self.backend.read.return_value = credentials_stage()
        self.profile = AccountProfile("测试", "secret")
        self.clock = FakeClock()
        patchers = (
            patch("beidou_pilot.gui_login.time", self.clock),
            patch("beidou_pilot.gui_login.load_runtime", side_effect=lambda *arguments: self.runtime),
            patch("beidou_pilot.gui_login.BridgeClient"),
            patch("beidou_pilot.gui_login.require_input_idle"),
        )
        mocks = []
        for patcher in patchers:
            mocks.append(patcher.start())
            self.addCleanup(patcher.stop)
        self.load_runtime, self.bridge_factory, self.require_idle = mocks[1], mocks[2], mocks[3]
        self.bridge = self.bridge_factory.return_value
        self.reset_run()

    def reset_run(self):
        self.clock.now = 0.0
        run_dir = self.root / ("run-" + uuid.uuid4().hex)
        run_dir.mkdir()
        self.runtime = SimpleNamespace(
            running=True, run_id=RUN_ID, run_dir=run_dir, character_id=None, world=0, channel=0
        )
        self.bridge.reset_mock()
        self.bridge.snapshot.return_value = {"instance_id": INSTANCE, "run_id": RUN_ID}
        self.bridge.login_action.return_value = {"status": "dispatched"}
        self.require_idle.reset_mock()
        self.require_idle.side_effect = None
        self.load_runtime.side_effect = lambda *arguments: self.runtime
        self.load_runtime.reset_mock()

    def run_login(self, profile=None, **options):
        values = {"instance_id": INSTANCE, "run_id": RUN_ID, "accept_terms": True, "gender": "female"}
        values.update(options)
        return execute(self.backend, self.profile if profile is None else profile, **values)

    def login_sequence(self):
        return [
            terms_stage(), terms_stage(),
            credentials_stage(), credentials_stage(),
            gender_stage(), gender_stage(),
            world_stage(), world_stage(),
            channel_stage(), channel_stage(),
            characters_stage(), characters_stage(),
        ]

    def test_terms_credentials_gender_world_channel_reach_character_list(self):
        for gender, encoded in (("male", "0"), ("female", "1")):
            with self.subTest(gender=gender):
                self.reset_run()
                self.backend.read.side_effect = self.login_sequence()
                result = self.run_login(gender=gender)
                self.assertEqual(result["phase"], "character_list", "正常序列完成后应返回角色列表阶段")
                self.assertEqual(result["characters"], [{"id": 7, "name": "Hero"}], "角色列表原样投影")
                self.assertEqual((result["instance_id"], result["run_id"]), (INSTANCE, RUN_ID),
                                 "结果须保留本次实例身份")
                calls = self.bridge.login_action.call_args_list
                self.assertEqual(
                    [call.args[0] for call in calls],
                    ["accept_terms", "submit_login", "select_gender", "select_world", "select_channel"],
                    "登录动作须按协议、账号、性别、世界、频道顺序各发一次",
                )
                self.assertEqual(calls[0].args[1:], ("terms",), "协议动作只带协议窗口原生地址")
                self.assertEqual(calls[1].args[1:], ("login", "测试".encode("cp936"), b"secret"),
                                 "账号动作按客户端字符集传用户名密码字节")
                self.assertEqual(calls[2].args[1:], ("gender", encoded), "性别动作使用 0/1 原生选择值")
                self.assertEqual(calls[3].args[1:], ("world", "0"), "世界动作带世界窗口地址与 0 基世界索引")
                self.assertEqual(calls[4].args[1:], ("0", "channel"),
                                 "频道动作带 0 基频道索引与频道窗口原生地址")
                for call in calls:
                    self.assertEqual(call.kwargs, {"timeout": 2.0}, "每次原生动作使用默认两秒等待")
                markers = (
                    "gui-terms-submitted",
                    "gui-login-submitted",
                    "gui-gender-submitted",
                    "gui-world-submitted",
                    "gui-channel-submitted",
                )
                for marker in markers:
                    path = self.runtime.run_dir / marker
                    self.assertEqual(path.read_text(), "attempted\n", f"{marker} 须记录一次性尝试")
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600, f"{marker} 须为私有文件")
                self.assertGreaterEqual(self.require_idle.call_count, 6, "每次动作前后都须核对输入空闲")
                self.require_idle.assert_any_call(self.bridge, INSTANCE, RUN_ID)
                self.assertGreaterEqual(self.bridge.snapshot.call_count, 6, "每轮都须核对原生桥身份")

    def test_terms_page_requires_explicit_authorization(self):
        self.backend.read.return_value = terms_stage()
        with self.assertRaises(ClientError) as error:
            self.run_login(accept_terms=False)
        self.assertEqual(error.exception.code, "gui_terms_not_authorized", "未授权同意协议时不得发送原生动作")
        self.bridge.login_action.assert_not_called()
        self.assertFalse((self.runtime.run_dir / "gui-terms-submitted").exists(), "未授权时不应创建一次性标记")

    def test_existing_character_list_returns_without_native_actions(self):
        self.backend.read.return_value = characters_stage()
        result = self.run_login()
        self.assertEqual(result["phase"], "character_list", "已有角色列表可直接观察返回")
        self.assertEqual(result["characters"], [{"id": 7, "name": "Hero"}])
        self.bridge.login_action.assert_not_called()

    def test_transition_or_pending_state_waits_without_input(self):
        for message, value in (
            ("转场阶段", stage("TRANSITION", ())),
            ("登录请求处理中", stage("LOGIN", terms_windows(), login_state(request_pending=True))),
            ("转场处理中", stage("LOGIN", terms_windows(), login_state(transition_pending=True))),
        ):
            with self.subTest(message=message):
                self.reset_run()
                self.backend.read.return_value = value
                with self.assertRaises(ClientError) as error:
                    self.run_login(timeout=0.25)
                self.assertEqual(error.exception.code, "gui_login_timeout", "等待期满而未输入时应超时")
                self.bridge.login_action.assert_not_called()

    def test_same_page_repeats_are_not_replayed_before_timeout(self):
        self.backend.read.return_value = terms_stage()
        with self.assertRaises(ClientError) as error:
            self.run_login(timeout=0.25)
        self.assertEqual(error.exception.code, "gui_login_timeout", "页面未变化时应等待而不是重放")
        self.assertEqual(self.bridge.login_action.call_count, 1, "同一页面未变化前不得重发动作")
        self.assertTrue((self.runtime.run_dir / "gui-terms-submitted").exists(), "已发动作须保留一次性标记")

    def test_page_regression_blocks_replay(self):
        self.backend.read.side_effect = [terms_stage(), gender_stage(), terms_stage(), terms_stage()]
        with self.assertRaises(ClientError) as error:
            self.run_login()
        self.assertEqual(error.exception.code, "gui_login_action_unknown", "登录页面回退时须停止且不重放")
        self.assertIn("回退", error.exception.message)
        self.assertEqual(
            [call.args[0] for call in self.bridge.login_action.call_args_list],
            ["accept_terms", "select_gender"],
            "回退前只允许已按顺序发出的动作",
        )

    def test_existing_marker_blocks_replay(self):
        cases = (
            ("gui-terms-submitted", terms_stage()),
            ("gui-login-submitted", credentials_stage()),
            ("gui-gender-submitted", gender_stage()),
            ("gui-world-submitted", world_stage()),
            ("gui-channel-submitted", channel_stage()),
        )
        for marker, value in cases:
            with self.subTest(marker=marker):
                self.reset_run()
                (self.runtime.run_dir / marker).write_text("attempted\n")
                self.backend.read.return_value = value
                with self.assertRaises(ClientError) as error:
                    self.run_login()
                self.assertEqual(error.exception.code, "gui_login_action_unknown",
                                 "同一运行已尝试的登录动作禁止重放")
                self.bridge.login_action.assert_not_called()

    def test_rejected_native_action_is_not_replayed(self):
        self.backend.read.return_value = terms_stage()
        self.bridge.login_action.side_effect = ClientError(
            "gui_native_action_rejected", "原生桥拒绝", {"reason": "denied"}
        )
        with self.assertRaises(ClientError) as error:
            self.run_login()
        self.assertEqual(error.exception.code, "gui_native_action_rejected", "原生拒绝语义须原样透出")
        self.assertEqual(error.exception.details, {"reason": "denied"}, "拒绝详情不得伪造成功")
        self.assertTrue((self.runtime.run_dir / "gui-terms-submitted").exists(), "拒绝后仍须保留一次性标记")
        with self.assertRaises(ClientError) as retry:
            self.run_login()
        self.assertEqual(retry.exception.code, "gui_login_action_unknown", "被拒绝的动作不得重放")
        self.assertEqual(self.bridge.login_action.call_count, 1, "拒绝后不得再次发布原生动作")

    def test_runtime_identity_change_after_action_stops(self):
        self.backend.read.return_value = terms_stage()
        changed = SimpleNamespace(
            running=True, run_id="other", run_dir=self.runtime.run_dir, character_id=None, world=0, channel=0
        )
        self.load_runtime.side_effect = [self.runtime, self.runtime, changed]
        with self.assertRaises(ClientError) as error:
            self.run_login()
        self.assertEqual(error.exception.code, "gui_login_identity_unconfirmed",
                         "运行实例身份变化后须停止输入")
        self.assertEqual(self.bridge.login_action.call_count, 1, "身份变化前只允许已发出的动作")
        self.assertTrue((self.runtime.run_dir / "gui-terms-submitted").exists())

    def test_native_bridge_identity_change_after_action_stops(self):
        self.backend.read.return_value = terms_stage()
        self.bridge.snapshot.side_effect = [
            {"instance_id": INSTANCE, "run_id": RUN_ID},
            {"instance_id": "other", "run_id": RUN_ID},
        ]
        with self.assertRaises(ClientError) as error:
            self.run_login()
        self.assertEqual(error.exception.code, "gui_login_identity_unconfirmed",
                         "原生桥身份变化后须停止输入")
        self.assertEqual(self.bridge.login_action.call_count, 1)

    def test_native_bridge_identity_mismatch_never_observes_or_acts(self):
        for message, state in (
            ("实例身份不符", {"instance_id": "other", "run_id": RUN_ID}),
            ("运行身份不符", {"instance_id": INSTANCE, "run_id": "other"}),
            ("身份字段缺失", {"instance_id": INSTANCE}),
            ("快照为空", {}),
        ):
            with self.subTest(message=message):
                self.reset_run()
                self.bridge.snapshot.return_value = state
                with self.assertRaises(ClientError) as error:
                    self.run_login()
                self.assertEqual(error.exception.code, "gui_login_identity_unconfirmed", message)
                self.backend.read.assert_not_called()
                self.require_idle.assert_not_called()
                self.bridge.login_action.assert_not_called()

    def test_non_beidou_backend_never_uses_native_login_actions(self):
        self.backend.name = "headless"
        with self.assertRaises(ClientError) as error:
            self.run_login()
        self.assertEqual(error.exception.code, "gui_login_identity_unconfirmed",
                         "原生 GUI 登录动作只允许北斗图形端")
        self.bridge_factory.assert_not_called()
        self.bridge.login_action.assert_not_called()

    def test_busy_input_stops_before_observation(self):
        self.require_idle.side_effect = ClientError("input_busy", "脚本占用输入")
        self.backend.read.return_value = terms_stage()
        with self.assertRaises(ClientError) as error:
            self.run_login()
        self.assertEqual(error.exception.code, "input_busy", "输入不空闲时须停止")
        self.require_idle.assert_called_once_with(self.bridge, INSTANCE, RUN_ID)
        self.backend.read.assert_not_called()
        self.bridge.login_action.assert_not_called()

    def test_stale_or_unknown_stage_identity_stops_without_action(self):
        mutations = (
            ("实例身份不符", lambda value: value.update(instance_id="other")),
            ("客户端运行身份不符", lambda value: value.update(client={"run_id": "other"})),
            ("客户端观察缺失", lambda value: value.update(client=None)),
            ("观察不可用", lambda value: value.update(unavailable=["dialog"])),
            ("登录状态缺失", lambda value: value.update(login=None)),
            ("阶段未知", lambda value: value.update(stage="LOBBY")),
        )
        for message, mutate in mutations:
            with self.subTest(message=message):
                self.reset_run()
                value = terms_stage()
                mutate(value)
                self.backend.read.return_value = value
                with self.assertRaises(ClientError) as error:
                    self.run_login()
                self.assertEqual(error.exception.code, "gui_login_state_unknown", message)
                self.assertEqual(self.require_idle.call_count, 1, "身份确认后才核对输入空闲")
                self.bridge.login_action.assert_not_called()

    def test_unknown_extra_window_or_unready_channel_is_not_operable(self):
        invalid_world = stage(
            "WORLD_SELECT",
            world_windows(),
            login_state(raw_world_selection={"count": 2, "selected_index": 0, "raw_world_id": 0}),
        )
        for message, value in (
            ("多余窗口", stage("LOGIN", login_windows() + [window(("0xdead",))])),
            ("窗口为空", stage("LOGIN", ())),
            ("世界原始选择异常", invalid_world),
            ("频道面板未就绪", channel_stage(panel=None)),
        ):
            with self.subTest(message=message):
                self.reset_run()
                self.backend.read.return_value = value
                with self.assertRaises(ClientError) as error:
                    self.run_login()
                self.assertEqual(error.exception.code, "gui_login_state_unknown", message)
                self.bridge.login_action.assert_not_called()

    def test_world_or_channel_outside_supported_range_is_rejected(self):
        for message, profile, runtime_changes in (
            ("其他世界", AccountProfile("user", "secret", 1, 0), {"world": 1}),
            ("频道超过 20", AccountProfile("user", "secret", 0, 20), {"channel": 20}),
            ("负频道", AccountProfile("user", "secret", 0, -1), {"channel": -1}),
        ):
            with self.subTest(message=message):
                self.reset_run()
                for field, value in runtime_changes.items():
                    setattr(self.runtime, field, value)
                with self.assertRaises(ClientError) as error:
                    self.run_login(profile=profile)
                self.assertEqual(error.exception.code, "unsupported_capability", message)
                self.backend.read.assert_not_called()
                self.bridge.login_action.assert_not_called()

    def test_runtime_credentials_must_match_profile_and_have_no_character(self):
        for message, changes in (
            ("进程已退出", {"running": False}),
            ("运行身份变化", {"run_id": "other"}),
            ("已有角色", {"character_id": 7}),
            ("世界与账号文件不一致", {"world": 1}),
            ("频道与账号文件不一致", {"channel": 1}),
        ):
            with self.subTest(message=message):
                self.reset_run()
                for field, value in changes.items():
                    setattr(self.runtime, field, value)
                with self.assertRaises(ClientError) as error:
                    self.run_login()
                self.assertEqual(error.exception.code, "gui_login_identity_unconfirmed", message)
                self.backend.read.assert_not_called()
                self.bridge.login_action.assert_not_called()

    def test_invalid_options_are_rejected_before_observation(self):
        calls = (
            ("等待时间过短", {"timeout": 0}),
            ("等待时间过长", {"timeout": 181}),
            ("等待时间非有限", {"timeout": float("nan")}),
            ("性别缺失", {"gender": None}),
            ("性别未知", {"gender": "other"}),
            ("期限为布尔", {"deadline": True}),
            ("期限非有限", {"deadline": float("inf")}),
        )
        for message, options in calls:
            with self.subTest(message=message):
                with self.assertRaises(ClientError) as error:
                    self.run_login(**options)
                self.assertEqual(error.exception.code, "invalid_login_options", message)
        self.load_runtime.assert_not_called()
        self.backend.read.assert_not_called()
        self.bridge.login_action.assert_not_called()

    def test_elapsed_external_deadline_never_locks_or_observes(self):
        self.clock.now = 5.0
        with self.assertRaises(ClientError) as error:
            self.run_login(deadline=5.0)
        self.assertEqual(error.exception.code, "gui_login_timeout", "准备阶段已过期须停止")
        self.assertFalse((self.runtime.run_dir / "gui-login.lock").exists(), "超时不应创建登录锁")
        self.backend.read.assert_not_called()
        self.bridge.login_action.assert_not_called()

    def test_external_deadline_is_forwarded_without_reset(self):
        self.clock.now = 1.0
        with patch("beidou_pilot.gui_login._execute_locked", return_value={"phase": "character_list"}) as locked:
            result = self.run_login(deadline=8.0)
        self.assertEqual(result["phase"], "character_list")
        self.assertEqual(locked.call_args.kwargs["deadline"], 8.0, "外部绝对期限不得被超时参数重置")

    def test_concurrent_login_never_observes_or_acts(self):
        lock_path = self.runtime.run_dir / "gui-login.lock"
        with lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ClientError) as error:
                self.run_login()
        self.assertEqual(error.exception.code, "gui_login_busy", "同一运行已有登录控制器时不得接管")
        self.backend.read.assert_not_called()
        self.bridge.login_action.assert_not_called()

    def test_unsupported_credentials_never_create_marker_or_action(self):
        self.backend.read.return_value = credentials_stage()
        with self.assertRaises(ClientError) as error:
            self.run_login(profile=AccountProfile("😀", "secret"))
        self.assertEqual(error.exception.code, "unsupported_credentials",
                         "账号字段超出客户端字符集时不得输入")
        self.bridge.login_action.assert_not_called()
        self.assertFalse((self.runtime.run_dir / "gui-login-submitted").exists(),
                         "编码失败前不应创建一次性标记")

    def test_incomplete_character_list_stops_as_unknown(self):
        self.backend.read.return_value = stage(
            "CHARACTER_SELECT", (), login_state(characters_available=False)
        )
        with self.assertRaises(ClientError) as error:
            self.run_login()
        self.assertEqual(error.exception.code, "gui_login_state_unknown",
                         "角色列表未就绪且无待处理状态时须停止")
        self.bridge.login_action.assert_not_called()

    def test_character_list_after_terms_alone_is_not_trusted(self):
        self.backend.read.side_effect = [terms_stage(), characters_stage(), characters_stage()]
        with self.assertRaises(ClientError) as error:
            self.run_login(timeout=0.25)
        self.assertEqual(error.exception.code, "gui_login_timeout",
                         "未完成世界与频道选择前出现的角色列表不能作为登录完成")
        self.assertEqual(self.bridge.login_action.call_count, 1)

    def test_channel_panel_not_ready_after_world_waits_without_replay(self):
        self.backend.read.side_effect = [
            world_stage(),
            channel_stage(panel=None),
            channel_stage(panel=None),
        ]
        with self.assertRaises(ClientError) as error:
            self.run_login(timeout=0.25)
        self.assertEqual(error.exception.code, "gui_login_timeout", "频道面板未就绪时应等待而非重发")
        self.assertEqual(self.bridge.login_action.call_count, 1, "世界动作之后不得重发")
        self.assertEqual(self.bridge.login_action.call_args.args[0], "select_world")


class RequireInputIdleTests(unittest.TestCase):
    def bridge(self, **overrides):
        state = {
            "instance_id": INSTANCE,
            "run_id": RUN_ID,
            "held_keys": [],
            "command": {"id": None, "status": "idle", "reason": None},
            "scripts": [{"status": "completed", "control_released": True}],
        }
        for key, value in overrides.items():
            if value is MISSING:
                state.pop(key)
            else:
                state[key] = value
        bridge = Mock(name="bridge")
        bridge.snapshot.return_value = state
        return bridge

    def test_released_sessions_and_idle_input_pass(self):
        require_input_idle(self.bridge(), INSTANCE, RUN_ID)
        require_input_idle(self.bridge(scripts=[]), INSTANCE, RUN_ID)
        require_input_idle(
            self.bridge(scripts=[{"status": "cancelled", "control_released": True},
                                 {"status": "rejected", "control_released": True}]),
            INSTANCE,
            RUN_ID,
        )

    def test_identity_change_is_rejected(self):
        for message, overrides in (("实例身份", {"instance_id": "other"}), ("运行身份", {"run_id": "other"})):
            with self.subTest(message=message), self.assertRaises(ClientError) as error:
                require_input_idle(self.bridge(**overrides), INSTANCE, RUN_ID)
            self.assertEqual(error.exception.code, "bridge_identity_changed", message)

    def test_active_or_unknown_input_ownership_is_rejected(self):
        cases = (
            ("脚本列表缺失", {"scripts": MISSING}),
            ("脚本列表无效", {"scripts": None}),
            ("脚本运行中", {"scripts": [{"status": "running", "control_released": False}]}),
            ("未确认释放", {"scripts": [{"status": "completed", "control_released": False}]}),
            ("缺少释放字段", {"scripts": [{"status": "completed"}]}),
            ("状态未知", {"scripts": [{"status": "unknown", "control_released": True}]}),
            ("命令运行中", {"command": {"id": "request", "status": "running", "reason": None}}),
            ("按键未释放", {"held_keys": [30]}),
        )
        for message, overrides in cases:
            with self.subTest(message=message), self.assertRaises(ClientError) as error:
                require_input_idle(self.bridge(**overrides), INSTANCE, RUN_ID)
            self.assertEqual(error.exception.code, "input_busy", message)


class FakeBridgeTime:
    """桥接动作等待用的可控时间；不真实睡眠。"""

    def __init__(self):
        self.now = None
        self.sleep_hook = None

    def monotonic(self):
        return time.monotonic() if self.now is None else self.now

    def sleep(self, seconds):
        if self.sleep_hook is not None:
            self.sleep_hook(seconds)
        elif self.now is not None:
            self.now += seconds


class LoginActionProtocolTests(unittest.TestCase):
    """BridgeClient.login_action 的文件协议合同，不启动客户端或 Docker。"""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = InstancePaths(self.root).bridge
        self.directory.mkdir(parents=True)
        self.bridge_state = {"instance_id": "native", "run_id": "run"}
        self.snapshot = self.enterContext(
            patch("beidou_pilot.bridge.BridgeClient.snapshot", return_value=self.bridge_state)
        )
        self.time = FakeBridgeTime()
        self.enterContext(patch("beidou_pilot.bridge.time", self.time))
        self.client = BridgeClient(self.root)

    def published(self):
        return (self.directory / "login-action.txt").read_text(encoding="ascii").split()

    def answer(self, **overrides):
        def write_result(seconds):
            fields = self.published()
            result = {
                "protocol": 1,
                "instance_id": "native",
                "run_id": "run",
                "request_id": fields[2],
                "action": fields[3],
                "status": "dispatched",
                "reason": None,
            }
            result.update(overrides)
            (self.directory / "login-action-result.json").write_text(json.dumps(result), encoding="utf-8")

        self.time.sleep_hook = write_result

    def test_publishes_one_request_with_three_encoded_arguments(self):
        self.answer()
        result = self.client.login_action("submit_login", "0xlogin", b"\xbe\xff", timeout=2)
        fields = self.published()
        self.assertEqual(len(fields), 7, "原生登录动作固定三个参数槽")
        self.assertEqual(fields[0], "1", "协议版本须为 1")
        self.assertEqual(fields[1], "native", "请求须绑定原生桥实例")
        self.assertRegex(fields[2], r"[0-9a-f]{32}", "请求 ID 须为十六进制 UUID")
        self.assertEqual(fields[3], "submit_login", "动作名原样发布")
        self.assertEqual(base64.b64decode(fields[4]), "0xlogin".encode("cp936"), "字符串参数按客户端字符集编码")
        self.assertEqual(base64.b64decode(fields[5]), b"\xbe\xff", "字节参数原样 Base64 发布")
        self.assertEqual(fields[6], "-", "缺少的参数槽使用占位符")
        self.assertEqual(result["status"], "dispatched", "dispatched 结果须原样返回")
        self.assertEqual(result["request_id"], fields[2], "返回结果须属于本次请求")
        self.assertEqual(list(self.directory.glob("login-action-*.tmp")), [], "发布后不保留临时文件")

    def test_string_arguments_use_client_charset(self):
        self.answer()
        self.client.login_action("submit_login", "账号", "密码")
        fields = self.published()
        self.assertEqual(base64.b64decode(fields[4]), "账号".encode("cp936"), "账号按客户端字符集编码")
        self.assertEqual(base64.b64decode(fields[5]), "密码".encode("cp936"), "密码按客户端字符集编码")
        self.assertEqual(fields[6], "-")

    def test_waits_for_matching_request_id_and_ignores_others(self):
        seen = []

        def respond(seconds):
            fields = self.published()
            if not seen:
                seen.append(fields[2])
                (self.directory / "login-action-result.json").write_text(json.dumps({
                    "protocol": 1, "instance_id": "native", "run_id": "run",
                    "request_id": "a" * 32, "action": "select_world",
                    "status": "dispatched", "reason": None,
                }), encoding="utf-8")
                return
            (self.directory / "login-action-result.json").write_text(json.dumps({
                "protocol": 1, "instance_id": "native", "run_id": "run",
                "request_id": fields[2], "action": fields[3],
                "status": "dispatched", "reason": None,
            }), encoding="utf-8")

        self.time.sleep_hook = respond
        result = self.client.login_action("select_world", "0xworld", "0")
        self.assertEqual(result["request_id"], self.published()[2], "只接受本次请求 ID 的结果")
        self.assertEqual(result["action"], "select_world")

    def test_invalid_matching_result_stops_with_protocol_error(self):
        cases = (
            ("实例身份不符", {"instance_id": "other"}),
            ("运行身份不符", {"run_id": "other"}),
            ("动作不符", {"action": "select_gender"}),
            ("协议版本不符", {"protocol": 2}),
            ("状态未知", {"status": "accepted"}),
            ("原因不是字符串", {"reason": 42}),
        )
        for message, overrides in cases:
            with self.subTest(message=message):
                self.answer(**overrides)
                with self.assertRaises(ClientError) as error:
                    self.client.login_action("accept_terms", "0xterms")
                self.assertEqual(error.exception.code, "invalid_bridge_state", message)

    def test_dispatched_result_is_returned_with_native_fields(self):
        self.answer(native_page="channel")
        result = self.client.login_action("select_channel", "0", "0xchannel")
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(result["native_page"], "channel", "原生结果附加字段须原样返回")

    def test_rejected_result_raises_and_is_not_retried(self):
        self.answer(status="rejected", reason="page_not_ready")
        with self.assertRaises(ClientError) as error:
            self.client.login_action("accept_terms", "0xterms")
        self.assertEqual(error.exception.code, "gui_native_action_rejected", "rejected 须映射为原生动作拒绝")
        self.assertEqual(error.exception.details["action"], "accept_terms")
        self.assertEqual(error.exception.details["reason"], "page_not_ready")
        self.assertEqual(error.exception.details["request_id"], self.published()[2])
        self.assertEqual(self.snapshot.call_count, 1, "拒绝后不得重试")

    def test_timeout_keeps_single_request_without_retry(self):
        self.time.now = 0.0
        with self.assertRaises(ClientError) as error:
            self.client.login_action("accept_terms", "0xterms", timeout=1)
        self.assertEqual(error.exception.code, "gui_native_action_timeout", "未确认结果时须按超时上报")
        self.assertEqual(self.published()[3], "accept_terms", "只发布一次动作")
        self.assertEqual(self.snapshot.call_count, 1, "超时后不得重试")
        self.assertGreaterEqual(self.time.now, 1.0, "等待须受期限约束")
        self.assertFalse((self.directory / "login-action-result.json").exists(), "超时不应伪造结果")

    def test_snapshot_failure_never_publishes(self):
        self.snapshot.side_effect = ClientError("stale_bridge_state", "快照过期")
        with self.assertRaises(ClientError) as error:
            self.client.login_action("accept_terms", "0xterms")
        self.assertEqual(error.exception.code, "stale_bridge_state", "快照不可用时错误须透出")
        self.assertFalse((self.directory / "login-action.txt").exists(), "快照不可用时不得发布动作")
        self.assertEqual(self.snapshot.call_count, 1)

    def test_invalid_timeout_or_arguments_never_publish(self):
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(ClientError) as error:
                self.client.login_action("accept_terms", timeout=timeout)
            self.assertEqual(error.exception.code, "invalid_bridge_options", "等待时间须为正有限数")
        self.snapshot.assert_not_called()
        self.assertFalse((self.directory / "login-action.txt").exists())
        cases = (
            ("参数类型无效", lambda: self.client.login_action("accept_terms", 42)),
            ("参数过多", lambda: self.client.login_action("accept_terms", "a", "b", "c", "d")),
        )
        for message, call in cases:
            with self.subTest(message=message), self.assertRaises(ClientError) as error:
                call()
            self.assertEqual(error.exception.code, "invalid_bridge_request", message)
        self.assertFalse((self.directory / "login-action.txt").exists(), "无效参数不得发布")

    def test_publish_failure_reports_without_retry(self):
        shutil.rmtree(self.directory)
        with self.assertRaises(ClientError) as error:
            self.client.login_action("accept_terms", "0xterms")
        self.assertEqual(error.exception.code, "login_action_publish_failed", "发布未确认时须停止且不重放")
        self.assertIn("request_id", error.exception.details, "发布失败须保留请求身份")


if __name__ == "__main__":
    unittest.main()
