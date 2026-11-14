"""A skill delete removes every version of the skill and every version's
bundle.

The file records and deleted rows are read from the database."""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.models import FileRecord, Plugin, PluginSkill, PluginVersion, Skill
from onyx.server.features.skill.models import SkillBulkResponse, SkillResponse
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import (
    SkillManager,
    build_minimal_bundle,
)
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _skill_with_versions(user: DATestUser, count: int) -> SkillResponse:
    name = f"delete-{uuid4().hex[:8]}"
    skill = SkillManager.create_custom(user, name=name)
    for number in range(2, count + 1):
        SkillManager.replace_bundle(
            skill,
            build_minimal_bundle(name, description=f"Version {number}"),
            user,
        )
    return skill


def _bundles_by_version(skill_id: UUID) -> dict[int, str | None]:
    with get_session_with_current_tenant() as db_session:
        rows = db_session.execute(
            select(PluginVersion.version_number, PluginVersion.bundle_file_id).where(
                PluginVersion.plugin_id == skill_id
            )
        ).tuples()
        return dict(rows.all())


def _existing_files(file_ids: set[str]) -> set[str]:
    with get_session_with_current_tenant() as db_session:
        return set(
            db_session.scalars(
                select(FileRecord.file_id).where(FileRecord.file_id.in_(file_ids))
            )
        )


def _assert_skill_removed(skill_id: UUID, file_ids: set[str]) -> None:
    with get_session_with_current_tenant() as db_session:
        assert db_session.get(Plugin, skill_id) is None
        assert db_session.get(Skill, skill_id) is None
        assert (
            db_session.scalar(
                select(func.count())
                .select_from(PluginVersion)
                .where(PluginVersion.plugin_id == skill_id)
            )
            == 0
        )
        assert (
            db_session.scalar(
                select(func.count())
                .select_from(PluginSkill)
                .join(PluginVersion, PluginVersion.id == PluginSkill.plugin_version_id)
                .where(PluginVersion.plugin_id == skill_id)
            )
            == 0
        )
    assert _existing_files(file_ids) == set()


def test_delete_removes_every_version_and_bundle(basic_user: DATestUser) -> None:
    skill = _skill_with_versions(basic_user, 3)
    file_ids = {
        file_id
        for file_id in _bundles_by_version(skill.id).values()
        if file_id is not None
    }
    assert len(file_ids) == 3

    SkillManager.delete_custom(skill, basic_user)

    _assert_skill_removed(skill.id, file_ids)


def test_bulk_delete_removes_every_version_and_bundle(
    basic_user: DATestUser,
) -> None:
    skills = [_skill_with_versions(basic_user, 3) for _ in range(2)]
    file_ids = {
        file_id
        for skill in skills
        for file_id in _bundles_by_version(skill.id).values()
        if file_id is not None
    }
    assert len(file_ids) == 6

    response = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        headers=basic_user.headers,
        json={"skill_ids": [str(skill.id) for skill in skills], "action": "delete"},
    )
    response.raise_for_status()
    assert SkillBulkResponse.model_validate(response.json()).failed == []

    for skill in skills:
        _assert_skill_removed(skill.id, set())
    assert _existing_files(file_ids) == set()
