from dataclasses import replace
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.onyxbot.slack import listener
from onyx.utils import fleet_telemetry as fleet
from onyx.utils.fleet_query_telemetry import QueryObservation


@pytest.mark.parametrize("exit_mode", ["normal", "signal", "startup_error"])
def test_listener_starts_sender_before_handlers_and_closes_on_exit(
    monkeypatch: pytest.MonkeyPatch, exit_mode: str
) -> None:
    monkeypatch.delenv("DISABLE_TELEMETRY", raising=False)
    monkeypatch.setattr(fleet, "_client", None)
    config: fleet.TelemetryConfig = fleet.TelemetryConfig(
        "http://localhost:8787",
        "test-token",
        "11111111-1111-4111-8111-111111111111",
        "test-slack",
        b"test-privacy-key",
    )
    monkeypatch.setattr(
        fleet.TelemetryConfig,
        "from_env",
        lambda service: replace(config, service=service),
    )
    # Run the real lifecycle and queue, without starting network delivery.
    monkeypatch.setattr(fleet.BoundedTelemetry, "start", Mock())
    monkeypatch.setattr(listener.SqlEngine, "init_engine", Mock())
    monkeypatch.setattr(listener, "set_is_ee_if_available", Mock())
    monkeypatch.setattr(listener, "setup_tracing", Mock())
    started: Mock = Mock(wraps=listener.start_telemetry)
    monkeypatch.setattr(listener, "start_telemetry", started)
    senders: list[fleet.BoundedTelemetry] = []

    def handler() -> Any:
        started.assert_called_once_with("slack")
        sender: fleet.BoundedTelemetry | None = fleet.start_telemetry("slack")
        assert sender is not None and not sender.closed
        senders.append(sender)
        observation: QueryObservation = QueryObservation(channel="slack", mode="chat")
        observation.answer()
        observation.finish()
        if exit_mode == "signal":
            raise SystemExit(0)
        if exit_mode == "startup_error":
            raise RuntimeError("handler startup failed")
        return Mock(running=False)

    monkeypatch.setattr(listener, "SlackbotHandler", handler)
    if exit_mode == "normal":
        listener.main()
    else:
        with pytest.raises(SystemExit if exit_mode == "signal" else RuntimeError):
            listener.main()
    assert len(senders) == 1 and senders[0].closed
    payloads: list[dict[str, Any]] = []

    def transport(_url: str, **kwargs: Any) -> Any:
        import gzip
        import io
        import json

        payloads.extend(json.loads(gzip.decompress(kwargs["data"]))["events"])
        response: Mock = Mock(ok=True, status_code=200, headers={})
        response.raw = io.BytesIO(b'{"results":[{"index":0,"status":"accepted"}]}')
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    assert senders[0].flush_once(transport)
    assert len(payloads) == 1
    assert payloads[0]["service"] == "slack"
    assert payloads[0]["data"]["channel"] == "slack"
    assert payloads[0]["data"]["request_count"] == 1
