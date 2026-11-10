"""Real PostgreSQL and FileStore coverage in a disposable tenant schema."""

import io
import zipfile
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy import event, func, inspect, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.background.celery.tasks.skills.tasks import (
    check_for_orphan_skill_bundle_cleanup,
)
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLockLostError
from onyx.configs.constants import FileOrigin, OnyxRedisLocks
from onyx.db import skill_version
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Base, FileRecord, Skill, SkillVersion, User
from onyx.db.skill import (
    SkillValidityUpdate,
    create_skill_from_bundle__no_commit,
    persist_skill_validity,
    replace_skill_bundle,
)
from onyx.db.skill_version import (
    delete_orphan_skill_bundles,
    delete_unreferenced_skill_bundles,
    repair_skill_version,
    save_skill_version,
    skill_versions,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store import staging
from onyx.file_store.file_store import PresignableFileStore, get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.skill import api
from onyx.server.features.skill.models import SkillBulkActionRequest, SkillPatchRequest
from onyx.skills.bundle import build_single_file_bundle, build_skill_md
from onyx.skills.ingest import ingested_skill_bundle, save_skill_bundle_bytes
from onyx.utils.bundle import compute_bundle_metadata
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.craft.db_helpers import make_user


@pytest.fixture
def tenant(
    isolated_engine: Engine,
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[str, None, None]:
    schema = f"skill_v2_{uuid4().hex}"
    with isolated_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        names = {
            "user",
            "oauth_account",
            "user__pinned_persona",
            "skill",
            "skill_version",
            "skill__user",
            "skill__user_group",
            "user_skill_preference",
            "user_group",
            "user__user_group",
            "sandbox",
            "external_app",
            "external_app__skill",
            "external_app_user_credential",
            "file_record",
            "file_content",
            "key_value_store",
            "cache_store",
        }
        tables = {Base.metadata.tables[name] for name in names}
        while (
            dependencies := {
                fk.column.table for table in tables for fk in table.foreign_keys
            }
            - tables
        ):
            tables |= dependencies
        Base.metadata.create_all(
            connection.execution_options(schema_translate_map={None: schema}),
            tables=list(tables),
        )
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(schema)
    try:
        yield schema
    finally:
        try:
            with get_session_with_current_tenant() as cleanup:
                file_ids = list(cleanup.scalars(select(FileRecord.file_id)))
            store = get_default_file_store()
            for file_id in file_ids:
                store.delete_file(file_id, error_on_missing=False)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
            with isolated_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))


@pytest.fixture
def session(tenant: str) -> Generator[Session, None, None]:
    assert CURRENT_TENANT_ID_CONTEXTVAR.get() == tenant
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture
def user(session: Session) -> User:
    user = make_user(session)
    session.commit()
    return user


def bundle(name: str, body: str = "First instructions") -> bytes:
    return build_single_file_bundle(
        "SKILL.md",
        build_skill_md(
            name=name,
            description="Version test",
            instructions_markdown=body,
        ).encode(),
    )


def upload(content: bytes, filename: str = "skill.zip") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


def versions(skill: Skill, session: Session) -> list[SkillVersion]:
    session.refresh(skill)
    result = list(session.scalars(skill_versions(skill)))
    assert skill.current_version_id == result[0].id
    assert (skill.bundle_file_id, skill.bundle_sha256, skill.is_valid) == (
        result[0].bundle_file_id,
        result[0].bundle_sha256,
        result[0].is_valid,
    )
    return result


