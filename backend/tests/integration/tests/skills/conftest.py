from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Sandbox
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(autouse=True)
def _reset_db(reset: None) -> None:  # noqa: ARG001
    """Auto-reset DB before each skills test."""


def get_sandbox_id_for_user(user: DATestUser) -> UUID:
    """Look up the user's Sandbox row ID.

    Each user has at most one sandbox row; raises ``AssertionError`` if
    no row exists (call ``provision_sandbox_for`` first).
    """
    user_uuid = UUID(user.id)
    with get_session_with_current_tenant() as db_session:
        row = db_session.execute(
            select(Sandbox).where(Sandbox.user_id == user_uuid)
        ).scalar_one_or_none()
    assert row is not None, (
        f"No Sandbox row for user {user.id}; call provision_sandbox_for() first."
    )
    return row.id


def skills_dir_for_user(user: DATestUser, slug: str) -> Path:
    """On-disk path where ``slug`` would land for ``user`` (local backend only).

    Tests should ``.exists()``-check the returned path after a push to
    verify the bundle was extracted onto the user's sandbox workspace.
    """
    sandbox_id = get_sandbox_id_for_user(user)
    return Path(SANDBOX_BASE_PATH) / str(sandbox_id) / "managed" / "skills" / slug


def provision_sandbox_for(user: DATestUser) -> dict[str, Any]:
    """Provision a sandbox for ``user`` by creating an empty build session.

    Returns the create-session response body. The local backend inserts the
    ``Sandbox`` row synchronously, so callers can immediately resolve the
    sandbox path via :func:`skills_dir_for_user`.
    """
    response = BuildSessionManager.create(user)
    # Sanity: the sandbox row exists after this call (local backend).
    _ = get_sandbox_id_for_user(user)
    return response
