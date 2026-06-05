import base64
import datetime
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

from onyx.db.enums import EndpointPolicy
from onyx.external_apps.matching.engine import MatchedAction
from onyx.external_apps.providers.gmail import GmailAction
from onyx.server.features.build.approvals.api import ApprovalView


def _send_payload() -> dict[str, Any]:
    message = EmailMessage()
    message["To"] = "alice@example.com"
    message["Subject"] = "Hi"
    message.set_content("Body text")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return {"raw": raw}


def _view(action_type: str, payload: dict[str, Any]) -> ApprovalView:
    return ApprovalView(
        approval_id=uuid4(),
        session_id=uuid4(),
        actions=[
            MatchedAction(
                action_type=action_type,
                display_name="x",
                description="x",
                policy=EndpointPolicy.ASK,
            )
        ],
        app_name="Gmail",
        payload=payload,
        created_at=datetime.datetime.now(datetime.timezone.utc),
        decision=None,
        decided_at=None,
    )


def test_display_payload_decodes_by_decisive_action() -> None:
    payload = _send_payload()

    view = _view(GmailAction.MESSAGES_SEND, payload)

    assert view.payload == payload  # raw preserved
    assert view.display_payload["to"] == ["alice@example.com"]
    assert view.display_payload["subject"] == "Hi"
    assert "raw" not in view.display_payload


def test_display_payload_passthrough_when_no_decoder() -> None:
    payload = {"addLabelIds": ["INBOX"]}

    view = _view(GmailAction.MESSAGES_MODIFY, payload)

    assert view.display_payload == payload
