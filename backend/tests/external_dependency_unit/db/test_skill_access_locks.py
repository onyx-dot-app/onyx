"""Storage must not hold the tenant membership lock; mixed writes stay atomic."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from typing import IO
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, text, true
from sqlalchemy import delete as sql_delete
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SkillSharePermission
from onyx.db.models import (
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.skill import set_skill_enabled_for_user
from onyx.db.users import _membership_lock_id, lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.server.features.skill import api
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.skills.ingest import IngestedBundle
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.craft.db_helpers import (
    make_group,
    make_skill,
    make_user,
    share_skill_with_group,
    share_skill_with_user,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import client_for
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    stored_bundles,
    upload,
    versions,
)

pytestmark = pytest.mark.usefixtures(
    "tenant_context", "enable_ee", "initialize_file_store"
)


def try_lock_group_membership(db_session: Session) -> None:
    """Take the membership lock without waiting; raise when another holds it."""
    if not db_session.scalar(
        text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
        {"lock_id": _membership_lock_id(get_current_tenant_id())},
    ):
        raise OnyxError(OnyxErrorCode.CONFLICT, "Membership lock is held.")


@pytest.mark.parametrize(
    "operation",
    ["patch", "visibility", "bundle", "upload", "remove", "restore", "batch"],
)
def test_content_storage_does_not_hold_membership(
    db_session: Session, operation: str
) -> None:
    user = make_user(db_session, is_admin=True)
    db_session.commit()
    response = api.create_custom_skill(
        upload(bundle(f"locks-{uuid4().hex}")), False, user, db_session
    )
    skill = db_session.get(Skill, response.id)
    assert skill is not None and skill.current_version_id is not None
    api.upload_current_user_skill_files(
        skill.id, upload(b"support", "notes.txt"), user, db_session
    )
    store = get_default_file_store()
    original_read, original_ingest = store.read_file, api.ingest_skill_bundle
    checked = 0
    blocked: list[str] = []
    cleanup_ids = [skill.id]
    original_delete = api.delete_bundle_blob

    def check_lock() -> None:
        nonlocal checked
        with get_session_with_current_tenant() as other:
            try:
                try_lock_group_membership(other)
                other.scalar(
                    select(Skill.id)
                    .where(Skill.id == skill.id)
                    .with_for_update(nowait=True)
                )
                actor = other.get(User, user.id)
                assert actor is not None
                set_skill_enabled_for_user(
                    skill_id=skill.id, enabled=True, user=actor, db_session=other
                )
                other.commit()
                checked += 1
            except Exception:
                blocked.append("Storage blocked an access writer")
                raise

    def read(
        file_id: str,
        mode: str | None = None,
        use_tempfile: bool = False,
        *,
        max_bytes: int | None = None,
    ) -> IO[bytes]:
        check_lock()
        return original_read(file_id, mode, use_tempfile, max_bytes=max_bytes)

    def ingest(
        content: bytes,
        filename: str | None,
        file_store: FileStore,
        *,
        expected_name: str | None = None,
        stored: bool = False,
    ) -> IngestedBundle:
        check_lock()
        return original_ingest(
            content, filename, file_store, expected_name=expected_name, stored=stored
        )

    def delete(file_store: FileStore, file_id: str) -> None:
        check_lock()
        original_delete(file_store, file_id)

    try:
        with (
            get_session_with_current_tenant() as auth_session,
            patch.object(store, "read_file", side_effect=read),
            patch.object(api, "ingest_skill_bundle", side_effect=ingest),
            patch("onyx.skills.ingest.ingest_skill_bundle", side_effect=ingest),
            patch.object(api, "delete_bundle_blob", side_effect=delete),
        ):
            auth_user = auth_session.get(User, user.id)
            assert auth_user is not None and auth_user is not user
            client = client_for(auth_user, db_session)
            path = f"/skills/custom/{skill.id}"
            if operation == "patch":
                result = client.patch(
                    path, json={"description": "Changed", "public_permission": "VIEWER"}
                )
            elif operation == "visibility":
                result = client.patch(path, json={"public_permission": "VIEWER"})
            elif operation == "bundle":
                result = client.put(
                    f"{path}/bundle",
                    files={"bundle": ("skill.zip", bundle(skill.name, "Changed"))},
                )
            elif operation == "upload":
                result = client.post(
                    f"{path}/files", files={"upload": ("extra.txt", b"extra")}
                )
            elif operation == "remove":
                result = client.delete(f"{path}/files", params={"path": "notes.txt"})
            elif operation == "restore":
                result = client.post(
                    f"{path}/versions/{skill.current_version_id}/restore"
                )
            else:
                content = bundle(f"batch-{uuid4().hex}")
                result = client.post(
                    "/skills/custom/batch",
                    data={
                        "auto_enable": "false",
                        "sharing": json.dumps(
                            {
                                "public_permission": "VIEWER",
                                "installation_policy": "DEFAULT",
                            }
                        ),
                    },
                    files=[
                        ("bundles", ("first.zip", content)),
                        ("bundles", ("second.zip", content)),
                    ],
                )
                assert result.status_code == 200, result.text
                assert (
                    len(result.json()["imported"])
                    == len(result.json()["not_imported"])
                    == 1
                )
                cleanup_ids.extend(
                    UUID(item["skill"]["id"]) for item in result.json()["imported"]
                )
            assert result.status_code == 200, result.text
            assert (checked > 0 or operation == "visibility") and not blocked
        db_session.refresh(skill)
        if operation == "patch":
            assert skill.description == "Changed"
            assert skill.public_permission == SkillSharePermission.VIEWER
    finally:
        db_session.rollback()
        for skill_id in cleanup_ids:
            api.delete_current_user_skill(skill_id, user, db_session)


@pytest.mark.parametrize("race", ["content", "direct", "group", "manager", "publish"])
def test_staged_patch_rechecks_content_and_access(
    db_session: Session, race: str
) -> None:
    owner = make_user(db_session, is_admin=True)
    actor = make_user(
        db_session, standard_account=True, is_admin=race in {"manager", "publish"}
    )
    db_session.commit()
    response = api.create_custom_skill(
        upload(bundle(f"race-{uuid4().hex}")), False, owner, db_session
    )
    skill = db_session.get(Skill, response.id)
    assert skill is not None
    if race == "group":
        group = make_group(db_session)
        db_session.add(User__UserGroup(user_id=actor.id, user_group_id=group.id))
        share_skill_with_group(db_session, skill, group, SkillSharePermission.EDITOR)
    elif race != "manager":
        share_skill_with_user(db_session, skill, actor, SkillSharePermission.EDITOR)
    before = stored_bundles(db_session)
    db_session.commit()
    ingest = api.ingest_skill_bundle
    raced = False

    def concurrent_write(
        content: bytes,
        filename: str | None,
        file_store: FileStore,
        *,
        expected_name: str | None = None,
        stored: bool = False,
    ) -> IngestedBundle:
        nonlocal raced, before
        if not raced:
            raced = True
            with get_session_with_current_tenant() as other:
                writer = other.get(User, owner.id)
                assert writer is not None
                if race == "content":
                    api.patch_current_user_skill(
                        skill.id,
                        SkillPatchRequest(description="Concurrent"),
                        writer,
                        other,
                    )
                else:
                    lock_group_membership(other)
                    if race == "group":
                        other.execute(
                            sql_delete(Skill__UserGroup).where(
                                Skill__UserGroup.skill_id == skill.id
                            )
                        )
                    elif race in {"manager", "publish"}:
                        other.execute(
                            sql_delete(User__UserGroup).where(
                                User__UserGroup.user_id == actor.id,
                                User__UserGroup.user_group_id.in_(
                                    select(UserGroup.id).where(
                                        UserGroup.name == "Admin"
                                    )
                                )
                                if race == "publish"
                                else true(),
                            )
                        )
                        recompute_user_permissions__no_commit(actor.id, other)
                    else:
                        other.execute(
                            sql_delete(Skill__User).where(
                                Skill__User.skill_id == skill.id
                            )
                        )
                    other.commit()
                before = stored_bundles(other)
        return ingest(
            content, filename, file_store, expected_name=expected_name, stored=stored
        )

    try:
        with (
            get_session_with_current_tenant() as auth_session,
            patch.object(api, "ingest_skill_bundle", side_effect=concurrent_write),
        ):
            auth_user = auth_session.get(User, actor.id)
            assert auth_user is not None and auth_user is not actor
            result = client_for(auth_user, db_session).patch(
                f"/skills/custom/{skill.id}",
                json={"description": "Must not commit", "public_permission": "VIEWER"}
                if race == "publish"
                else {"description": "Must not commit"},
            )
        assert result.status_code == (
            409 if race == "content" else 403 if race in {"manager", "publish"} else 404
        ), result.text
        db_session.refresh(skill)
        assert skill.description == (
            "Concurrent" if race == "content" else "Version test"
        )
        assert len(versions(skill, db_session)) == (2 if race == "content" else 1)
        assert stored_bundles(db_session) == before
    finally:
        db_session.rollback()
        api.delete_current_user_skill(skill.id, owner, db_session)


def test_toggle_waits_for_membership_before_locking_user(
    isolated_engine: Engine,
) -> None:
    with Session(isolated_engine) as writer:
        user = make_user(writer, standard_account=True)
        skill = make_skill(writer, author_user_id=user.id)
        user_id, skill_id = user.id, skill.id
        writer.commit()
        lock_group_membership(writer)
        waiting: Queue[int] = Queue()

        def toggle() -> None:
            with Session(isolated_engine) as worker:
                worker.execute(text("SET LOCAL statement_timeout = '10s'"))
                pid = worker.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                waiting.put(pid)
                actor = worker.get(User, user_id)
                assert actor is not None
                set_skill_enabled_for_user(
                    skill_id=skill_id, enabled=True, user=actor, db_session=worker
                )
                worker.commit()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(toggle)
            try:
                pid = waiting.get(timeout=5)
                with isolated_engine.connect() as observer:
                    deadline = time.monotonic() + 5
                    while not observer.scalar(
                        select(func.cardinality(func.pg_blocking_pids(pid)))
                    ):
                        assert time.monotonic() < deadline
                        time.sleep(0.01)
                recompute_user_permissions__no_commit(user_id, writer)
                writer.commit()
            finally:
                writer.rollback()
            future.result(timeout=15)


@pytest.mark.parametrize(
    "operation", ["batch", "patch", "create", "editor", "bundle", "upload"]
)
def test_commit_ack_failure_keeps_referenced_upload(
    db_session: Session, operation: str
) -> None:
    user = make_user(db_session, is_admin=True)
    db_session.commit()
    name = f"ack-{uuid4().hex}"
    initial = None
    if operation in {"patch", "bundle", "upload"}:
        initial = api.create_custom_skill(upload(bundle(name)), False, user, db_session)
    commit = db_session.commit

    def lose_ack() -> None:
        commit()
        raise ConnectionError("Commit acknowledgement lost")

    store = get_default_file_store()
    with (
        patch.object(db_session, "commit", side_effect=lose_ack),
        patch.object(store, "delete_file", wraps=store.delete_file) as cleanup,
    ):
        with pytest.raises(ConnectionError, match="acknowledgement"):
            if operation == "patch":
                assert initial is not None
                api.patch_current_user_skill(
                    initial.id,
                    SkillPatchRequest(
                        description="Committed",
                        public_permission=SkillSharePermission.VIEWER,
                    ),
                    user,
                    db_session,
                )
            elif operation == "create":
                api.create_custom_skill(upload(bundle(name)), False, user, db_session)
            elif operation == "editor":
                api.create_custom_skill_from_editor(
                    name,
                    "Created",
                    "Instructions",
                    upload=None,
                    auto_enable=False,
                    external_app_id=None,
                    sharing=None,
                    user=user,
                    db_session=db_session,
                )
            elif operation == "bundle":
                assert initial is not None
                api.replace_current_user_skill_bundle(
                    initial.id, upload(bundle(name, "Committed")), user, db_session
                )
            elif operation == "upload":
                assert initial is not None
                api.upload_current_user_skill_files(
                    initial.id, upload(b"committed", "extra.txt"), user, db_session
                )
            else:
                api.create_custom_skills_batch(
                    [upload(bundle(name))],
                    auto_enable=False,
                    sharing=None,
                    user=user,
                    db_session=db_session,
                )
        cleanup.assert_not_called()
    skill = db_session.scalar(select(Skill).where(Skill.name == name))
    assert skill is not None and skill.bundle_file_id is not None
    try:
        with get_default_file_store().read_file(skill.bundle_file_id) as stream:
            assert stream.read()
    finally:
        api.delete_current_user_skill(skill.id, user, db_session)


@pytest.mark.parametrize("operation", ["create", "editor"])
def test_create_conflict_releases_locks_before_blob_cleanup(
    db_session: Session, operation: str
) -> None:
    user = make_user(db_session, is_admin=True)
    db_session.commit()
    name = f"conflict-{uuid4().hex}"
    existing = api.create_custom_skill(upload(bundle(name)), True, user, db_session)
    before = stored_bundles(db_session)
    db_session.commit()
    store = get_default_file_store()
    original_delete = store.delete_file
    lock_free: list[bool] = []

    def delete(file_id: str, *, error_on_missing: bool = True) -> None:
        with get_session_with_current_tenant() as observer:
            try:
                try_lock_group_membership(observer)
            except OnyxError:
                lock_free.append(False)
                return
            lock_free.append(True)
        original_delete(file_id, error_on_missing=error_on_missing)

    try:
        with patch.object(store, "delete_file", side_effect=delete):
            client = client_for(user, db_session)
            if operation == "create":
                result = client.post(
                    "/skills/custom", files={"bundle": ("skill.zip", bundle(name))}
                )
            else:
                result = client.post(
                    "/skills/custom/editor",
                    data={
                        "name": name,
                        "description": "New",
                        "instructions_markdown": "New",
                    },
                )
            assert result.status_code == 409, result.text
        assert lock_free == [True]
        assert stored_bundles(db_session) == before
        assert (
            db_session.scalar(
                select(func.count()).select_from(Skill).where(Skill.name == name)
            )
            == 1
        )
    finally:
        db_session.rollback()
        api.delete_current_user_skill(existing.id, user, db_session)
