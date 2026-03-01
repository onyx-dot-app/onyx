import importlib
from typing import Any
from unittest.mock import Mock

from ee.onyx.configs import app_configs as ee_app_configs
from ee.onyx.utils import posthog_client
from ee.onyx.utils import telemetry as ee_telemetry


def test_posthog_api_key_defaults_to_none_when_unset(monkeypatch: Any) -> None:
    with monkeypatch.context() as m:
        m.delenv("POSTHOG_API_KEY", raising=False)
        importlib.reload(ee_app_configs)
        assert ee_app_configs.POSTHOG_API_KEY is None

    importlib.reload(ee_app_configs)


def test_primary_posthog_client_not_initialized_without_api_key(
    monkeypatch: Any,
) -> None:
    class FakePosthog:
        call_count = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            type(self).call_count += 1

    with monkeypatch.context() as m:
        m.delenv("POSTHOG_API_KEY", raising=False)
        m.delenv("MARKETING_POSTHOG_API_KEY", raising=False)
        m.setattr("posthog.Posthog", FakePosthog)

        importlib.reload(ee_app_configs)
        importlib.reload(posthog_client)

        assert posthog_client.posthog is None
        assert posthog_client.marketing_posthog is None
        assert FakePosthog.call_count == 0

    importlib.reload(ee_app_configs)
    importlib.reload(posthog_client)


def test_primary_posthog_client_initialized_with_api_key(monkeypatch: Any) -> None:
    class FakePosthog:
        call_count = 0
        last_kwargs: dict[str, Any] | None = None

        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            type(self).call_count += 1
            type(self).last_kwargs = kwargs

    with monkeypatch.context() as m:
        m.setenv("POSTHOG_API_KEY", "test-primary-key")
        m.delenv("MARKETING_POSTHOG_API_KEY", raising=False)
        m.setattr("posthog.Posthog", FakePosthog)

        importlib.reload(ee_app_configs)
        importlib.reload(posthog_client)

        assert isinstance(posthog_client.posthog, FakePosthog)
        assert posthog_client.marketing_posthog is None
        assert FakePosthog.call_count == 1
        assert FakePosthog.last_kwargs == {
            "project_api_key": "test-primary-key",
            "host": ee_app_configs.POSTHOG_HOST,
            "debug": ee_app_configs.POSTHOG_DEBUG_LOGS_ENABLED,
            "on_error": posthog_client.posthog_on_error,
        }

    importlib.reload(ee_app_configs)
    importlib.reload(posthog_client)


def test_capture_and_sync_skips_primary_identify_without_primary_client(
    monkeypatch: Any,
) -> None:
    marketing_posthog = Mock()
    monkeypatch.setattr(posthog_client, "marketing_posthog", marketing_posthog)
    monkeypatch.setattr(posthog_client, "posthog", None)

    posthog_client.capture_and_sync_with_alternate_posthog(
        alternate_distinct_id="marketing-user-id",
        event="signed_up",
        properties={"onyx_cloud_user_id": "cloud-user-id", "plan": "trial"},
    )

    marketing_posthog.identify.assert_called_once()
    marketing_posthog.capture.assert_called_once()
    marketing_posthog.flush.assert_called_once()


def test_event_telemetry_noops_when_posthog_disabled(monkeypatch: Any) -> None:
    logger = Mock()
    monkeypatch.setattr(ee_telemetry, "logger", logger)
    monkeypatch.setattr(ee_telemetry, "posthog", None)

    ee_telemetry.event_telemetry(
        distinct_id="user@example.com",
        event="message_sent",
        properties={"source": "web"},
    )

    logger.info.assert_not_called()
