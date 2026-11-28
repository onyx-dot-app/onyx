"""Parse audit events out of caplog.

These return nothing unless a handler is attached to ``onyx.audit``. The unit
conftests do that automatically; external-dependency tests use ``audit_stream``.
"""

import json
from typing import Any

import pytest

from onyx.configs.constants import QueryHistoryType
from onyx.server.security import store as security_store
from onyx.server.settings import store as settings_store
from onyx.server.settings.models import Settings
from onyx.utils.audit import DEFAULT_AUDIT_EVENT_CATEGORIES, AuditEventCategory


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


def use_audit_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    categories: tuple[AuditEventCategory, ...] = DEFAULT_AUDIT_EVENT_CATEGORIES,
    include_query_text: bool = False,
    query_history_type: QueryHistoryType = QueryHistoryType.NORMAL,
) -> None:
    """Pin the audit categories, the query text setting and the query history
    type that the EE emitter reads."""
    settings = security_store._build_env_defaults().model_copy(
        update={
            "audit_event_categories": categories,
            "audit_include_query_text": include_query_text,
        }
    )
    monkeypatch.setattr(security_store, "get_security_settings", lambda: settings)
    monkeypatch.setattr(
        settings_store,
        "load_settings",
        lambda **_kwargs: Settings(query_history_type=query_history_type),
    )
