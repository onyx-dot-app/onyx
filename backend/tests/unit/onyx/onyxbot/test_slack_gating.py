"""Tests for Slack bot gating and seat limit enforcement."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.settings.models import ApplicationStatus

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_HANDLE_MSG = "onyx.onyxbot.slack.handlers.handle_message"
_LISTENER = "onyx.onyxbot.slack.listener"


def _make_socket_request(
    req_type: str = "events_api",
    event: dict | None = None,
) -> MagicMock:
    """Create a mock SocketModeRequest."""
    req = MagicMock()
    req.type = req_type
    if req_type == "events_api":
        req.payload = {
            "event": event or {"type": "message", "channel": "C123", "ts": "1234.5678"}
        }
    elif req_type == "slash_commands":
        req.payload = {"channel_id": "C123"}
    else:
        req.payload = {}
    return req


def _make_license_metadata(
    status: ApplicationStatus = ApplicationStatus.ACTIVE,
) -> MagicMock:
    """Create a mock LicenseMetadata."""
    metadata = MagicMock()
    metadata.status = status
    return metadata


def _ee_side_effect(
    is_gated: bool = False,
    metadata: Any = None,
) -> list:
    """Build fetch_ee_implementation_or_noop side_effect for gating tests.

    Returns callables for: [is_tenant_gated, get_cached_license_metadata].
    """
    return [
        lambda *_a, **_kw: is_gated,
        lambda *_a, **_kw: metadata,
    ]


def _make_message_info(email: str = "user@test.com") -> MagicMock:
    """Create a mock SlackMessageInfo for handle_message tests."""
    info = MagicMock()
    info.channel_to_respond = "C123"
    info.thread_messages = [MagicMock(message="test?")]
    info.sender_id = "U123"
    info.bypass_filters = False
    info.is_slash_command = False
    info.is_bot_dm = False
    info.email = email
    info.msg_to_respond = "1234.5678"
    return info


def _make_channel_config() -> MagicMock:
    """Create a mock SlackChannelConfig."""
    config = MagicMock()
    config.persona = None
    config.channel_config = {}
    return config


# ---------------------------------------------------------------------------
# _check_tenant_gated
# ---------------------------------------------------------------------------


class TestCheckTenantGated:
    """Tests for _check_tenant_gated function."""

    @pytest.fixture(autouse=True)
    def _patch_tenant_id(self) -> Any:
        with patch(f"{_LISTENER}.get_current_tenant_id", return_value="public"):
            yield

    def _call(
        self,
        _mock_fetch_ee: MagicMock,
        event: dict | None = None,
    ) -> tuple[bool, MagicMock]:
        """Call _check_tenant_gated with a fresh client + request."""
        from onyx.onyxbot.slack.listener import _check_tenant_gated

        client = MagicMock()
        client.web_client = MagicMock()
        req = _make_socket_request(event=event)
        result = _check_tenant_gated(client, req)
        return result, client

    @patch(f"{_LISTENER}.fetch_ee_implementation_or_noop")
    def test_active_license_not_gated(self, mock_fetch_ee: MagicMock) -> None:
        metadata = _make_license_metadata()
        mock_fetch_ee.side_effect = _ee_side_effect(metadata=metadata)

        result, _ = self._call(mock_fetch_ee)
        assert result is False

    @patch(f"{_LISTENER}.respond_in_thread_or_channel")
    @patch(f"{_LISTENER}.fetch_ee_implementation_or_noop")
    def test_multi_tenant_gated_blocks_and_responds(
        self, mock_fetch_ee: MagicMock, mock_respond: MagicMock
    ) -> None:
        mock_fetch_ee.side_effect = _ee_side_effect(is_gated=True)

        result, _ = self._call(mock_fetch_ee)

        assert result is True
        mock_respond.assert_called_once()
        assert "subscription has expired" in mock_respond.call_args[1]["text"]

    @patch(f"{_LISTENER}.respond_in_thread_or_channel")
    @patch(f"{_LISTENER}.fetch_ee_implementation_or_noop")
    def test_gated_access_status_blocks(
        self, mock_fetch_ee: MagicMock, mock_respond: MagicMock
    ) -> None:
        metadata = _make_license_metadata(status=ApplicationStatus.GATED_ACCESS)
        mock_fetch_ee.side_effect = _ee_side_effect(metadata=metadata)

        result, _ = self._call(mock_fetch_ee)

        assert result is True
        mock_respond.assert_called_once()

    @pytest.mark.parametrize(
        "event",
        [
            {"type": "message", "channel": "C123", "bot_id": "B456", "ts": "1"},
            {
                "type": "message",
                "channel": "C123",
                "bot_profile": {"id": "B456"},
                "ts": "1",
            },
            {"type": "message", "channel": "C123", "subtype": "bot_message", "ts": "1"},
        ],
        ids=["bot_id", "bot_profile", "subtype_bot_message"],
    )
    @patch(f"{_LISTENER}.respond_in_thread_or_channel")
    @patch(f"{_LISTENER}.fetch_ee_implementation_or_noop")
    def test_bot_message_no_response_sent(
        self, mock_fetch_ee: MagicMock, mock_respond: MagicMock, event: dict
    ) -> None:
        """Bot messages are blocked but no response is sent (prevents loop)."""
        mock_fetch_ee.side_effect = _ee_side_effect(is_gated=True)

        result, _ = self._call(mock_fetch_ee, event=event)

        assert result is True
        mock_respond.assert_not_called()

    @patch(f"{_LISTENER}.respond_in_thread_or_channel")
    @patch(f"{_LISTENER}.fetch_ee_implementation_or_noop")
    def test_app_mention_no_response_sent(
        self, mock_fetch_ee: MagicMock, mock_respond: MagicMock
    ) -> None:
        """app_mention events are blocked silently (dedup with message event)."""
        mock_fetch_ee.side_effect = _ee_side_effect(is_gated=True)

        result, _ = self._call(
            mock_fetch_ee,
            event={"type": "app_mention", "channel": "C123", "ts": "1"},
        )

        assert result is True
        mock_respond.assert_not_called()

    @patch(f"{_LISTENER}.fetch_ee_implementation_or_noop")
    def test_no_license_metadata_not_gated(self, mock_fetch_ee: MagicMock) -> None:
        """No license metadata (CE mode) means not gated."""
        mock_fetch_ee.side_effect = _ee_side_effect(metadata=None)

        result, _ = self._call(mock_fetch_ee)
        assert result is False

    @patch(f"{_LISTENER}.respond_in_thread_or_channel")
    @patch(f"{_LISTENER}.fetch_ee_implementation_or_noop")
    def test_response_uses_thread_ts(
        self, mock_fetch_ee: MagicMock, mock_respond: MagicMock
    ) -> None:
        mock_fetch_ee.side_effect = _ee_side_effect(is_gated=True)

        self._call(
            mock_fetch_ee,
            event={
                "type": "message",
                "channel": "C123",
                "thread_ts": "1111.0000",
                "ts": "2222.0000",
            },
        )

        assert mock_respond.call_args[1]["thread_ts"] == "1111.0000"


# ---------------------------------------------------------------------------
# _extract_channel_from_request
# ---------------------------------------------------------------------------


class TestExtractChannelFromRequest:
    """Tests for _extract_channel_from_request function."""

    @pytest.mark.parametrize(
        "req_type, payload, expected",
        [
            ("events_api", {"event": {"channel": "C123"}}, "C123"),
            ("slash_commands", {"channel_id": "C456"}, "C456"),
            ("interactive", {"container": {"channel_id": "C789"}}, "C789"),
            ("unknown", {}, None),
        ],
    )
    def test_channel_extraction(
        self, req_type: str, payload: dict, expected: str | None
    ) -> None:
        from onyx.onyxbot.slack.listener import _extract_channel_from_request

        req = MagicMock()
        req.type = req_type
        req.payload = payload
        assert _extract_channel_from_request(req) == expected


# ---------------------------------------------------------------------------
# handle_message seat check
# ---------------------------------------------------------------------------


class TestHandleMessageSeatCheck:
    """Tests for seat limit enforcement in handle_message."""

    @pytest.fixture(autouse=True)
    def _common_patches(self) -> Any:
        """Patch side-effect-only dependencies that every test needs."""
        with (
            patch(f"{_HANDLE_MSG}.slack_usage_report"),
            patch(f"{_HANDLE_MSG}.send_msg_ack_to_user"),
        ):
            yield

    @pytest.fixture
    def db_session(self) -> Generator[MagicMock, None, None]:
        with patch(f"{_HANDLE_MSG}.get_session_with_current_tenant") as mock:
            session = MagicMock()
            mock.return_value.__enter__ = MagicMock(return_value=session)
            mock.return_value.__exit__ = MagicMock(return_value=False)
            yield session

    def _call_handle_message(
        self, client: MagicMock | None = None, email: str = "user@test.com"
    ) -> bool:
        from onyx.onyxbot.slack.handlers.handle_message import handle_message

        return handle_message(
            message_info=_make_message_info(email),
            slack_channel_config=_make_channel_config(),
            client=client or MagicMock(),
            feedback_reminder_id=None,
        )

    @pytest.mark.usefixtures("db_session")
    @patch(f"{_HANDLE_MSG}.respond_in_thread_or_channel")
    @patch(f"{_HANDLE_MSG}.fetch_ee_implementation_or_noop")
    @patch(f"{_HANDLE_MSG}.get_user_by_email", return_value=None)
    def test_new_user_blocked_when_seats_exceeded(
        self,
        _mock_get_user: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_respond: MagicMock,
    ) -> None:
        seat_result = MagicMock(available=False, error_message="Seat limit exceeded")
        mock_fetch_ee.return_value = lambda **_kw: seat_result

        result = self._call_handle_message()

        assert result is False
        assert "seat limit" in mock_respond.call_args[1]["text"]
        assert "Onyx administrator" in mock_respond.call_args[1]["text"]

    @pytest.mark.usefixtures("db_session")
    @patch(f"{_HANDLE_MSG}.handle_regular_answer", return_value=False)
    @patch(f"{_HANDLE_MSG}.handle_standard_answers", return_value=False)
    @patch(f"{_HANDLE_MSG}.add_slack_user_if_not_exists")
    @patch(f"{_HANDLE_MSG}.fetch_ee_implementation_or_noop")
    @patch(f"{_HANDLE_MSG}.get_user_by_email")
    def test_existing_user_bypasses_seat_check(
        self,
        mock_get_user: MagicMock,
        mock_fetch_ee: MagicMock,
        _mock_add_user: MagicMock,
        _mock_standard: MagicMock,
        _mock_regular: MagicMock,
    ) -> None:
        mock_get_user.return_value = MagicMock()  # User exists

        self._call_handle_message()

        mock_fetch_ee.assert_not_called()

    @patch(f"{_HANDLE_MSG}.handle_regular_answer", return_value=False)
    @patch(f"{_HANDLE_MSG}.handle_standard_answers", return_value=False)
    @patch(f"{_HANDLE_MSG}.add_slack_user_if_not_exists")
    @patch(f"{_HANDLE_MSG}.fetch_ee_implementation_or_noop")
    @patch(f"{_HANDLE_MSG}.get_user_by_email", return_value=None)
    def test_new_user_allowed_when_seats_available(
        self,
        _mock_get_user: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_add_user: MagicMock,
        _mock_standard: MagicMock,
        _mock_regular: MagicMock,
        db_session: MagicMock,
    ) -> None:
        mock_fetch_ee.return_value = lambda **_kw: MagicMock(available=True)

        self._call_handle_message(email="new@test.com")

        mock_add_user.assert_called_once_with(db_session, "new@test.com")

    @patch(f"{_HANDLE_MSG}.handle_regular_answer", return_value=False)
    @patch(f"{_HANDLE_MSG}.handle_standard_answers", return_value=False)
    @patch(f"{_HANDLE_MSG}.add_slack_user_if_not_exists")
    @patch(f"{_HANDLE_MSG}.fetch_ee_implementation_or_noop")
    @patch(f"{_HANDLE_MSG}.get_user_by_email", return_value=None)
    def test_noop_seat_check_allows_new_user(
        self,
        _mock_get_user: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_add_user: MagicMock,
        _mock_standard: MagicMock,
        _mock_regular: MagicMock,
        db_session: MagicMock,
    ) -> None:
        """CE mode: noop returns None, user is allowed."""
        mock_fetch_ee.return_value = lambda **_kw: None

        self._call_handle_message(email="new@test.com")

        mock_add_user.assert_called_once_with(db_session, "new@test.com")


# ---------------------------------------------------------------------------
# check_seat_availability
# ---------------------------------------------------------------------------


class TestCheckSeatAvailability:
    """Tests for check_seat_availability function."""

    def _check(self, used: int, total: int) -> Any:
        from ee.onyx.db.license import check_seat_availability

        metadata = MagicMock(seats=total)
        with (
            patch("ee.onyx.db.license.get_used_seats", return_value=used),
            patch("ee.onyx.db.license.get_license_metadata", return_value=metadata),
        ):
            return check_seat_availability(MagicMock())

    def test_seats_available(self) -> None:
        result = self._check(used=5, total=10)
        assert result.available is True

    def test_seats_exceeded(self) -> None:
        result = self._check(used=10, total=10)
        assert result.available is False
        assert "Seat limit" in result.error_message

    def test_at_capacity_allows_fill(self) -> None:
        """Filling to exactly 100% is allowed (uses > not >=)."""
        result = self._check(used=9, total=10)
        assert result.available is True

    def test_no_license_allows_unlimited(self) -> None:
        from ee.onyx.db.license import check_seat_availability

        with patch("ee.onyx.db.license.get_license_metadata", return_value=None):
            result = check_seat_availability(MagicMock())
            assert result.available is True


# ---------------------------------------------------------------------------
# get_used_seats
# ---------------------------------------------------------------------------


class TestGetUsedSeats:
    """Tests for get_used_seats — anonymous user exclusion."""

    @patch("ee.onyx.db.license.MULTI_TENANT", False)
    @patch("onyx.db.engine.sql_engine.get_session_with_current_tenant")
    def test_excludes_anonymous_user(self, mock_get_session: MagicMock) -> None:
        from ee.onyx.db.license import get_used_seats

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalar.return_value = 3

        assert get_used_seats() == 3
        mock_session.execute.assert_called_once()
