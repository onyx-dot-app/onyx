"""A signup through the api server builds its tenant from the stored snapshot:
after the rollout job has snapshotted the template, the new tenant is stamped
at head and carries the template's built-in skill ids, which a chain build
would have minted fresh. Runs the real migration job and the real api."""

import subprocess
import sys
from uuid import uuid4

from sqlalchemy import column, select, table

from ee.onyx.db import tenant_snapshot
from ee.onyx.db.user_tenant_mapping import get_tenant_id_for_email
from onyx.db.engine.shard_registry import get_default_shard_name, get_engine_for_shard
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import Skill
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

_BACKEND_DIR = __file__[: __file__.index("/tests/")]


def _run_rollout_job_with_snapshot() -> None:
    """The job the cloud deploy runs, flag included, against the compose database."""
    result = subprocess.run(
        [
            sys.executable,
            "alembic/run_multitenant_migrations.py",
            "--snapshot-template",
            "--jobs",
            "2",
        ],
        cwd=_BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def _built_in_skill_ids_in_template(shard: str) -> dict[str, str]:
    with tenant_snapshot.template_session(shard) as db_session:
        rows = db_session.execute(
            select(Skill.built_in_skill_id, Skill.id).where(
                Skill.built_in_skill_id.is_not(None)
            )
        ).all()
    return {str(built_in_id): str(skill_id) for built_in_id, skill_id in rows}


def _built_in_skill_ids_in_tenant(tenant_id: str) -> dict[str, str]:
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        rows = db_session.execute(
            select(Skill.built_in_skill_id, Skill.id).where(
                Skill.built_in_skill_id.is_not(None)
            )
        ).all()
    return {str(built_in_id): str(skill_id) for built_in_id, skill_id in rows}


def test_signup_builds_the_tenant_from_the_snapshot(
    reset_multitenant: None,  # noqa: ARG001
) -> None:
    shard = get_default_shard_name()
    _run_rollout_job_with_snapshot()
    head = tenant_snapshot.get_head_revision()
    assert head is not None
    assert tenant_snapshot.get_snapshot(shard, head) is not None

    unique = uuid4().hex
    test_user: DATestUser = UserManager.create(
        name=f"clone_{unique}", email=f"clone_{unique}@example.com"
    )
    assert UserManager.is_admin(test_user)

    tenant_id = get_tenant_id_for_email(test_user.email)
    version_table = table("alembic_version", column("version_num"), schema=tenant_id)
    with get_engine_for_shard(shard).connect() as connection:
        stamped = connection.scalar(select(version_table.c.version_num))
    assert stamped == head

    # A chain build mints new skill ids. Only a clone carries the template's.
    template_skills = _built_in_skill_ids_in_template(shard)
    assert template_skills
    assert _built_in_skill_ids_in_tenant(tenant_id) == template_skills
