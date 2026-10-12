"""A signup through the api server builds its tenant from the stored snapshot:
after the rollout job has snapshotted the template, the new tenant is stamped
at head and carries the template's built-in skill ids, which a chain build
would have minted fresh. Runs the real migration job and the real api."""

import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import column, delete, select, table
from sqlalchemy.orm import Session

from ee.onyx.db import tenant_snapshot
from ee.onyx.db.user_tenant_mapping import get_tenant_id_for_email
from onyx.db.engine.shard_routing import get_shard_for_tenant
from onyx.db.engine.sql_engine import get_catalog_session, get_session_with_tenant
from onyx.db.models import AvailableTenant, Skill
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

_BACKEND_DIR = __file__[: __file__.index("/tests/")]


def _run_rollout_job_with_snapshot() -> None:
    """The rollout job with the snapshot flag, against the compose database."""
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
        env={**os.environ, "PYTHONPATH": _BACKEND_DIR},
    )
    assert result.returncode == 0, result.stdout


def _drain_tenant_pool() -> None:
    """Signup hands out a pool tenant first, and tenants pooled before the snapshot
    were built through the chain. Any refill from here on is itself a clone."""
    with get_catalog_session() as db_session:
        db_session.execute(delete(AvailableTenant))
        db_session.commit()


def _built_in_skill_ids(db_session: Session) -> dict[str, str]:
    rows = db_session.execute(
        select(Skill.built_in_skill_id, Skill.id).where(
            Skill.built_in_skill_id.is_not(None)
        )
    ).all()
    return {str(built_in_id): str(skill_id) for built_in_id, skill_id in rows}


def test_signup_builds_the_tenant_from_the_snapshot(
    reset_multitenant: None,  # noqa: ARG001
) -> None:
    _run_rollout_job_with_snapshot()
    head: str | None = tenant_snapshot.get_head_revision()
    assert head is not None
    _drain_tenant_pool()

    unique = uuid4().hex
    test_user: DATestUser = UserManager.create(
        name=f"clone_{unique}", email=f"clone_{unique}@example.com"
    )

    tenant_id: str = get_tenant_id_for_email(test_user.email)
    shard: str = get_shard_for_tenant(tenant_id)
    assert tenant_snapshot.get_snapshot(shard, head) is not None

    # The lightweight table needs the schema spelled out to read the tenant's row.
    version_table = table("alembic_version", column("version_num"), schema=tenant_id)
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        stamped = db_session.scalar(select(version_table.c.version_num))
        tenant_skills = _built_in_skill_ids(db_session)
    assert stamped == head

    # A chain build mints new skill ids. Only a clone carries the template's.
    with tenant_snapshot.template_session(shard) as db_session:
        template_skills = _built_in_skill_ids(db_session)
    assert template_skills
    assert tenant_skills == template_skills
