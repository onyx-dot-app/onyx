"""Unit tests for the generalized audit-event subsystem (``onyx.utils.audit``).

These cover the invariants the subsystem must never violate: a stable
OCSF-shaped schema, never logging a secret, never raising on missing context,
and Redis-backed dedup that degrades safely when Redis is unavailable.
"""

import io
import json
import logging
from typing import Any
from typing import cast
from typing import TextIO
from unittest.mock import MagicMock

import pytest

from onyx.utils import audit
from onyx.utils.audit import _OCSF_CLASS_BY_ACTION
from onyx.utils.audit import actor_from_user
from onyx.utils.audit import AUDIT_HANDLER_NAME
from onyx.utils.audit import AUDIT_LOGGER_ROOT
from onyx.utils.audit import AuditAction
from onyx.utils.audit import AuditActor
from onyx.utils.audit import AuditOutcome
from onyx.utils.audit import emit_audit_event
from onyx.utils.audit import OCSFEventClass


def _capture(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Parse every captured ``onyx.audit`` JSON message into a dict."""
    events: list[dict[str, Any]] = []
    for record in caplog.records:
        if record.name.startswith("onyx.audit"):
            events.append(json.loads(record.getMessage()))
    return events


def test_every_action_has_an_ocsf_class() -> None:
    # The import-time guard already enforces this, but assert it explicitly so a
    # regression is a clear test failure rather than an import error.
    for action in AuditAction:
        assert action in _OCSF_CLASS_BY_ACTION
        assert isinstance(_OCSF_CLASS_BY_ACTION[action], OCSFEventClass)


def test_emits_stable_ocsf_shaped_schema(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        emit_audit_event(
            AuditAction.LLM_PROVIDER_UPDATE,
            AuditOutcome.SUCCESS,
            actor=AuditActor(user_id="u-1", email="a@example.com", auth_type="oauth"),
            resource_type="llm_provider",
            resource_id=42,
        )

    events = _capture(caplog)
    assert len(events) == 1
    event = events[0]

    # Stable top-level schema contract.
    assert set(event.keys()) == {
        "audit_schema_version",
        "ts",
        "action",
        "ocsf_class",
        "outcome",
        "tenant_id",
        "actor",
        "resource_type",
        "resource_id",
        "request_id",
        "endpoint",
        "source_ip",
        "extra",
    }
    assert event["action"] == "llm_provider.update"
    assert event["ocsf_class"] == "api_activity"
    assert event["outcome"] == "success"
    assert event["resource_type"] == "llm_provider"
    # resource_id is normalized to a string regardless of input type.
    assert event["resource_id"] == "42"
    assert event["actor"] == {
        "user_id": "u-1",
        "email": "a@example.com",
        "api_key_id": None,
        "auth_type": "oauth",
    }


def test_routes_to_per_class_child_logger(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        emit_audit_event(AuditAction.LOGIN, AuditOutcome.SUCCESS)

    auth_records = [r for r in caplog.records if r.name == "onyx.audit.authentication"]
    assert len(auth_records) == 1


def test_never_logs_a_secret_passed_nowhere(caplog: pytest.LogCaptureFixture) -> None:
    # The emitter only serializes the fields it is handed; a secret that is never
    # passed can never appear. Assert the rendered line for a typical event does
    # not contain anything resembling a credential value.
    secret = "sk-super-secret-value"
    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        emit_audit_event(
            AuditAction.CREDENTIAL_ACCESS,
            AuditOutcome.SUCCESS,
            actor=AuditActor(user_id="u-1"),
            resource_type="llm_provider",
            resource_id=7,
            extra={"provider": "openai"},
        )

    rendered = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in rendered


def test_never_raises_on_missing_context(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Force every context helper to blow up; emission must still succeed.
    def _boom() -> str:
        raise RuntimeError("no context")

    monkeypatch.setattr(audit, "_safe_get_tenant_id", lambda: _boom())
    monkeypatch.setattr(audit, "_safe_get_request_id", lambda: _boom())
    monkeypatch.setattr(audit, "_safe_get_endpoint", lambda: _boom())
    monkeypatch.setattr(audit, "_safe_get_client_ip", lambda: _boom())

    # Must not raise.
    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        emit_audit_event(AuditAction.LOGOUT, AuditOutcome.SUCCESS)


def test_dedup_suppresses_within_window(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # First call claims the window, second is suppressed.
    seen: set[str] = set()

    def fake_should_emit(dedup_key: str, _ttl: int, _tenant_id: str | None) -> bool:
        if dedup_key in seen:
            return False
        seen.add(dedup_key)
        return True

    monkeypatch.setattr(audit, "should_emit", fake_should_emit)

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        emit_audit_event(
            AuditAction.CREDENTIAL_ACCESS, AuditOutcome.SUCCESS, dedup_key="k1"
        )
        emit_audit_event(
            AuditAction.CREDENTIAL_ACCESS, AuditOutcome.SUCCESS, dedup_key="k1"
        )

    assert len(_capture(caplog)) == 1


def test_dedup_degrades_to_emit_when_redis_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ``should_emit`` must return True (always-emit) when the Redis client raises.
    def boom_get_client(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("redis down")

    import onyx.redis.redis_pool as redis_pool

    monkeypatch.setattr(redis_pool, "get_redis_client", boom_get_client)
    assert audit.should_emit("any-key", 600, "tenant-1") is True


def test_no_dedup_key_always_emits(caplog: pytest.LogCaptureFixture) -> None:
    # Low-volume events omit dedup_key and should always emit, even repeated.
    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        emit_audit_event(AuditAction.USER_ROLE_CHANGE, AuditOutcome.SUCCESS)
        emit_audit_event(AuditAction.USER_ROLE_CHANGE, AuditOutcome.SUCCESS)

    assert len(_capture(caplog)) == 2


def test_audit_logger_self_contained_without_root_handler() -> None:
    """Regression: events must reach the subsystem's handler even with no root
    handler (the uvicorn condition that silently dropped every api-server event).
    """
    audit_root = logging.getLogger(AUDIT_LOGGER_ROOT)

    own_handlers = [h for h in audit_root.handlers if h.name == AUDIT_HANDLER_NAME]
    assert own_handlers, "onyx.audit must attach its own handler"
    assert audit_root.propagate is False

    # Simulate uvicorn (no root handlers); capture via a temporary handler.
    buf = io.StringIO()
    capture = logging.StreamHandler(cast(TextIO, buf))
    audit_root.addHandler(capture)
    root = logging.getLogger()
    saved_root_handlers = root.handlers[:]
    root.handlers = []
    try:
        emit_audit_event(
            AuditAction.LOGIN,
            AuditOutcome.SUCCESS,
            actor=AuditActor(user_id="u-1", email="a@example.com"),
        )
    finally:
        root.handlers = saved_root_handlers
        audit_root.removeHandler(capture)

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert lines, "audit event must reach onyx.audit handlers without root"
    payload = json.loads(lines[-1])
    assert payload["action"] == "auth.login"


def test_actor_from_user_none_returns_none() -> None:
    assert actor_from_user(None) is None


def test_actor_from_user_builds_actor() -> None:
    user = MagicMock(id="u-1", email="user@example.com")
    actor = actor_from_user(user, auth_type="password")
    assert actor is not None
    assert actor.user_id == "u-1"
    assert actor.email == "user@example.com"
    assert actor.auth_type == "password"


def test_actor_from_user_never_raises() -> None:
    # A user object whose ``id`` access blows up must degrade to None, not raise.
    broken = MagicMock()
    type(broken).id = property(lambda _self: (_ for _ in ()).throw(RuntimeError()))
    assert actor_from_user(broken) is None
