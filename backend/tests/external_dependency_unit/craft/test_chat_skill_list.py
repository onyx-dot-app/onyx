"""Chat gets each user's custom skills at the version the user runs, and no
built-in, external-app or invalid skills."""

import io
import zipfile
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import (
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import Plugin, User
from onyx.db.plugin import (
    get_visible_versions_skill_md,
    set_plugin_preferences__no_commit,
)
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
from onyx.skills.built_in import CHAT_BUILT_IN_SKILL_IDS
from onyx.skills.content import read_chat_skills_md, read_versions_skill_md
from onyx.skills.ingest import delete_bundle_blob, ingest_skill_bundle
from onyx.skills.push import build_chat_built_ins_bundle
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_external_app,
    make_group,
    make_skill,
    make_user,
    set_current_version_validity,
    share_plugin_with_group,
)


def _bundle(name: str, version: str, short_description: str | None = None) -> bytes:
    metadata = (
        f"metadata:\n  short-description: {short_description}\n"
        if short_description
        else ""
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: Skill {version}\n{metadata}---\n\n"
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
    set_skill_installation_policy(skill, PluginInstallationPolicy.DEFAULT, db_session)
    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None
    first_version_id: UUID = plugin.current_version_id
    second = ingest_skill_bundle(
        _bundle(name, "two", short_description="Short two"),
        f"{name}.zip",
        file_store,
        expected_name=name,
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
        skill.name: skill
        for skill in list_chat_skills(db_session, author, built_ins=False)
    }
    org_skills = {
        skill.name: skill
        for skill in list_chat_skills(db_session, org_only, built_ins=False)
    }

    # Each skill has its version's description and short description.
    assert (
        author_skills[name].description,
        author_skills[name].short_description,
    ) == ("Skill two", "Short two")
    assert (
        org_skills[name].description,
        org_skills[name].short_description,
    ) == ("Skill one", None)
    # The whole SKILL.md of each version, frontmatter included.
    skill_md = read_versions_skill_md(
        [(author_skills[name].version_id, ""), (org_skills[name].version_id, "")],
        author.id,
        db_session,
    )
    for version_id, version in (
        (author_skills[name].version_id, "two"),
        (org_skills[name].version_id, "one"),
    ):
        text = skill_md[(version_id, "")]
        assert text.startswith(f"---\nname: {name}\n")
        assert f"description: Skill {version}" in text
        assert text.rstrip().endswith(f"Instructions {version}")
    built_in_names = {
        runtime.name
        for runtime in list_runtime_skills_for_user(db_session=db_session, user=author)
        if runtime.built_in_skill_id is not None
    }
    assert built_in_names
    assert not built_in_names & set(author_skills)


def test_chat_skills_keep_app_skills_and_leave_out_invalid_skills(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User],
) -> None:
    user, _ = users
    # The app's plugin holds the skill; the user has not connected the app.
    app_skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=app_skill, auth_template={"token": "{token}"})
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
    chat_names = {
        skill.name for skill in list_chat_skills(db_session, user, built_ins=False)
    }

    assert {app_skill.name, valid_skill.name} <= runtime_names
    assert invalid_skill.name not in runtime_names
    assert {app_skill.name, valid_skill.name} <= chat_names
    assert invalid_skill.name not in chat_names


def test_chat_skills_follow_install_settings_and_the_name_order(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User],
) -> None:
    """Chat gets the custom skills the sandbox loads: a group's Not available
    hides a skill and its SKILL.md, Required turns a skill on, and one skill
    keeps each name."""
    user, other = users
    group = make_group(db_session)
    add_user_to_group(db_session, user, group)
    hidden = make_skill(db_session, is_public=True)
    required = make_skill(db_session, is_public=True)
    name = f"chat-order-{uuid4().hex[:8]}"
    published = make_skill(db_session, name=name, is_public=True)
    own = make_skill(db_session, name=name, author_user_id=user.id)
    for skill in (hidden, required, published, own):
        set_current_version_validity(db_session, skill.id, True)
    for skill, policy in (
        (hidden, PluginInstallationPolicy.DEFAULT),
        (published, PluginInstallationPolicy.DEFAULT),
        (required, None),
    ):
        set_skill_installation_policy(skill, policy, db_session)
    share_plugin_with_group(
        db_session, hidden.id, group.id, None, PluginInstallationPolicy.NOT_AVAILABLE
    )
    share_plugin_with_group(
        db_session, required.id, group.id, None, PluginInstallationPolicy.REQUIRED
    )
    set_plugin_preferences__no_commit(user.id, [own.id], True, db_session)
    db_session.commit()

    chat = {
        skill.name: skill
        for skill in list_chat_skills(db_session, user, built_ins=False)
    }
    runtime = {
        runtime.name: runtime.version.id
        for runtime in list_runtime_skills_for_user(db_session=db_session, user=user)
        if runtime.version is not None
    }

    assert hidden.name not in chat
    assert required.name in chat
    assert hidden.name in {
        skill.name for skill in list_chat_skills(db_session, other, built_ins=False)
    }
    assert required.name not in {
        skill.name for skill in list_chat_skills(db_session, other, built_ins=False)
    }
    # One skill keeps the name: the published one beats the user's own, as in
    # the sandbox.
    assert [
        skill.name for skill in list_chat_skills(db_session, user, built_ins=False)
    ].count(name) == 1
    assert {skill.name: skill.version_id for skill in chat.values()} == runtime
    published_plugin = db_session.get(Plugin, published.id)
    hidden_plugin = db_session.get(Plugin, hidden.id)
    assert published_plugin is not None and hidden_plugin is not None
    assert chat[name].version_id == published_plugin.current_version_id
    # A picked skill's SKILL.md is read only for a skill the user can see.
    assert not get_visible_versions_skill_md(
        [(hidden_plugin.current_version_id, "")], user.id, db_session
    )
    assert get_visible_versions_skill_md(
        [(hidden_plugin.current_version_id, "")], other.id, db_session
    )


def test_chat_built_ins_need_the_sandbox_and_name_their_vm_folder(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User],
) -> None:
    user, _ = users
    assert not any(
        skill.built_in_skill_id
        for skill in list_chat_skills(db_session, user, built_ins=False)
    )

    built_ins = {
        skill.name: skill
        for skill in list_chat_skills(db_session, user, built_ins=True)
        if skill.built_in_skill_id is not None
    }
    assert "pptx" in built_ins
    assert {skill.built_in_skill_id for skill in built_ins.values()} <= (
        CHAT_BUILT_IN_SKILL_IDS
    )

    pptx = built_ins["pptx"]
    skill_md = read_chat_skills_md([pptx], user.id, db_session)[
        (pptx.version_id, pptx.path)
    ]
    assert skill_md.startswith("Skill files: /mnt/skills/pptx/")
    assert "python /mnt/skills/pptx/scripts/lint.py" in skill_md

    # Each mounted folder is a listed skill; the bundle is built once.
    bundle = build_chat_built_ins_bundle(db_session)
    assert bundle is not None
    assert build_chat_built_ins_bundle(db_session) is bundle
    with zipfile.ZipFile(io.BytesIO(bundle.zip_bytes)) as zf:
        folders = {name.split("/", 1)[0] for name in zf.namelist()}
    assert folders == set(built_ins)
