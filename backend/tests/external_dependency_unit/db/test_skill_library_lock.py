"""Library name locks use tenant identity, not the connection search path."""

from uuid import uuid4

import pytest
from psycopg2.errors import LockNotAvailable
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import OperationalError

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.skill_library import lock_skill_library_names
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@pytest.mark.parametrize("different_tenant", [False, True])
def test_library_name_lock_isolated_by_tenant(
    isolated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    different_tenant: bool,
) -> None:
    monkeypatch.setattr(
        "onyx.db.engine.sql_engine.get_engine_for_tenant", lambda _: isolated_engine
    )
    first_tenant = f"skill_lock_{uuid4().hex}"
    second_tenant = f"skill_lock_{uuid4().hex}" if different_tenant else first_tenant
    name = f"skill-{uuid4().hex}"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(first_tenant)
    try:
        with (
            get_session_with_tenant(tenant_id=first_tenant) as first,
            get_session_with_tenant(tenant_id=second_tenant) as second,
        ):
            assert first.scalar(select(func.current_schema())) == second.scalar(
                select(func.current_schema())
            )
            lock_skill_library_names(None, [name], first)
            CURRENT_TENANT_ID_CONTEXTVAR.set(second_tenant)
            second.execute(text("SET LOCAL lock_timeout = '100ms'"))
            if different_tenant:
                lock_skill_library_names(None, [name], second)
            else:
                with pytest.raises(OperationalError) as caught:
                    lock_skill_library_names(None, [name], second)
                assert isinstance(caught.value.orig, LockNotAvailable)
                second.rollback()
                first.rollback()
                lock_skill_library_names(None, [name], second)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
