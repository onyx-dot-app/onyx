"""Concurrent edits must read the version published by the preceding lock holder."""

import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from typing import Literal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import (
    associate_custom_skill_with_external_app__no_commit,
    get_skills_for_external_app,
    replace_custom_skill_associations__no_commit,
)
from onyx.db.models import ExternalApp, Skill, User
from onyx.db.skill import SkillManagementPolicy, fetch_skill
from onyx.db.skill_version import persist_skill_version_validity
from onyx.server.features.skill import api
from onyx.skills.bundle import inspect_custom_bundle
from onyx.skills.content import read_custom_skill_bundle_bytes
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.db.test_skill_version_writes import bundle, upload
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user


@pytest.mark.parametrize(
    "operation",
    ["upload", "associate", "replace-associations", "validity-new-version"],
)
def test_waiting_edit_reads_committed_version(
    operation: Literal[
        "upload",
        "associate",
        "replace-associations",
        "validity-new-version",
    ],
    tenant: str,
    session: Session,
    user: User,
    isolated_engine: Engine,
) -> None:
    response = api.create_custom_skill(
        upload(bundle("locked-reader")), False, user, session
    )
    app = ExternalApp(
        name="Review app",
        app_type=ExternalAppType.CUSTOM,
        enabled=True,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
    )
    session.add(app)
    session.commit()
    app_id, user_id, skill_id = app.id, user.id, response.id
    skill = session.get(Skill, skill_id)
    assert skill is not None and skill.current_version is not None
    version_id = skill.current_version.id
    bundle_file_id = skill.current_version.bundle_file_id
    if operation == "validity-new-version":
        skill.current_version.is_valid = skill.is_valid = None
        session.commit()
    waiting_pid: Queue[int] = Queue()

    def second_edit() -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
        try:
            with get_session_with_current_tenant() as writer:
                writer.execute(text("SET LOCAL statement_timeout = '10s'"))
                second_user = writer.get(User, user_id)
                assert second_user is not None
                pid = writer.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                waiting_pid.put(pid)
                if operation == "validity-new-version":
                    persist_skill_version_validity(
                        skill_id=skill_id,
                        version_id=version_id,
                        bundle_file_id=bundle_file_id,
                        is_valid=False,
                        db_session=writer,
                    )
                elif operation == "upload":
                    api.upload_current_user_skill_files(
                        skill_id, upload(b"second", "second.txt"), second_user, writer
                    )
                elif operation == "associate":
                    associate_custom_skill_with_external_app__no_commit(
                        writer, external_app_id=app_id, skill_id=skill_id
                    )
                else:
                    replace_custom_skill_associations__no_commit(
                        writer, external_app_id=app_id, skill_ids=[skill_id]
                    )
                writer.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    first = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        db_session=session,
        user=user,
        lock_for_update=True,
    )
    assert first is not None
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(second_edit)
        try:
            pid = waiting_pid.get(timeout=5)
            with isolated_engine.connect() as observer:
                deadline = time.monotonic() + 5
                while not observer.scalar(
                    select(func.cardinality(func.pg_blocking_pids(pid)))
                ):
                    assert time.monotonic() < deadline, (
                        "second edit never waited for the skill lock"
                    )
                    time.sleep(0.01)
            if operation == "validity-new-version":
                api.replace_current_user_skill_bundle(
                    skill_id,
                    upload(bundle("locked-reader", "New instructions")),
                    user,
                    session,
                )
            else:
                api.upload_current_user_skill_files(
                    skill_id, upload(b"first", "first.txt"), user, session
                )
        finally:
            session.rollback()
        future.result(timeout=15)

    session.expire_all()
    skill = session.get(Skill, skill_id)
    assert skill is not None
    if operation == "validity-new-version":
        assert skill.current_version_id != version_id
        assert skill.current_version is not None
        assert skill.current_version.bundle_file_id != bundle_file_id
        assert skill.current_is_valid is True and skill.is_valid is True
        return
    paths = {
        file.path
        for file in inspect_custom_bundle(read_custom_skill_bundle_bytes(skill)).files
    }
    assert "first.txt" in paths
    if operation == "upload":
        assert "second.txt" in paths
    else:
        assert [row.id for row in get_skills_for_external_app(session, app_id)] == [
            skill_id
        ]
