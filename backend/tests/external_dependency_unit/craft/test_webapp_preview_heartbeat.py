"""Preview traffic through the webapp proxy counts as sandbox activity."""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Callable

from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.engine.async_sql_engine import abandon_async_engines
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession, Sandbox
from onyx.server.features.build.webapp_proxy import _touch_preview_heartbeat
from tests.external_dependency_unit.async_client_utils import (
    dispose_loop_async_clients,
)

_OLD_HEARTBEAT = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)


def _backdate_heartbeat(db_session: Session, sandbox: Sandbox) -> None:
    db_session.execute(
        update(Sandbox)
        .where(Sandbox.id == sandbox.id)
        .values(last_heartbeat=_OLD_HEARTBEAT)
    )
    db_session.commit()


def _touch(build_session: BuildSession) -> None:
    abandon_async_engines()

    async def _run() -> None:
        try:
            await _touch_preview_heartbeat(build_session.id)
        finally:
            await dispose_loop_async_clients()

    asyncio.run(_run())


def _heartbeat(db_session: Session, sandbox: Sandbox) -> datetime.datetime | None:
    db_session.expire_all()
    row = db_session.get(Sandbox, sandbox.id)
    assert row is not None
    return row.last_heartbeat


def test_preview_traffic_refreshes_running_sandbox_heartbeat(
    db_session: Session,
    build_session: BuildSession,
    sandbox: Callable[..., Sandbox],
) -> None:
    running = sandbox(status=SandboxStatus.RUNNING)
    db_session.commit()
    _backdate_heartbeat(db_session, running)

    _touch(build_session)
    refreshed = _heartbeat(db_session, running)
    assert refreshed is not None and refreshed > _OLD_HEARTBEAT

    # A second request inside the interval does not write again.
    _backdate_heartbeat(db_session, running)
    _touch(build_session)
    assert _heartbeat(db_session, running) == _OLD_HEARTBEAT


def test_preview_traffic_does_not_touch_sleeping_sandbox(
    db_session: Session,
    build_session: BuildSession,
    sandbox: Callable[..., Sandbox],
) -> None:
    sleeping = sandbox(status=SandboxStatus.SLEEPING)
    db_session.commit()
    _backdate_heartbeat(db_session, sleeping)

    _touch(build_session)
    assert _heartbeat(db_session, sleeping) == _OLD_HEARTBEAT
