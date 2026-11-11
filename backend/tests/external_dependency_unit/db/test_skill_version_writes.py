"""Real PostgreSQL and FileStore coverage in a disposable tenant schema."""

import io
import zipfile
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Base, FileRecord, Skill, SkillVersion, User
from onyx.db.skill import (
    SkillValidityUpdate,
    create_skill_from_bundle__no_commit,
    persist_skill_validity,
    replace_skill_bundle,
)
from onyx.db.skill_version import (
    repair_skill_version,
    save_skill_version,
    skill_versions,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import PresignableFileStore, get_default_file_store
from onyx.server.features.skill import api
from onyx.server.features.skill.models import SkillPatchRequest
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