@pytest.mark.parametrize("creation", ["upload", "editor", "import"])
def test_all_writers(creation: str, session: Session, user: User) -> None:
    name = f"version-{uuid4().hex[:8]}"
    if creation == "upload":
        response = api.create_custom_skill(upload(bundle(name)), False, user, session)
        skill = session.get(Skill, response.id)
    elif creation == "editor":
        response = api.create_custom_skill_from_editor(
            name,
            "Version test",
            "First instructions",
            auto_enable=False,
            user=user,
            db_session=session,
        )
        skill = session.get(Skill, response.id)
    else:
        with ingested_skill_bundle(
            bundle(name), "skill.zip", get_default_file_store()
        ) as ingested:
            skill, _, _ = create_skill_from_bundle__no_commit(
                ingested, None, False, user, session
            )
            session.commit()
    assert skill is not None
    first = versions(skill, session)[0]
    assert first.created_by_user_id == user.id
    assert first.file_count == 1
    api.replace_current_user_skill_bundle(
        skill.id, upload(bundle(name, "Replaced")), user, session
    )
    assert len(versions(skill, session)) == 2
    api.upload_current_user_skill_files(
        skill.id, upload(b"support", "notes.txt"), user, session
    )
    assert len(versions(skill, session)) == 3
    assert versions(skill, session)[0].file_count == 2
    api.upload_current_user_skill_files(
        skill.id, upload(b"support", "notes.txt"), user, session
    )
    assert len(versions(skill, session)) == 4
    api.remove_current_user_skill_file(skill.id, "notes.txt", user, session)
    assert len(versions(skill, session)) == 5
    request = SkillPatchRequest(instructions_markdown="Edited instructions")
    api.patch_current_user_skill(skill.id, request, user, session)
    assert len(versions(skill, session)) == 6
    current_file = skill.bundle_file_id
    api.patch_current_user_skill(skill.id, request, user, session)
    assert len(versions(skill, session)) == 7
    assert skill.bundle_file_id != current_file
    api.patch_current_user_skill(
        skill.id, SkillPatchRequest(description="Version test"), user, session
    )
    assert len(versions(skill, session)) == 8
    session.expire_all()
    for version in versions(skill, session):
        assert "skill_md" in inspect(version).unloaded
        assert version.created_by_user_id == user.id
        assert version.bundle_file_id is not None
        with get_default_file_store().read_file(version.bundle_file_id) as source:
            bundle_bytes = source.read()
        metadata = compute_bundle_metadata(bundle_bytes)
        assert (metadata.unpacked_size_bytes, metadata.file_count) == (
            version.unpacked_size_bytes,
            version.file_count,
        )
        with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
            raw_skill_md = archive.read("SKILL.md").decode()
        assert version.skill_md == raw_skill_md
        assert version.name == name
        assert version.frontmatter is not None
        assert version.frontmatter["name"] == name
        assert version.frontmatter["description"] == "Version test"


@pytest.mark.parametrize(
    "extra,frontmatter_extra",
    [
        ("created: 2025-01-01", {"created": "2025-01-01"}),
        ("score: .nan", None),
        ("blob: !!binary aGk=", None),
    ],
)
def test_upload_stores_raw_skill_md_when_frontmatter_is_not_json(
    session: Session,
    user: User,
    extra: str,
    frontmatter_extra: dict[str, str] | None,
) -> None:
    name = f"yaml-{uuid4().hex[:8]}"
    raw = f"---\nname: {name}\ndescription: d\n{extra}\n---\n\nBody\n"
    response = api.create_custom_skill(
        upload(raw.encode(), "SKILL.md"), False, user, session
    )
    skill = session.get(Skill, response.id)
    assert skill is not None
    version = versions(skill, session)[0]
    assert version.skill_md == raw
    assert version.name == name
    if frontmatter_extra is None:
        assert version.frontmatter is None
        assert version.metadata_unrepairable
    else:
        assert version.frontmatter == {
            "name": name,
            "description": "d",
            **frontmatter_extra,
        }
        assert not version.metadata_unrepairable


def test_identical_reupload_adds_version(session: Session, user: User) -> None:
    name = f"rezip-{uuid4().hex[:8]}"
    response = api.create_custom_skill(upload(bundle(name)), False, user, session)
    skill = session.get(Skill, response.id)
    assert skill is not None
    api.upload_current_user_skill_files(
        skill.id, upload(b"support", "notes.txt"), user, session
    )
    old = versions(skill, session)[0]
    assert old.bundle_file_id is not None
    with get_default_file_store().read_file(old.bundle_file_id) as source:
        original = source.read()
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(original)) as archive,
        zipfile.ZipFile(output, "w") as target,
    ):
        for info in reversed(archive.infolist()):
            target.writestr(
                zipfile.ZipInfo(info.filename, (2026, 11, 6, 12, 0, 0)),
                archive.read(info),
            )
    assert output.getvalue() != original
    file_count = session.scalar(select(func.count()).select_from(FileRecord))
    assert file_count is not None
    api.replace_current_user_skill_bundle(
        skill.id, upload(output.getvalue()), user, session
    )
    assert (
        session.scalar(select(func.count()).select_from(FileRecord)) == file_count + 1
    )
    assert len(versions(skill, session)) == 3
    assert skill.bundle_file_id != old.bundle_file_id
    assert versions(skill, session)[1] == old


