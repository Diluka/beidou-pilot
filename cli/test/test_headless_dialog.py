"""Headless interaction uses native references, never desktop coordinates."""
import unittest
from unittest.mock import MagicMock, Mock, patch

from beidou_pilot import headless_dialog
from beidou_pilot.errors import ClientError


class HeadlessDialogContract(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.page = {"source": "server", "title": "NPC", "text": "第一行\n第二行", "controls": [
            {"role": "option", "text": "任务", "ref": "@ui-test-1", "enabled": True},
            {"role": "button", "text": "下一页", "ref": "@ui-test-2", "enabled": True}]}
        self.backend.read.return_value = {"page": self.page, "unavailable": []}

    def test_projection_preserves_references(self):
        result = headless_dialog.read(self.backend)
        self.assertEqual(result["lines"], ["第一行", "第二行"])
        self.assertEqual(result["choices"][0]["ref"], "@ui-test-1")
        self.assertEqual(result["buttons"][0]["ref"], "@ui-test-2")
        self.backend.desktop.assert_not_called()

    def test_select_and_next_choose_native_reference(self):
        with patch.object(headless_dialog, "activate", return_value={}) as activate:
            headless_dialog.act(self.backend, "select", "任务")
            activate.assert_called_with(self.backend, "@ui-test-1")
            self.page["controls"].pop(0)
            headless_dialog.act(self.backend, "next")
            activate.assert_called_with(self.backend, "@ui-test-2")

    def test_no_dialog_and_unknown_controls(self):
        self.backend.read.return_value = {"page": None, "unavailable": []}
        with self.assertRaises(ClientError) as caught:
            headless_dialog.act(self.backend, "next")
        self.assertEqual(caught.exception.code, "no_dialog")
        self.page["controls"] = None
        self.backend.read.return_value = {"page": self.page, "unavailable": []}
        with self.assertRaises(ClientError) as caught:
            headless_dialog.act(self.backend, "next")
        self.assertEqual(caught.exception.code, "control_availability_unknown")

    def test_native_stale_reference_is_preserved(self):
        bridge = MagicMock()
        bridge._ready_state.return_value = {"scripts": []}
        bridge._wait.side_effect = ClientError("bridge_command_rejected", "rejected", {"reason": "stale_interaction_reference"})
        with patch.object(headless_dialog, "BridgeClient", return_value=bridge):
            with self.assertRaises(ClientError) as caught:
                headless_dialog.activate(self.backend, "@ui-old-1")
        self.assertEqual(caught.exception.code, "stale_interaction_reference")

    def test_talk_resolves_scene_npc(self):
        self.backend.read.return_value = {"npcs": [{"name": "希娜", "object_id": 1, "template_id": 2, "ref": "@ui-test-3"}]}
        with patch.object(headless_dialog, "activate", return_value={}) as activate:
            headless_dialog.talk(self.backend, "希娜")
            activate.assert_called_once_with(self.backend, "@ui-test-3")
