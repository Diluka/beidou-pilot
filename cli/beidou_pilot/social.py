"""按当前邀请引用响应，并用本端队伍事实确认结果。"""

import hashlib
import json
import math
import time
from typing import Literal, TypedDict, cast

from .backend import Backend
from .errors import ClientError, JsonObject
from .engines.ui import UIWindow
from .ui import click_control


class Invitation(TypedDict):
    id: str
    ref: str
    kind: Literal["friend", "party"]
    sender_id: int | None
    sender_name: str | None
    party_id: int | None
    expires_at_ms: int | None
    remaining_ms: int | None
    pending: bool
    available: bool
    window: UIWindow


def read_invitations(backend: Backend) -> JsonObject:
    report = backend.read("social", "invitations")
    client = cast(JsonObject, report["client"])
    for invitation in cast(list[Invitation], report["invitations"]):
        scope = [report["instance_id"], client["run_id"], report["scene_generation"], invitation["id"]]
        invitation["ref"] = "@invite" + hashlib.sha256(json.dumps(scope).encode()).hexdigest()[:16]
    return report


def respond(backend: Backend, reference: str, action: Literal["accept", "reject"], seconds: float = 3) -> JsonObject:
    if not math.isfinite(seconds) or not 0.1 <= seconds <= 30:
        raise ClientError("invalid_invitation_wait", "邀请结果等待须为0.1至30秒。")
    before = read_invitations(backend)
    invitation = next(
        (item for item in cast(list[Invitation], before["invitations"]) if item["ref"] == reference), None
    )
    if (
        invitation is None
        or not invitation["available"]
        or (invitation["expires_at_ms"] is not None and invitation["expires_at_ms"] <= time.time() * 1000)
    ):
        raise ClientError("stale_invitation", "邀请引用已失效或当前不可响应，请重新读取 invitations。")
    client = cast(JsonObject, before["client"])
    identity = before["instance_id"], client["run_id"]
    click_control(backend, invitation["window"], 2000 if action == "accept" else 2001)
    deadline = time.monotonic() + seconds
    while True:
        current = read_invitations(backend)
        current_client = cast(JsonObject, current["client"])
        if (current["instance_id"], current_client["run_id"]) != identity:
            raise ClientError("invitation_identity_changed", "响应后实例身份已变化，邀请结果未确认。")
        still_pending = any(
            item["id"] == invitation["id"] and item["pending"]
            for item in cast(list[Invitation], current["invitations"])
        )
        result: JsonObject = {
            "action": action,
            "invitation": cast(JsonObject, invitation),
            "dispatched": True,
            "effect": "unknown",
            "closed": not still_pending,
        }
        if invitation["kind"] == "party":
            party = backend.read("social", "party")
            party_client = cast(JsonObject, party["client"])
            if (party["instance_id"], party_client["run_id"]) != identity:
                raise ClientError("invitation_identity_changed", "队伍观察已属于另一实例，邀请结果未确认。")
            result["party"] = party
            members = cast(list[JsonObject], party["members"])
            if action == "accept":
                observation = backend.read("observe")
                observation_client = cast(JsonObject, observation["client"])
                if (observation["instance_id"], observation_client["run_id"]) != identity:
                    raise ClientError("invitation_identity_changed", "角色观察已属于另一实例，邀请结果未确认。")
                character = cast(JsonObject | None, observation["character"])
                confirmed = (
                    character is not None
                    and observation["native_values_valid"] is True
                    and party["party_id"] == invitation["party_id"]
                    and any(member["id"] == character["id"] for member in members)
                    and any(member["name"] == invitation["sender_name"] for member in members)
                )
                if confirmed:
                    return {**result, "effect": "confirmed", "status": "joined"}
            elif not still_pending and party["party_id"] != invitation["party_id"]:
                return {**result, "effect": "confirmed", "status": "not_joined"}
        elif not still_pending:
            return {**result, "status": "responded", "reason": "friend_relationship_not_observed"}
        if time.monotonic() >= deadline:
            raise ClientError("invitation_effect_unconfirmed", "邀请已响应，实际结果尚未确认，未重复点击。", result)
        time.sleep(0.05)