@pytest.mark.parametrize("save", [False, True])
@pytest.mark.parametrize("classified", [False, True])
def test_lazy_validity_copies_to_current_version(
    session: Session, user: User, save: bool, classified: bool
) -> None:
    response = api.create_custom_skill(
        upload(bundle("legacy-validity")), False, user, session
    )
    skill = session.get(Skill, response.id)
    assert skill is not None
    current = versions(skill, session)[0]
    current.is_valid = skill.is_valid = None
    session.commit()
    persist_skill_validity(
        [SkillValidityUpdate(skill.id, skill.bundle_file_id, classified)]
    )
    if save:
        api.patch_current_user_skill(
            skill.id,
            SkillPatchRequest(instructions_markdown="First instructions"),
            user,
            session,
        )
    else:
        repair_skill_version(skill, session)
        session.commit()
    session.expire_all()
    history = versions(skill, session)
    assert history[-1] == current
    assert current.is_valid is classified
    if save:
        assert len(history) == 2 and history[0].is_valid is True
    else:
        assert history == [current]


def test_builtin_cannot_create_version(session: Session, user: User) -> None:
    skill = Skill(name="builtin", description="Built in", built_in_skill_id="builtin")
    session.add(skill)
    session.commit()
    with ingested_skill_bundle(
        bundle("builtin"), "skill.zip", get_default_file_store()
    ) as ingested:
        with pytest.raises(OnyxError, match="Only custom skills"):
            save_skill_version(skill, ingested, user.id, session, initial=True)
        session.rollback()
    assert session.scalar(select(func.count()).select_from(SkillVersion)) == 0


def test_failed_write_rolls_back(session: Session, user: User) -> None:
    name = f"rollback-{uuid4().hex[:8]}"
    store = get_default_file_store()
    with pytest.raises(RuntimeError, match="abort"):
        with ingested_skill_bundle(bundle(name), "skill.zip", store) as ingested:
            record = store.read_file_record(ingested.bundle_file_id)
            create_skill_from_bundle__no_commit(ingested, None, False, user, session)
            session.rollback()
            raise RuntimeError("abort")
    assert session.scalar(select(Skill).where(Skill.name == name)) is None
    assert not store.has_file(
        ingested.bundle_file_id, FileOrigin.SKILL_BUNDLE, "application/zip"
    )
    assert isinstance(store, PresignableFileStore)
    assert store._stat_object(record.bucket_name, record.object_key) is None


def test_failed_replacement_preserves_pointer(session: Session, user: User) -> None:
    name = f"failed-{uuid4().hex[:8]}"
    response = api.create_custom_skill(upload(bundle(name)), False, user, session)
    skill = session.get(Skill, response.id)
    assert skill is not None
    original = versions(skill, session)[0]
    store = get_default_file_store()
    with pytest.raises(IntegrityError):
        with ingested_skill_bundle(
            bundle(name, "Rejected"), "skill.zip", store
        ) as ingested:
            replace_skill_bundle(
                skill=skill, ingested=ingested, creator_id=uuid4(), db_session=session
            )
    session.commit()
    assert versions(skill, session) == [original]
    assert skill.bundle_file_id == original.bundle_file_id


def test_concurrent_replacements(tenant: str, session: Session, user: User) -> None:
    name = f"concurrent-{uuid4().hex[:8]}"
    response = api.create_custom_skill(upload(bundle(name)), False, user, session)
    skill_id, creator_id = response.id, user.id
    session.commit()

    def replace(body: str) -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
        try:
            with get_session_with_current_tenant() as writer:
                skill = writer.get(Skill, skill_id)
                assert skill is not None
                with ingested_skill_bundle(
                    bundle(name, body), "skill.zip", get_default_file_store()
                ) as ingested:
                    replace_skill_bundle(
                        skill=skill,
                        ingested=ingested,
                        creator_id=creator_id,
                        db_session=writer,
                    )
                    writer.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(replace, ["Second", "Third"]))
    skill = session.get(Skill, skill_id)
    assert skill is not None
    assert [version.version_number for version in versions(skill, session)] == [3, 2, 1]


