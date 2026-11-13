"""Chat gets each user's custom skills at the version the user runs, and no
built-in, external-app or invalid skills."""

import io
import zipfile
from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Plugin, User
from onyx.db.skill import (
    SkillSharingChange,
    create_custom_skill__no_commit,
    list_chat_skills,
    list_runtime_skills_for_user,
    replace_skill_bundle,
    set_skill_enabled_for_user,
    set_skill_installation_policy,
)
from onyx.db.users import delete_user_from_db__no_commit
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.content import read_versions_instructions
from onyx.skills.ingest import delete_bundle_blob, ingest_skill_bundle
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
    make_user,
    make_user_credential,
    set_current_version_validity,
)


def _bundle(name: str, version: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: Skill {version}\n---\n\n"
            f"Instructions {version}\n",
        )
    return output.getvalue()


@pytest.fixture
def bundle_ids() -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    file_store = get_default_file_store()
    for bundle_file_id in ids:
        delete_bundle_blob(file_store, bundle_file_id)


@pytest.fixture(scope="module")
def created_user_ids() -> Iterator[list[UUID]]:
    """Users the module made. They go after the last test, once the skill
    table restore has removed the plugins that their marketplaces hold."""
    ids: list[UUID] = []
    yield ids
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        for user_id in ids:
            user = session.get(User, user_id)
            if user is not None:
                delete_user_from_db__no_commit(user, session)
        session.commit()


@pytest.fixture
def users(db_session: Session, created_user_ids: list[UUID]) -> tuple[User, User]:
    author = make_user(db_session, standard_account=True)
    org_only = make_user(db_session, standard_account=True)
    created_user_ids.extend([author.id, org_only.id])
    return author, org_only


def test_chat_skills_use_the_version_each_user_runs(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    bundle_ids: list[str],
    users: tuple[User, User],
) -> None:
    author, org_only = users
    name = f"chat-{author.id.hex[:8]}"
    file_store = get_default_file_store()
    first = ingest_skill_bundle(
        _bundle(name, "one"), f"{name}.zip", file_store, expected_name=name
    )
    bundle_ids.append(first.bundle_file_id)
    skill, _ = create_custom_skill__no_commit(
        first,
        author,
        db_session,
        change=SkillSharingChange(
            public_permission=SkillSharePermission.VIEWER,
            set_public_permission=True,
        ),
    )
    set_skill_installation_policy(skill, SkillInstallationPolicy.DEFAULT, db_session)
    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None
    first_version_id: UUID = plugin.current_version_id
    second = ingest_skill_bundle(
        _bundle(name, "two"), f"{name}.zip", file_store, expected_name=name
    )
    bundle_ids.append(second.bundle_file_id)
    replace_skill_bundle(
        skill=skill,
        ingested=second,
        base_version_id=None,
        user=author,
        skip_if_unchanged=False,
        db_session=db_session,
    )
    plugin.published_version_id = first_version_id
    db_session.commit()

    author_skills = {
        skill.name: skill for skill in list_chat_skills(db_session, author)
    }
    org_skills = {skill.name: skill for skill in list_chat_skills(db_session, org_only)}

    assert author_skills[name].description == "Skill two"
    assert org_skills[name].description == "Skill one"
    assert read_versions_instructions(
        [author_skills[name].version_id, org_skills[name].version_id],
        author.id,
        db_session,
    ) == {
        author_skills[name].version_id: "Instructions two",
        org_skills[name].version_id: "Instructions one",
    }
    built_in_names = {
        runtime.name
        for runtime in list_runtime_skills_for_user(db_session=db_session, user=author)
        if runtime.skill.built_in_skill_id is not None
    }
    assert built_in_names
    assert not built_in_names & set(author_skills)


def test_chat_skills_leave_out_external_app_and_invalid_skills(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User],
) -> None:
    user, _ = users
    app_skill = make_skill(db_session, is_public=True)
    app = make_external_app(
        db_session, skill=app_skill, auth_template={"token": "{token}"}
    )
    make_user_credential(
        db_session, app=app, user=user, user_credentials={"token": "t"}
    )
    invalid_skill = make_skill(db_session, is_public=True)
    valid_skill = make_skill(db_session, is_public=True)
    for skill in (app_skill, invalid_skill, valid_skill):
        set_skill_enabled_for_user(
            skill_id=skill.id, enabled=True, user=user, db_session=db_session
        )
    set_current_version_validity(db_session, invalid_skill.id, False)

    runtime_names = {
        runtime.name
        for runtime in list_runtime_skills_for_user(db_session=db_session, user=user)
    }
    chat_names = {skill.name for skill in list_chat_skills(db_session, user)}

    assert {app_skill.name, valid_skill.name} <= runtime_names
    assert invalid_skill.name not in runtime_names
    assert valid_skill.name in chat_names
    assert not {app_skill.name, invalid_skill.name} & chat_names
