from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from sentry_sdk.types import Event

import onyx.configs.sentry as sentry_module
from onyx.configs.sentry import _add_instance_tags


def _event(data: dict) -> Event:
    """Helper to create a Sentry Event from a plain dict for testing."""
    return cast(Event, data)


def _reset_state() -> None:
    """Reset the module-level resolved flag between tests."""
    sentry_module._instance_id_resolved = False


class TestAddInstanceTags:
    def setup_method(self) -> None:
        _reset_state()

    @patch("onyx.utils.telemetry.get_or_generate_uuid", return_value="test-uuid-1234")
    @patch("sentry_sdk.set_tag")
    def test_first_event_sets_instance_id(
        self, mock_set_tag: MagicMock, mock_uuid: MagicMock
    ) -> None:
        result = _add_instance_tags(_event({"message": "test error"}), {})

        assert result is not None
        assert result["tags"]["instance_id"] == "test-uuid-1234"
        mock_set_tag.assert_called_once_with("instance_id", "test-uuid-1234")
        mock_uuid.assert_called_once()

    @patch("onyx.utils.telemetry.get_or_generate_uuid", return_value="test-uuid-1234")
    @patch("sentry_sdk.set_tag")
    def test_second_event_skips_resolution(
        self, _mock_set_tag: MagicMock, mock_uuid: MagicMock
    ) -> None:
        _add_instance_tags(_event({"message": "first"}), {})
        result = _add_instance_tags(_event({"message": "second"}), {})

        assert result is not None
        assert "tags" not in result  # second event not modified
        mock_uuid.assert_called_once()  # only resolved once

    @patch(
        "onyx.utils.telemetry.get_or_generate_uuid",
        side_effect=Exception("DB unavailable"),
    )
    @patch("sentry_sdk.set_tag")
    def test_resolution_failure_still_returns_event(
        self, _mock_set_tag: MagicMock, _mock_uuid: MagicMock
    ) -> None:
        result = _add_instance_tags(_event({"message": "test error"}), {})

        assert result is not None
        assert result["message"] == "test error"
        assert "tags" not in result or "instance_id" not in result.get("tags", {})

    @patch(
        "onyx.utils.telemetry.get_or_generate_uuid",
        side_effect=Exception("DB unavailable"),
    )
    @patch("sentry_sdk.set_tag")
    def test_resolution_failure_retries_on_next_event(
        self, _mock_set_tag: MagicMock, mock_uuid: MagicMock
    ) -> None:
        """If resolution fails (e.g. DB not ready), retry on the next event."""
        _add_instance_tags(_event({"message": "first"}), {})
        _add_instance_tags(_event({"message": "second"}), {})

        assert mock_uuid.call_count == 2  # retried on second event

    @patch("onyx.utils.telemetry.get_or_generate_uuid", return_value="test-uuid-1234")
    @patch("sentry_sdk.set_tag")
    def test_preserves_existing_tags(
        self, _mock_set_tag: MagicMock, _mock_uuid: MagicMock
    ) -> None:
        result = _add_instance_tags(
            _event({"message": "test", "tags": {"existing": "tag"}}), {}
        )

        assert result is not None
        assert result["tags"]["existing"] == "tag"
        assert result["tags"]["instance_id"] == "test-uuid-1234"
