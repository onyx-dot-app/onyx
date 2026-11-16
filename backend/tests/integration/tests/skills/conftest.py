"""Fixtures and helpers for skills integration tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import update

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.models import User__UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import ADMIN_USER_NAME, API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module", autouse=True)
def _module_reset_and_seed() -> None:
    reset_all()
    admin = UserManager.create(name=ADMIN_USER_NAME)
    LLMProviderManager.create(user_performing_action=admin)


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    """Direct database reads and writes in the test process."""
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def share_skill(
    user: DATestUser, skill_id: UUID | str, body: dict[str, Any]
) -> httpx.Response:
    return client.patch(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/share",
        json=body,
        headers=user.headers,
    )


def visible_skill_ids(user: DATestUser) -> set[UUID]:
    return {skill.id for skill in SkillManager.list_for_user(user).customs}


def promote_to_manager(user_id: str, group_id: int) -> None:
    with get_session_with_current_tenant() as db_session:
        promoted = db_session.scalars(
            update(User__UserGroup)
            .where(
                User__UserGroup.user_id == UUID(user_id),
                User__UserGroup.user_group_id == group_id,
            )
            .values(is_manager=True)
            .returning(User__UserGroup.user_id)
        ).all()
        assert len(promoted) == 1
        recompute_user_permissions__no_commit(UUID(user_id), db_session)
        db_session.commit()