@pytest.mark.parametrize("compression", [0, 99])
def test_corrupt_legacy_bundle_does_not_block_repair_or_replace(
    session: Session, user: User, compression: int
) -> None:
    response = api.create_custom_skill(
        upload(bundle("corrupt-history")), False, user, session
    )
    skill = session.get(Skill, response.id)
    assert skill is not None
    data = bytearray(bundle(skill.name))
    # Central-directory method 99 is unsupported; an invalid signature is not a ZIP.
    offset = data.index(b"PK\x01\x02") + 10
    data[offset : offset + 2] = compression.to_bytes(2, "little")
    store = get_default_file_store()
    skill.bundle_file_id = save_skill_bundle_bytes(
        bytes(data) if compression else b"not a ZIP",
        display_name="old.zip",
        file_store=store,
    )
    session.commit()
    repair_skill_version(skill, session)
    session.commit()
    session.expire_all()
    assert len(versions(skill, session)) == 2
    api.replace_current_user_skill_bundle(
        skill.id, upload(bundle(skill.name, "Fixed")), user, session
    )
    assert len(versions(skill, session)) == 3
    assert versions(skill, session)[0].unpacked_size_bytes is not None


@pytest.mark.parametrize("damage", ["missing", "invalid_zip", "different_content"])
def test_identical_reupload_replaces_damaged_current_bundle(
    session: Session, user: User, damage: str
) -> None:
    content = bundle("recovered")
    response = api.create_custom_skill(upload(content), False, user, session)
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.bundle_file_id is not None
    lost_file = skill.bundle_file_id
    store = get_default_file_store()
    store.delete_file(lost_file)
    if damage != "missing":
        store.save_file(
            io.BytesIO(
                b"corrupt"
                if damage == "invalid_zip"
                else bundle("recovered", "Corrupted instructions")
            ),
            "damaged.zip",
            FileOrigin.SKILL_BUNDLE,
            "application/zip",
            file_id=lost_file,
        )
    api.replace_current_user_skill_bundle(skill.id, upload(content), user, session)
    assert len(versions(skill, session)) == 2
    assert skill.bundle_file_id != lost_file
    with store.read_file(skill.bundle_file_id) as source:
        assert compute_bundle_metadata(source.read()) == compute_bundle_metadata(
            content
        )


@pytest.mark.parametrize("writer", ["replace", "editor", "patch"])
def test_identical_write_commits_version_before_push_failure(
    writer: str, session: Session, user: User
) -> None:
    response = api.create_custom_skill(
        upload(bundle("noop-push")), False, user, session
    )
    api.upload_current_user_skill_files(
        response.id, upload(b"notes", "notes.txt"), user, session
    )
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.bundle_file_id is not None
    store = get_default_file_store()
    with store.read_file(skill.bundle_file_id) as source:
        original = source.read()
    file_ids = set(session.scalars(select(FileRecord.file_id)))
    with pytest.MonkeyPatch.context() as patch:

        def fail_push(*_args: object) -> None:
            raise RuntimeError("push failed after content commit")

        patch.setattr(api, "push_skill_to_affected_sandboxes", fail_push)
        patch.setattr(api, "push_skills_for_users", fail_push)
        with pytest.raises(RuntimeError, match="push failed"):
            if writer == "replace":
                api.replace_current_user_skill_bundle(
                    skill.id, upload(original), user, session
                )
            elif writer == "editor":
                api.upload_current_user_skill_files(
                    skill.id, upload(b"notes", "notes.txt"), user, session
                )
            else:
                api.patch_current_user_skill(
                    skill.id,
                    SkillPatchRequest(instructions_markdown="First instructions"),
                    user,
                    session,
                )
    session.expire_all()
    history = versions(skill, session)
    assert len(history) == 3
    assert set(session.scalars(select(FileRecord.file_id))) - file_ids == {
        history[0].bundle_file_id
    }


