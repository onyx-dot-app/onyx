"""Concurrent edits must read the version published by the preceding lock holder."""

import time
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Queue
from typing import Literal

import pytest
from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import (
    associate_custom_skill_with_external_app__no_commit,
    get_skills_for_external_app,
    replace_custom_skill_associations__no_commit,
    upsert_external_app_user_credential__no_commit,
)
from onyx.db.models import ExternalApp, Skill, User, UserSkillLimitBlock
from onyx.db.skill import (
    SkillManagementPolicy,
    connect_external_app_within_skill_limit__no_commit,
    fetch_skill,
)
from onyx.db.skill_version import persist_skill_version_validity
from onyx.db.users import lock_group_membership
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill import api
from onyx.skills.bundle import inspect_custom_bundle
from onyx.skills.content import read_custom_skill_bundle_bytes
from onyx.skills.limits import SKILL_WRITE_MAX_BYTES
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.craft.db_helpers import make_external_app
from tests.external_dependency_unit.db.test_skill_version_writes import bundle, upload
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user
from tests.external_dependency_unit.db.test_skill_write_limit import MIB, sized_skill


@pytest.mark.parametrize(
    "operation",
    ["upload", "associate", "replace-associations", "validity", "validity-new-version"],
)
def test_waiting_edit_reads_committed_version(
    operation: Literal[
        "upload",
        "associate",
        "replace-associations",
        "validity",
        "validity-new-version",
    ],
    tenant: str,
    session: Session,
    user: User,
    isolated_engine: Engine,
) -> None:
    response = api.create_custom_skill(
        upload(bundle("locked-reader")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
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
    if operation in {"validity", "validity-new-version"}:
        skill.current_version.is_valid = None
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
                if operation in {"validity", "validity-new-version"}:
                    persist_skill_version_validity(
                        skill_id=skill_id,
                        version_id=version_id,
                        bundle_file_id=bundle_file_id,
                        is_valid=False,
                        db_session=writer,
                    )
                elif operation == "upload":
                    with pytest.raises(
                        OnyxError, match="Skill content changed"
                    ) as conflict:
                        api.upload_current_user_skill_files(
                            skill_id,
                            upload(b"second", "second.txt"),
                            second_user,
                            writer,
                            http_request=Request({"type": "http"}),
                        )
                    assert conflict.value.status_code == 409
                    writer.rollback()
                    api.upload_current_user_skill_files(
                        skill_id,
                        upload(b"second", "second.txt"),
                        second_user,
                        writer,
                        http_request=Request({"type": "http"}),
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

    lock_group_membership(session)
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
            if operation in {"validity", "validity-new-version"}:
                api.replace_current_user_skill_bundle(
                    skill_id,
                    upload(
                        bundle(
                            "locked-reader",
                            "New instructions"
                            if operation == "validity-new-version"
                            else "First instructions",
                        )
                    ),
                    user,
                    session,
                    http_request=Request({"type": "http"}),
                )
            else:
                api.upload_current_user_skill_files(
                    skill_id,
                    upload(b"first", "first.txt"),
                    user,
                    session,
                    http_request=Request({"type": "http"}),
                )
        finally:
            session.rollback()
        future.result(timeout=15)

    session.expire_all()
    skill = session.get(Skill, skill_id)
    assert skill is not None
    if operation in {"validity", "validity-new-version"}:
        if operation == "validity-new-version":
            assert skill.current_version_id != version_id
            assert skill.current_version is not None
            assert skill.current_version.bundle_file_id != bundle_file_id
        else:
            assert skill.current_version_id == version_id
        assert skill.current_is_valid is True
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


def test_connect_checks_the_skills_left_by_a_concurrent_unlink(
    tenant: str, session: Session, user: User, isolated_engine: Engine
) -> None:
    """An unlink cannot leave a limit block on a Skill that no app links."""
    sized_skill(session, size=SKILL_WRITE_MAX_BYTES - MIB, author=user)
    skill = sized_skill(session, size=2 * MIB)
    app = make_external_app(
        session, skill=skill, auth_template={"Authorization": "Bearer {token}"}
    )
    session.commit()
    app_id, user_id, skill_id = app.id, user.id, skill.id
    admin_pid: Queue[int] = Queue()

    def unlink() -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
        try:
            with get_session_with_current_tenant() as admin:
                admin.execute(text("SET LOCAL statement_timeout = '10s'"))
                pid = admin.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                admin_pid.put(pid)
                replace_custom_skill_associations__no_commit(
                    admin, external_app_id=app_id, skill_ids=[]
                )
                admin.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    with ThreadPoolExecutor(max_workers=1) as pool:
        unlinked: list[Future[None]] = []

        def connect() -> None:
            unlinked.append(pool.submit(unlink))
            pid = admin_pid.get(timeout=5)
            with isolated_engine.connect() as observer:
                deadline = time.monotonic() + 5
                # The unlink either waits for this connection or commits first.
                while not unlinked[0].done() and not observer.scalar(
                    select(func.cardinality(func.pg_blocking_pids(pid)))
                ):
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
            upsert_external_app_user_credential__no_commit(
                session,
                external_app_id=app_id,
                user_id=user_id,
                user_credentials={"token": "secret"},
            )

        try:
            connect_external_app_within_skill_limit__no_commit(
                app_id, user_id, connect, session
            )
            session.commit()
        finally:
            session.rollback()
        unlinked[0].result(timeout=15)

    assert get_skills_for_external_app(session, app_id) == []
    assert (
        session.scalar(
            select(UserSkillLimitBlock.skill_id).where(
                UserSkillLimitBlock.user_id == user_id,
                UserSkillLimitBlock.skill_id == skill_id,
            )
        )
        is None
    )
