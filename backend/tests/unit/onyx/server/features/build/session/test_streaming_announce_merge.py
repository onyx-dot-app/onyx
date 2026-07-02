"""Tests for tenant-contextvar propagation in the announce-merge stream."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest

from onyx.server.features.build.session import streaming
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def test_drive_events_thread_inherits_caller_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The events-pump thread is spawned via the context-preserving helper, so
    lazy DB access inside the event iterator (e.g. event-bus creation) sees the
    caller's tenant contextvar instead of raising "Tenant ID is not set"."""
    monkeypatch.setattr(streaming, "get_cache_backend", lambda **_: object())
    monkeypatch.setattr(
        streaming.approval_cache,
        "pop_announcement",
        lambda *_a, **_k: None,
    )

    tenant_id = "tenant_abc"
    seen_in_thread: list[str | None] = []

    def event_iter() -> Generator[Any, None, None]:
        # Runs in the spawned drive_events thread.
        seen_in_thread.append(CURRENT_TENANT_ID_CONTEXTVAR.get())
        yield "event-1"

    # The helper snapshots the caller's context, so the spawned thread must
    # observe the tenant set here — not the contextvar's default.
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        events = list(
            streaming.merge_events_with_announces(
                event_iter(),
                session_id=uuid4(),
                tenant_id=tenant_id,
            )
        )
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert events == ["event-1"]
    assert seen_in_thread == [tenant_id]
