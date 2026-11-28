"""GET /admin/security/audit-status reports what Onyx wrote, from the real
cache backend."""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import cast

import pytest
from sqlalchemy.orm import Session

from ee.onyx.server.security.api import get_audit_stream_status
from ee.onyx.server.security.models import AuditClassStatus, AuditStreamStatus
from ee.onyx.utils import audit as ee_audit
from ee.onyx.utils import audit_stats
from ee.onyx.utils.credential_audit import emit_credential_access
from onyx.cache.factory import get_cache_backend
from onyx.db.models import User
from onyx.utils.audit import AuditAction, AuditOutcome, emit_audit_event
from shared_configs.contextvars import get_current_tenant_id

pytestmark = pytest.mark.usefixtures("tenant_context", "audit_stream")


@pytest.fixture
def real_stats(
    db_session: Session,  # noqa: ARG001
    audit_stream: None,  # noqa: ARG001 — set up first, so this undoes its stub
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Record stats in the real cache (``enterprise_audit`` stubs them) and
    remove them afterwards."""
    monkeypatch.setattr(ee_audit, "record_event", audit_stats.record_event)
    monkeypatch.setattr(
        "ee.onyx.utils.credential_audit.record_event", audit_stats.record_event
    )
    monkeypatch.setattr(
        "ee.onyx.utils.credential_audit._should_emit", lambda *_args: True
    )
    cache = get_cache_backend(tenant_id=get_current_tenant_id())
    cache.delete_prefix("audit:stats:")
    audit_stats._last_event_written_at.clear()
    try:
        yield
    finally:
        audit_stats._queue.join()
        cache.delete_prefix("audit:stats:")
        audit_stats._last_event_written_at.clear()


@pytest.mark.usefixtures("real_stats")
def test_status_counts_written_events() -> None:
    before = datetime.now(tz=timezone.utc).replace(microsecond=0)
    emit_audit_event(AuditAction.LOGIN, AuditOutcome.SUCCESS)
    emit_audit_event(AuditAction.LOGOUT, AuditOutcome.SUCCESS)
    emit_audit_event(AuditAction.API_KEY_CREATE, AuditOutcome.SUCCESS)
    emit_credential_access("connector", "google_drive", 1, user_id="u-1")
    # The writer thread records counts off the caller's path.
    audit_stats._queue.join()

    status = get_audit_stream_status(_=cast(User, None))

    by_class = {entry.event_class: entry for entry in status.classes}
    assert status.enabled is True
    assert by_class["authentication"].events_last_24h == 2
    assert by_class["api_activity"].events_last_24h == 1
    assert by_class["credential_access"].events_last_24h == 1
    assert by_class["group_management"].events_last_24h == 0
    assert by_class["group_management"].last_event_at is None
    last_login = by_class["authentication"].last_event_at
    assert last_login is not None and last_login >= before


def _authentication(status: AuditStreamStatus) -> AuditClassStatus:
    return next(e for e in status.classes if e.event_class == "authentication")


@pytest.mark.usefixtures("real_stats")
def test_last_event_time_is_written_once_a_minute() -> None:
    emit_audit_event(AuditAction.LOGIN, AuditOutcome.SUCCESS)
    audit_stats._queue.join()
    first = _authentication(get_audit_stream_status(_=cast(User, None)))
    emit_audit_event(AuditAction.LOGIN, AuditOutcome.SUCCESS)
    audit_stats._queue.join()
    second = _authentication(get_audit_stream_status(_=cast(User, None)))

    assert second.events_last_24h == 2
    assert second.last_event_at == first.last_event_at


@pytest.mark.usefixtures("real_stats")
def test_a_late_writer_does_not_move_the_last_event_back() -> None:
    audit_stats._write_event(get_current_tenant_id(), "authentication", 2_000.0)
    audit_stats._last_event_written_at.clear()
    audit_stats._write_event(get_current_tenant_id(), "authentication", 1_000.0)

    cache = get_cache_backend(tenant_id=get_current_tenant_id())
    raw = cache.get("audit:stats:last:authentication")
    assert raw is not None and float(raw) == 2_000.0
