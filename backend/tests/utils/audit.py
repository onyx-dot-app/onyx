"""Parse audit events out of caplog.

These return nothing unless a handler is attached to ``onyx.audit``. The unit
conftests do that automatically; external-dependency tests use ``audit_stream``.
"""

import json
from typing import Any

import pytest


def audit_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name.startswith("onyx.audit")
    ]


def audit_actions(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [event["action"] for event in audit_events(caplog)]


def events_for(caplog: pytest.LogCaptureFixture, action: str) -> list[dict[str, Any]]:
    return [event for event in audit_events(caplog) if event["action"] == action]
