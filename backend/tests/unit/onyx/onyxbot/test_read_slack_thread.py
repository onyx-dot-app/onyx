from typing import Any
from unittest.mock import MagicMock

from onyx.configs.constants import MessageType
from onyx.onyxbot.slack.models import ThreadMessage
from onyx.onyxbot.slack.utils import (
    _extract_attachments_text,
    _extract_blocks_text,
    read_slack_thread,
)


class MockSlackResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def test_extract_blocks_text() -> None:
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "First line"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "Field 1"},
                {"type": "mrkdwn", "text": "Field 2"},
            ],
        },
    ]
    extracted = _extract_blocks_text(blocks)
    assert extracted == "First line\nField 1\nField 2"


def test_extract_attachments_text() -> None:
    attachments = [
        {
            "title": "Alert Title",
            "text": "Alert description",
            "fields": [{"title": "Severity", "value": "HIGH"}],
        }
    ]
    extracted = _extract_attachments_text(attachments)
    assert extracted == "Alert Title\nAlert description\nSeverity: HIGH"


def test_extract_attachments_fallback() -> None:
    attachments = [{"fallback": "Fallback alert text"}]
    extracted = _extract_attachments_text(attachments)
    assert extracted == "Fallback alert text"


def test_read_slack_thread_textless_bot_message_blocks() -> None:
    mock_client = MagicMock()
    mock_client.conversations_replies.return_value = MockSlackResponse(
        {
            "messages": [
                {
                    "user": "U_OTHER_BOT",
                    "bot_id": "B_OTHER_BOT",
                    "text": "",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "Alert from bot block"},
                        }
                    ],
                }
            ]
        }
    )
    mock_client.users_info.return_value = MockSlackResponse(
        {
            "ok": True,
            "user": {"name": "ci-bot", "real_name": "CI Bot"},
        }
    )
    mock_client.auth_test.return_value = MockSlackResponse(
        {
            "user_id": "U_ONYX_BOT",
            "bot_id": "B_ONYX_BOT",
        }
    )

    result = read_slack_thread(
        tenant_id="test_tenant_blocks",
        slack_bot_id=101,
        channel="C12345",
        thread="1234567890.123456",
        client=mock_client,
    )

    assert len(result) == 1
    assert result[0] == ThreadMessage(
        message="Alert from bot block",
        sender="CI Bot",
        role=MessageType.USER,
    )


def test_read_slack_thread_textless_bot_message_attachments() -> None:
    mock_client = MagicMock()
    mock_client.conversations_replies.return_value = MockSlackResponse(
        {
            "messages": [
                {
                    "user": "U_OTHER_BOT",
                    "bot_id": "B_OTHER_BOT",
                    "text": "",
                    "attachments": [
                        {
                            "title": "GuardDuty Finding",
                            "text": "Finding description",
                            "fields": [{"title": "Severity", "value": "HIGH"}],
                        }
                    ],
                }
            ]
        }
    )
    mock_client.users_info.return_value = MockSlackResponse(
        {
            "ok": True,
            "user": {"name": "aws-bot", "real_name": "AWS Chatbot"},
        }
    )
    mock_client.auth_test.return_value = MockSlackResponse(
        {
            "user_id": "U_ONYX_BOT",
            "bot_id": "B_ONYX_BOT",
        }
    )

    result = read_slack_thread(
        tenant_id="test_tenant_attachments",
        slack_bot_id=102,
        channel="C12345",
        thread="1234567890.123456",
        client=mock_client,
    )

    assert len(result) == 1
    assert result[0] == ThreadMessage(
        message="GuardDuty Finding\nFinding description\nSeverity: HIGH",
        sender="AWS Chatbot",
        role=MessageType.USER,
    )


def test_read_slack_thread_empty_bot_message_skipped() -> None:
    mock_client = MagicMock()
    mock_client.conversations_replies.return_value = MockSlackResponse(
        {
            "messages": [
                {
                    "user": "U_OTHER_BOT",
                    "bot_id": "B_OTHER_BOT",
                    "text": "",
                }
            ]
        }
    )
    mock_client.users_info.return_value = MockSlackResponse(
        {
            "ok": True,
            "user": {"name": "empty-bot"},
        }
    )
    mock_client.auth_test.return_value = MockSlackResponse(
        {
            "user_id": "U_ONYX_BOT",
            "bot_id": "B_ONYX_BOT",
        }
    )

    result = read_slack_thread(
        tenant_id="test_tenant_empty",
        slack_bot_id=103,
        channel="C12345",
        thread="1234567890.123456",
        client=mock_client,
    )

    assert len(result) == 0
