"""观察消费合同：原生有效性与客户端实例身份，不依赖 Linux 进程字段。"""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from beidou_pilot.backend import Backend
from beidou_pilot.catalog import Catalog
from beidou_pilot.errors import ClientError
from beidou_pilot.items import read_inventory
from beidou_pilot.snapshot import collect, format_snapshot
from beidou_pilot.stats import read_character
from beidou_pilot.travel import portal


class ObservationConsumerContract(unittest.TestCase):
    def test_native_values_are_usable_when_checksum_verification_is_unknown(self) -> None:
        backend = Mock(spec=Backend)
        character = {"id": 4, "hp": 100}
        backend.read.return_value = {"character": character, "native_values_valid": True,
                                     "character_checksum_valid": None, "unavailable": []}
        self.assertEqual(character, read_character(backend))
        inventory = {"items": [], "native_values_valid": True, "checksums_valid": None,
                     "unavailable": []}
        backend.read.return_value = inventory
        self.assertEqual(inventory, read_inventory(backend, 2))
        self.assertIsNone(inventory["checksums_valid"])

    def test_unavailable_native_values_stop_character_and_inventory_actions(self) -> None:
        backend = Mock(spec=Backend)
        backend.read.return_value = {"character": {"id": 4}, "native_values_valid": False,
                                     "checksums_valid": None, "unavailable": ["transition"]}
        for read in (lambda: read_character(backend), lambda: read_inventory(backend, 2)):
            with self.subTest(read=read), self.assertRaises(ClientError):
                read()

    def test_portal_plan_anchors_native_identity_and_rejects_replacement_result(self) -> None:
        backend = Mock(spec=Backend)
        backend.root, backend.name, backend.instance = Path("/unused"), "beidou", "default"
        initial = {"ready": True, "instance_id": "first", "scene_generation": 3, "map_id": 100,
                   "position": {"x": 10.5, "y": 20.0}, "character": {"id": 4, "hp": 100, "max_hp": 100}}
        catalog = Mock(spec=Catalog)
        catalog.map.return_value = {"portals": [{"name": "out", "x": 10, "y": 20, "target_map_id": 200}],
                                    "metadata_source": "fixture", "unavailable": []}
        result = {"status": "completed", "last_state": {**initial, "map_id": 200, "instance_id": "replacement"}}
        with patch("beidou_pilot.travel.BridgeClient") as bridge:
            bridge.return_value.snapshot.return_value = initial
            with patch("beidou_pilot.travel.run_strategy", return_value=result) as run:
                with self.assertRaises(ClientError) as failure:
                    portal(backend, "out", catalog=catalog)
        self.assertEqual("portal_identity_changed", failure.exception.code)
        options = run.call_args.args[2]
        self.assertEqual(initial, run.call_args.kwargs["context_state"])
        self.assertEqual((10, 20, 200), tuple(options[key] for key in ("x", "y", "target_map")))
        self.assertNotIn("instance_id", options)