def skill_with_versions(session: Session, user: User, count: int) -> Skill:
    name = f"kept-{uuid4().hex[:8]}"
    response = api.create_custom_skill(upload(bundle(name)), False, user, session)
    for number in range(2, count + 1):
        api.replace_current_user_skill_bundle(
            response.id, upload(bundle(name, f"Version {number}")), user, session
        )
    skill = session.get(Skill, response.id)
    assert skill is not None
    return skill


def stored_bundles(session: Session) -> set[str]:
    session.expire_all()
    return set(
        session.scalars(
            select(FileRecord.file_id).where(
                FileRecord.file_origin == FileOrigin.SKILL_BUNDLE
            )
        )
    )


def make_old(file_ids: set[str], session: Session) -> None:
    session.execute(
        update(FileRecord)
        .where(FileRecord.file_id.in_(file_ids))
        .values(created_at=func.now() - timedelta(hours=2))
    )
    session.commit()


class FailingStore:
    def delete_file(self, file_id: str, error_on_missing: bool = True) -> None:
        raise RuntimeError(f"store unavailable: {file_id} {error_on_missing}")


def test_eleventh_version_prunes_oldest_bundle(session: Session, user: User) -> None:
    skill = skill_with_versions(session, user, 10)
    oldest = versions(skill, session)[-1]
    oldest_file = oldest.bundle_file_id
    assert oldest_file is not None and len(stored_bundles(session)) == 10
    api.replace_current_user_skill_bundle(
        skill.id, upload(bundle(skill.name, "Eleventh")), user, session
    )
    history = versions(skill, session)
    assert [version.version_number for version in history] == list(range(11, 0, -1))
    assert history[-1].bundle_file_id is None
    assert all(version.bundle_file_id for version in history[:10])
    assert stored_bundles(session) == {v.bundle_file_id for v in history[:10]}


def test_concurrent_writes_keep_ten_bundles(
    tenant: str, session: Session, user: User
) -> None:
    skill = skill_with_versions(session, user, 9)
    skill_id, user_id, name = skill.id, user.id, skill.name
    session.commit()

    def replace(body: str) -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
        try:
            with get_session_with_current_tenant() as writer:
                writer_user = writer.get(User, user_id)
                assert writer_user is not None
                api.replace_current_user_skill_bundle(
                    skill_id, upload(bundle(name, body)), writer_user, writer
                )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(replace, ["A", "B", "C", "D"]))
    history = versions(skill, session)
    assert [version.version_number for version in history] == list(range(13, 0, -1))
    assert [version.bundle_file_id is None for version in history] == [False] * 10 + [
        True
    ] * 3
    assert stored_bundles(session) == {v.bundle_file_id for v in history[:10]}


def test_delete_skill_with_twelve_versions(session: Session, user: User) -> None:
    skill = skill_with_versions(session, user, 12)
    skill_id = skill.id
    assert len(versions(skill, session)) == 12
    assert len(stored_bundles(session)) == 10
    api.delete_current_user_skill(skill_id, user, session)
    count = select(func.count()).where(SkillVersion.skill_id == skill_id)
    assert session.scalar(count) == 0
    assert stored_bundles(session) == set()


def test_bulk_delete_removes_every_retained_bundle(
    session: Session, user: User
) -> None:
    first = skill_with_versions(session, user, 3)
    second = skill_with_versions(session, user, 2)
    assert len(stored_bundles(session)) == 5
    response = api.bulk_update_skills(
        SkillBulkActionRequest(skill_ids=[first.id, second.id], action="delete"),
        user,
        session,
    )
    assert response.failed == []
    assert session.scalar(select(func.count()).select_from(SkillVersion)) == 0
    assert stored_bundles(session) == set()


