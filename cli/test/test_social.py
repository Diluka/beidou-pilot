"""从CLI响应当前邀请；桌面派发不能代替队伍成员事实。"""

from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.cli import main
from beidou_pilot.engines.desktop import DesktopActions
from beidou_pilot.errors import JsonObject


class SocialInvitationContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "clientctl.py").touch()
        self.pending = True
        self.run_id = "run-1"
        self.invitation = {
            "id": "current-invitation",
            "kind": "party",
            "sender_id": None,
            "sender_name": "Inviter",
            "party_id": 42,
            "expires_at_ms": int(time.time() * 1000) + 60000,
            "remaining_ms": 60000,
            "pending": True,
            "available": True,
            "window": {
                "width": 120,
                "height": 60,
                "root_rect": {"left": 10, "top": 10, "right": 130, "bottom": 70},
                "buttons": [
                    {"control_id": number, "layout_x": x, "layout_y": 20, "width": 20, "height": 20}
                    for number, x in ((2000, 20), (2001, 60))
                ],
            },
        }
        self.party = {"party_id": 42, "members": [{"id": 4, "name": "Receiver"}, {"id": 9, "name": "Inviter"}]}

        def read(domain: str, *arguments: str) -> JsonObject:
            metadata = {"instance_id": "client-1", "client": {"run_id": self.run_id}, "scene_generation": 1}
            if domain == "observe":
                return {**metadata, "character": {"id": 4}, "native_values_valid": True}
            if arguments == ("invitations",):
                return {**metadata, "invitations": [copy.deepcopy(self.invitation)] if self.pending else []}
            if arguments == ("party",):
                return {**metadata, **self.party}
            raise AssertionError((domain, arguments))

        self.enterContext(patch.object(Backend, "read", side_effect=read))
        self.desktop = self.enterContext(patch.object(Backend, "desktop", side_effect=self.close_invitation))

    def close_invitation(self, actions: DesktopActions) -> JsonObject:
        self.pending = False
        return {}

    def invoke(self, *arguments: str) -> tuple[int, JsonObject]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(self.root), "--json", *arguments])
        return code, json.loads(output.getvalue())

    def reference(self) -> str:
        code, result = self.invoke("invitations")
        self.assertEqual(0, code, result)
        return result["data"]["invitations"][0]["ref"]

    def test_accept_confirms_self_and_inviter_in_the_actual_party(self) -> None:
        code, result = self.invoke("invitations", "accept", self.reference())
        self.assertEqual(0, code, result)
        self.assertEqual(("joined", "confirmed"), (result["data"]["status"], result["data"]["effect"]))
        self.desktop.assert_called_once()

    def test_closed_invitation_without_inviter_membership_is_unconfirmed(self) -> None:
        self.party["members"] = [{"id": 4, "name": "Receiver"}]
        code, result = self.invoke("invitations", "accept", self.reference(), "--seconds", "0.1")
        self.assertEqual(2, code)
        self.assertEqual("invitation_effect_unconfirmed", result["error"]["code"])
        self.assertTrue(result["error"]["details"]["closed"])
        self.desktop.assert_called_once()

    def test_reference_from_a_previous_run_never_clicks(self) -> None:
        reference = self.reference()
        self.run_id = "run-2"
        code, result = self.invoke("invitations", "accept", reference)
        self.assertEqual((2, "stale_invitation"), (code, result["error"]["code"]))
        self.desktop.assert_not_called()

    def test_reject_confirms_not_joined_and_friend_response_keeps_relationship_unknown(self) -> None:
        self.party = {"party_id": 0, "members": []}
        code, result = self.invoke("invitations", "reject", self.reference())
        self.assertEqual(0, code, result)
        self.assertEqual("not_joined", result["data"]["status"])
        self.pending = True
        self.invitation["kind"] = "friend"
        self.invitation["sender_id"] = 9
        self.invitation["party_id"] = None
        code, result = self.invoke("invitations", "accept", self.reference())
        self.assertEqual(0, code, result)
        self.assertEqual("unknown", result["data"]["effect"])
        self.assertEqual("friend_relationship_not_observed", result["data"]["reason"])


if __name__ == "__main__":
    unittest.main()