class SnapshotConsumerContract(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = Mock(spec=Backend)
        self.backend.root = Path("/unused")
        character = {"id": 4, "name": "战士", "job": 100, "level": 12, "hp": 100, "max_hp": 100,
                     "mp": 20, "max_mp": 20, "ability_points": 0, "skill_points": 0, "experience": 50}
        self.domains = {
            "stage": {"stage": "IN_GAME", "running": True, "channel": 1},
            "observe": {"native_values_valid": True, "character": character, "map_id": 100,
                        "position": {"x": 0.5, "y": 0.0}, "instance_id": "native-1",
                        "client": {"container_id": "container", "run_id": "run"},
                        "observed_at": "2026-11-09T00:00:00+00:00"},
            "scene": {"map_id": 100, "player_facing": "Right", "npcs": [], "drops": [],
                      "monsters": [{"object_id": 10, "template_id": None, "name": None, "x": 200.5, "y": 0.0}]},
            "inventory": {"items": [{"inventory_type": 2, "slot": 1, "item_id": 2000000, "quantity": 2}],
                          "equipped": []},
            "quests": {"quests": {"1000": {"status": "started"}}},
            "character": {"mesos": 50, "skills": {"1001004": {"level": 1}}},
            "interaction": {"page": None},
        }
        self.backend.read.side_effect = lambda domain, *arguments: self.domains[domain]
        self.catalog = self.enterContext(patch("beidou_pilot.snapshot.Catalog")).return_value
        self.catalog.map_name.return_value = "训练场"
        self.catalog.item_name.return_value = "红色药水"

    def test_headless_keeps_common_state_and_refs_without_inventing_ui_visibility(self) -> None:
        self.backend.name = "headless"
        self.domains["observe"].update(dead=True, revive_requestable=True)
        self.domains["observe"]["character"]["hp"] = 0
        report = collect(self.backend)
        self.assertIs(report["dead"], True)
        self.assertIs(report["revive_requestable"], True)
        self.assertNotIn("dialog", [call.args[0] for call in self.backend.read.call_args_list])
        self.assertIn("interaction", [call.args[0] for call in self.backend.read.call_args_list])
        self.assertNotIn("dialog", report)
        self.assertIsNone(report["interaction"]["page"])
        self.assertIsNone(report["viewport"])
        self.assertIsNone(report["monsters"][0]["visible"])
        self.assertIsNone(report["monsters"][0]["name"])
        self.assertEqual(200.0, report["monsters"][0]["dx"])
        self.assertIn(report["monsters"][0]["ref"], report["refs"])
        self.assertIn(report["inventory"][0]["ref"], report["refs"])
        self.assertEqual(2, report["inventory"][0]["quantity"])
        self.assertEqual(self.domains["quests"]["quests"], report["quests"])
        self.assertEqual(self.domains["character"]["skills"], report["character"]["skills"])
        text = format_snapshot(report)
        self.assertIn("当前没有交互页面", text)
        self.assertIn("可见性未知", text)
        self.assertNotIn("画外", text)

    def test_native_control_and_npc_refs_are_preserved_without_python_payloads(self) -> None:
        self.backend.name = "headless"
        self.domains["scene"]["npcs"] = [{"object_id": 12, "template_id": 12101, "name": "瑞恩",
                                           "x": .5, "y": 0, "ref": "native-npc-ref"}]
        page = {"source": "server", "title": "瑞恩", "text": "你好",
                "controls": [{"role": "button", "text": "继续", "enabled": None, "ref": "native-button-ref"}]}
        self.domains["interaction"]["page"] = page
        report = collect(self.backend)
        self.assertEqual(page, report["interaction"]["page"])
        self.assertIsNone(report["interaction"]["page"]["controls"][0]["enabled"])
        self.assertEqual("native-npc-ref", report["npcs"][0]["ref"])
        self.assertNotIn("native-npc-ref", report["refs"])
        self.assertNotIn("native-button-ref", report["refs"])
        self.assertIn("启用状态未知", format_snapshot(report))

    def test_unknown_interaction_text_and_controls_stay_unknown(self) -> None:
        self.backend.name = "headless"
        page = {"source": "server", "title": "NPC对话", "text": None, "controls": None}
        self.domains["interaction"].update(page=page, unavailable=["interaction_page_layout_not_supported"],
                                           not_covered=[], client={"container_id": "native-metadata"})
        with patch("beidou_pilot.control_scripts.run_source") as run:
            report = collect(self.backend)
        run.assert_not_called()
        self.assertEqual(page, report["interaction"]["page"])
        self.assertEqual(["interaction_page_layout_not_supported"], report["interaction"]["unavailable"])
        self.assertEqual([], report["interaction"]["not_covered"])
        self.assertNotIn("client", report["interaction"])
        self.assertIn("交互正文：未知", format_snapshot(report))
        self.assertIn("交互控件：未知", format_snapshot(report))

    def test_beidou_preserves_dialog_and_filters_only_known_invisible_entities(self) -> None:
        self.backend.name = "beidou"
        self.domains["dialog"] = {"camera_viewport": None, "dialog_open": True, "npc_id": 1000,
                                  "dialog_type": 1, "lines": ["欢迎"], "choices": [], "buttons": []}
        unknown = collect(self.backend)
        self.assertTrue(unknown["dialog"]["supported"])
        self.assertTrue(unknown["dialog"]["open"])
        self.assertIsNone(unknown["monsters"][0]["visible"])
        self.assertIn("欢迎", format_snapshot(unknown))
        self.domains["dialog"]["camera_viewport"] = {"left": 0, "right": 100, "top": -10, "bottom": 10}
        self.assertEqual([], collect(self.backend)["monsters"])
        full = collect(self.backend, all_entities=True)
        self.assertFalse(full["monsters"][0]["visible"])
        self.assertIn("画外", format_snapshot(full))

    def test_beginner_snapshot_lists_candidates_without_inventing_a_route(self) -> None:
        self.domains["dialog"] = {"camera_viewport": None, "dialog_open": False, "npc_id": None,
                                  "dialog_type": None, "lines": [], "choices": [], "buttons": []}
        for backend in ("headless", "beidou"):
            for level in (7, 8, 10):
                with self.subTest(backend=backend, level=level):
                    self.backend.name = backend
                    self.domains["observe"]["character"].update(job=0, level=level)
                    report = collect(self.backend)
                    milestone = report["advancement"]
                    self.assertIsNone(milestone["level"])
                    self.assertIsNone(milestone["due"])
                    self.assertEqual({"magician": 8, "warrior": 10, "bowman": 10, "thief": 10, "pirate": 10},
                                     {c["first_job"]: c["level"] for c in milestone["candidates"]})
                    text = format_snapshot(report)
                    self.assertIn("首转路线未知", text)
                    self.assertIn("魔法师8级", text)
                    self.assertIn("fight/hunt", text)


if __name__ == "__main__":
    unittest.main()