def test_cleanup_task_retries_failed_deletes(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = skill_with_versions(session, user, 2)
    with monkeypatch.context() as patch:
        patch.setattr(staging, "get_default_file_store", FailingStore)
        api.delete_current_user_skill(skill.id, user, session)
    leaked = stored_bundles(session)
    assert len(leaked) == 2
    # Younger than one hour: an upload may not have committed its row yet.
    assert delete_orphan_skill_bundles() == 0
    assert stored_bundles(session) == leaked
    make_old(leaked, session)
    assert delete_orphan_skill_bundles() == 2
    assert stored_bundles(session) == set()


def test_cleanup_keeps_files_in_use(session: Session, user: User) -> None:
    store = get_default_file_store()
    legacy = Skill(
        name="pointerless",
        description="Old writer",
        bundle_file_id=save_skill_bundle_bytes(
            bundle("pointerless"), display_name="old.zip", file_store=store
        ),
        author_user_id=user.id,
    )
    session.add(legacy)
    deleted = skill_with_versions(session, user, 1)
    kept = skill_with_versions(session, user, 1)
    shared = versions(deleted, session)[0].bundle_file_id
    assert shared is not None
    # A historical anomaly: another skill's version uses the same blob.
    session.add(SkillVersion(skill_id=kept.id, version_number=2, bundle_file_id=shared))
    other_origin = store.save_file(
        io.BytesIO(b"chat"), "chat.txt", FileOrigin.CHAT_UPLOAD, "text/plain"
    )
    session.commit()
    api.delete_current_user_skill(deleted.id, user, session)
    in_use = stored_bundles(session)
    assert {legacy.bundle_file_id, shared} <= in_use
    make_old(in_use | {other_origin}, session)
    assert delete_orphan_skill_bundles() == 0
    assert stored_bundles(session) == in_use
    assert store.has_file(other_origin, FileOrigin.CHAT_UPLOAD, "text/plain")


def test_rolled_back_prune_keeps_files(session: Session, user: User) -> None:
    skill = skill_with_versions(session, user, 10)
    before = stored_bundles(session)
    with ingested_skill_bundle(
        bundle(skill.name, "Rolled back"), "skill.zip", get_default_file_store()
    ) as ingested:
        stale = replace_skill_bundle(
            skill=skill, ingested=ingested, creator_id=user.id, db_session=session
        )
        session.rollback()
    assert stale and set(stale) < before
    delete_unreferenced_skill_bundles(stale, session)
    assert before <= stored_bundles(session)
    assert all(version.bundle_file_id for version in versions(skill, session))


def test_cleanup_task_uses_configured_cache_and_tenant(
    tenant: str, session: Session
) -> None:
    store = get_default_file_store()
    orphan = save_skill_bundle_bytes(
        bundle("orphan"), display_name="orphan.zip", file_store=store
    )
    make_old({orphan}, session)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("another_tenant")
    try:
        check_for_orphan_skill_bundle_cleanup.run(tenant_id=tenant)
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == "another_tenant"
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    assert orphan not in stored_bundles(session)


def test_cleanup_advances_past_failed_batch(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = get_default_file_store()
    files = {
        save_skill_bundle_bytes(
            bundle(f"orphan-{index}"), display_name="orphan.zip", file_store=store
        )
        for index in range(3)
    }
    for index, file_id in enumerate(sorted(files)):
        session.execute(
            update(FileRecord)
            .where(FileRecord.file_id == file_id)
            .values(
                created_at=func.now() - timedelta(hours=2) + timedelta(seconds=index)
            )
        )
    session.commit()
    failed = set(sorted(files)[:2])
    delete = store.delete_file

    def selective_delete(file_id: str, error_on_missing: bool = True) -> None:
        if file_id in failed:
            raise RuntimeError("This bundle cannot be deleted yet")
        delete(file_id, error_on_missing=error_on_missing)

    monkeypatch.setattr(skill_version, "_ORPHAN_BATCH_SIZE", 2)
    monkeypatch.setattr(store, "delete_file", selective_delete)
    monkeypatch.setattr(staging, "get_default_file_store", lambda: store)
    assert delete_orphan_skill_bundles() == 0
    assert delete_orphan_skill_bundles() == 1
    assert stored_bundles(session) == failed
    failed.clear()
    assert delete_orphan_skill_bundles() == 0
    assert delete_orphan_skill_bundles() == 2
    assert stored_bundles(session) == set()


def test_lite_poller_retries_orphan_bundle(session: Session) -> None:
    from onyx.background.periodic_poller import _build_periodic_tasks

    orphan = save_skill_bundle_bytes(
        bundle("lite-orphan"),
        display_name="orphan.zip",
        file_store=get_default_file_store(),
    )
    make_old({orphan}, session)
    tasks = _build_periodic_tasks()
    assert len({task.lock_id for task in tasks}) == len(tasks)
    task = next(task for task in tasks if task.name == "skill-bundle-cleanup")
    task.run_fn()
    assert orphan not in stored_bundles(session)


def test_pruning_does_not_load_cleared_history(session: Session, user: User) -> None:
    skill = skill_with_versions(session, user, 30)
    skill_id, user_id, name = skill.id, user.id, skill.name
    session.expunge_all()
    writer = session.get(User, user_id)
    assert writer is not None
    loaded: list[SkillVersion] = []

    def record_load(_session: Session, instance: object) -> None:
        if isinstance(instance, SkillVersion):
            loaded.append(instance)

    event.listen(session, "loaded_as_persistent", record_load)
    try:
        api.replace_current_user_skill_bundle(
            skill_id, upload(bundle(name, "Next version")), writer, session
        )
    finally:
        event.remove(session, "loaded_as_persistent", record_load)
    assert len(loaded) <= 4
    assert len(stored_bundles(session)) == 10


def test_cleanup_lost_lease_keeps_cursor_pending(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = get_default_file_store()
    files = {
        save_skill_bundle_bytes(
            bundle(f"lease-{n}"), display_name="orphan.zip", file_store=store
        )
        for n in range(2)
    }
    make_old(files, session)
    backend = get_cache_backend()
    lock = backend.lock(
        OnyxRedisLocks.ORPHAN_SKILL_BUNDLE_CLEANUP_BEAT_LOCK, timeout=120
    )
    renewals = 0

    def expire_after_delete(_ttl: float) -> None:
        nonlocal renewals
        renewals += 1
        if renewals == 2:
            lock.release()
            raise CacheLockLostError("expired during delete")

    with monkeypatch.context() as patch:
        patch.setattr(skill_version, "get_cache_backend", lambda: backend)
        patch.setattr(backend, "lock", lambda *_args, **_kwargs: lock)
        patch.setattr(lock, "extend", expire_after_delete)
        with pytest.raises(CacheLockLostError):
            delete_orphan_skill_bundles()
    assert len(stored_bundles(session)) == 1
    with pytest.raises(KvKeyNotFoundError):
        get_kv_store().load("orphan_skill_bundle_cursor", refresh_cache=True)
    assert delete_orphan_skill_bundles() == 1
    assert stored_bundles(session) == set()


def test_cleanup_retries_failures_despite_new_arrivals(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = get_default_file_store()
    failed = save_skill_bundle_bytes(
        bundle("failed"), display_name="old.zip", file_store=store
    )
    make_old({failed}, session)
    with monkeypatch.context() as patch:
        patch.setattr(staging, "get_default_file_store", FailingStore)
        assert delete_orphan_skill_bundles() == 0
    for number in range(4):
        new = save_skill_bundle_bytes(
            bundle(f"arrival-{number}"), display_name="new.zip", file_store=store
        )
        make_old({new}, session)
        delete_orphan_skill_bundles()
    assert failed not in stored_bundles(session)


@pytest.mark.parametrize("first_pass_count", [0, 1])
def test_orphan_cleanup_deadline_resumes_without_skipping(
    session: Session, monkeypatch: pytest.MonkeyPatch, first_pass_count: int
) -> None:
    store = get_default_file_store()
    files = {
        save_skill_bundle_bytes(
            bundle(f"timed-{n}"), display_name="skill.zip", file_store=store
        )
        for n in range(3)
    }
    make_old(files, session)
    clock = iter([0] + [0] * first_pass_count + [31, 31, 31])
    with monkeypatch.context() as patch:
        patch.setattr(skill_version, "monotonic", lambda: next(clock), raising=False)
        assert delete_orphan_skill_bundles() == first_pass_count
    assert len(stored_bundles(session)) == 3 - first_pass_count
    assert delete_orphan_skill_bundles() == 3 - first_pass_count
    assert stored_bundles(session) == set()
