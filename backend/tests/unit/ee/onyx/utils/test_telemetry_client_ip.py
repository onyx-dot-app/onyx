"""Unit tests for the client-IP enrichment in ee.onyx.utils.telemetry."""

from unittest.mock import MagicMock

from ee.onyx.utils import telemetry as ee_telemetry
from onyx.utils import client_ip as client_ip_mod


def test_event_telemetry_reads_client_ip_from_contextvar(monkeypatch):  # type: ignore[no-untyped-def]
    fake_posthog = MagicMock()
    monkeypatch.setattr(ee_telemetry, "posthog", fake_posthog)

    token = client_ip_mod._CLIENT_IP_CONTEXTVAR.set("8.8.8.8")
    try:
        ee_telemetry.event_telemetry(
            distinct_id="u-1",
            event="user_signed_up",
            properties={"email": "user@example.com"},
        )
    finally:
        client_ip_mod._CLIENT_IP_CONTEXTVAR.reset(token)

    fake_posthog.capture.assert_called_once_with(
        "u-1",
        "user_signed_up",
        {"email": "user@example.com", "$ip": "8.8.8.8"},
    )


def test_event_telemetry_omits_ip_when_contextvar_not_set(monkeypatch):  # type: ignore[no-untyped-def]
    fake_posthog = MagicMock()
    monkeypatch.setattr(ee_telemetry, "posthog", fake_posthog)
    # Contextvar defaults to None — no need to set it.

    ee_telemetry.event_telemetry(
        distinct_id="u-1",
        event="user_signed_up",
        properties={"email": "user@example.com"},
    )

    fake_posthog.capture.assert_called_once_with(
        "u-1",
        "user_signed_up",
        {"email": "user@example.com"},
    )


def test_identify_user_reads_client_ip_from_contextvar(monkeypatch):  # type: ignore[no-untyped-def]
    fake_posthog = MagicMock()
    monkeypatch.setattr(ee_telemetry, "posthog", fake_posthog)

    token = client_ip_mod._CLIENT_IP_CONTEXTVAR.set("8.8.8.8")
    try:
        ee_telemetry.identify_user(
            distinct_id="u-1",
            properties={"email": "user@example.com"},
        )
    finally:
        client_ip_mod._CLIENT_IP_CONTEXTVAR.reset(token)

    fake_posthog.identify.assert_called_once_with(
        "u-1",
        {"email": "user@example.com", "$ip": "8.8.8.8"},
    )
