import contextvars
import io
import json
import threading
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.models import (
    Integration__User,
    Integration__UserGroup,
    Plugin,
    PluginVersion,
    User,
    UserGroup,
    UserIntegrationPreference,
)
from onyx.db.plugin import (
    PluginAccessChange,
    PluginUserGrant,
    apply_plugin_access_change__no_commit,
)
from onyx.db.skill import list_chat_skills, list_runtime_skills_for_user
from onyx.db.users import delete_user_from_db__no_commit
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.integrations.models import PluginNeedState
from onyx.integrations.service import list_member_integrations
from onyx.server.features.skill import api
from onyx.server.features.skill.models import (
    SkillBulkActionRequest,
    SkillEnableRequest,
    SkillVersionRestoreRequest,
)
from onyx.server.features.skill.response_helpers import skill_response_for_user
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.push import (
    build_chat_custom_skill_files,
    build_user_skills_payload,
)
from onyx.tools.tool_implementations.skills.skill_tools import (
    SkillsListTool,
    skills_catalog_message,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.craft.db_helpers import make_group, make_user
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
)

MCP_URL = "https://mcp.plugin-upload.test/mcp"


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: The {name} skill.\n---\n\nSteps.\n"


def _plugin_zip(
    name: str,
    skills: list[str],
    *,
    servers: dict[str, object] | None = None,
    version: str = "1.0.0",
    description: str = "Kit.",
) -> UploadFile:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            f"{name}/.claude-plugin/plugin.json",
            json.dumps({"name": name, "version": version, "description": description}),
        )
        for skill in skills:
            bundle_zip.writestr(f"{name}/skills/{skill}/SKILL.md", _skill_md(skill))
            bundle_zip.writestr(f"{name}/skills/{skill}/notes.md", f"{skill} notes")
        if servers is not None:
            bundle_zip.writestr(
                f"{name}/.mcp.json", json.dumps({"mcpServers": servers})
            )
    return UploadFile(file=io.BytesIO(output.getvalue()), filename=f"{name}.zip")


def _http(url: str = MCP_URL) -> dict[str, str]:
    return {"type": "http", "url": url}


@pytest.fixture(scope="module")
def created_user_ids() -> Iterator[list[UUID]]:
    """Users go after the last test, once the skill table restore removed the
    plugins of their "My uploads"."""
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
def users(db_session: Session, created_user_ids: list[UUID]) -> tuple[User, User, User]:
    made = tuple(make_user(db_session, standard_account=True) for _ in range(3))
    db_session.commit()
    created_user_ids.extend(user.id for user in made)
    return made[0], made[1], made[2]


@pytest.fixture
def integration_ids(db_session: Session) -> Iterator[list[int]]:
    ids: list[int] = []
    yield ids
    delete_integrations(db_session, ids)


@pytest.fixture(autouse=True)
def bundle_cleanup(
    db_session: Session, users: tuple[User, User, User]
) -> Iterator[None]:
    yield
    db_session.rollback()
    file_store = get_default_file_store()
    for file_id in db_session.scalars(
        select(PluginVersion.bundle_file_id).where(
            PluginVersion.created_by_user_id.in_([user.id for user in users])
        )
    ):
        if file_id is not None:
            delete_bundle_blob(file_store, file_id)


@pytest.fixture(autouse=True)
def no_craft_reload() -> Iterator[None]:
    with patch("onyx.server.features.skill.api.reload_craft_sessions"):
        yield


def _save(
    user: User, upload: UploadFile, db_session: Session, *, save_as_new: bool = False
) -> api.PluginUploadResponse:
    return api.save_plugin_upload(
        bundle=upload,
        save_as_new=save_as_new,
        auto_enable=True,
        user=user,
        db_session=db_session,
    )


def _need_states(
    user: User, plugin_id: UUID, db_session: Session
) -> list[tuple[str, PluginNeedState, int | None]]:
    detail = api.fetch_skill_for_current_user(plugin_id, user, db_session).plugin
    assert detail is not None
    return [(need.name, need.state, need.integration_id) for need in detail.needs]


def test_three_skills_load_as_three_run_time_and_chat_skills(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, _ = users
    saved = _save(
        author, _plugin_zip("trio-kit", ["alpha", "beta", "gamma"]), db_session
    )

    assert (saved.target.kind, saved.target.version_number, saved.enabled) == (
        "new_plugin",
        1,
        True,
    )
    assert (saved.plugin.kind, saved.plugin.name) == ("plugin", "trio-kit")
    assert saved.plugin.plugin is not None
    assert [(skill.path, skill.name) for skill in saved.plugin.plugin.skills] == [
        ("skills/alpha", "alpha"),
        ("skills/beta", "beta"),
        ("skills/gamma", "gamma"),
    ]

    runtime = [
        skill
        for skill in list_runtime_skills_for_user(db_session=db_session, user=author)
        if skill.id == saved.plugin.id
    ]
    assert [
        (folder.path, folder.name)
        for skill in runtime
        for folder in skill.plugin_skills
    ] == [
        ("skills/alpha", "alpha"),
        ("skills/beta", "beta"),
        ("skills/gamma", "gamma"),
    ]
    chat = [
        (skill.name, skill.path)
        for skill in list_chat_skills(db_session, author, built_ins=False)
        if skill.name in {"alpha", "beta", "gamma"}
    ]
    assert chat == [
        ("alpha", "skills/alpha"),
        ("beta", "skills/beta"),
        ("gamma", "skills/gamma"),
    ]
    files = build_user_skills_payload(author, db_session).files
    assert sorted(
        path for path in files if path.split("/")[0] in {"alpha", "beta", "gamma"}
    ) == [
        "alpha/SKILL.md",
        "alpha/notes.md",
        "beta/SKILL.md",
        "beta/notes.md",
        "gamma/SKILL.md",
        "gamma/notes.md",
    ]
    assert files["beta/notes.md"] == b"beta notes"
    assert not any(path.startswith((".claude-plugin", "skills/")) for path in files)

    beta = next(
        skill
        for skill in list_chat_skills(db_session, author, built_ins=True)
        if skill.name == "beta"
    )
    copied = build_chat_custom_skill_files(beta, author, db_session)
    assert copied is not None
    assert sorted(copied) == ["beta/SKILL.md", "beta/notes.md"]


def test_same_name_adds_a_version_and_a_non_editor_gets_a_new_plugin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, editor, viewer = users
    first = _save(author, _plugin_zip("same-kit", ["one"]), db_session)
    plugin_id = first.plugin.id
    apply_plugin_access_change__no_commit(
        [plugin_id],
        PluginAccessChange(
            user_grants=(
                PluginUserGrant(
                    user_id=editor.id, permission=SkillSharePermission.EDITOR
                ),
                PluginUserGrant(
                    user_id=viewer.id, permission=SkillSharePermission.VIEWER
                ),
            )
        ),
        None,
        db_session,
    ).raise_first_failure()
    db_session.commit()

    preview = api.inspect_plugin_upload(
        bundle=_plugin_zip("same-kit", ["one", "two"], version="2.0.0"),
        save_as_new=False,
        user=author,
        db_session=db_session,
    )
    assert preview.target.model_dump() == {
        "kind": "new_version",
        "plugin_id": plugin_id,
        "plugin_name": "same-kit",
        "version_number": 2,
    }
    second = _save(author, _plugin_zip("same-kit", ["one", "two"]), db_session)

    assert (second.target.kind, second.target.version_number) == ("new_version", 2)
    assert second.plugin.id == plugin_id
    assert {
        (share.user.id, share.permission) for share in second.plugin.user_shares
    } == {
        (editor.id, SkillSharePermission.EDITOR),
        (viewer.id, SkillSharePermission.VIEWER),
    }
    assert second.plugin.enabled is True

    copy = _save(author, _plugin_zip("same-kit", ["one"]), db_session, save_as_new=True)
    assert (copy.target.kind, copy.plugin.name) == ("new_plugin", "same-kit-2")

    apply_plugin_access_change__no_commit(
        [plugin_id], PluginAccessChange(publish=True), None, db_session
    ).raise_first_failure()
    db_session.commit()
    published_version_id = db_session.get_one(Plugin, plugin_id).published_version_id
    editor_save = _save(editor, _plugin_zip("same-kit", ["one", "three"]), db_session)
    assert (editor_save.target.kind, editor_save.target.version_number) == (
        "new_version",
        3,
    )
    assert editor_save.plugin.id == plugin_id
    db_session.expire_all()
    assert db_session.get_one(Plugin, plugin_id).published_version_id == (
        published_version_id
    )

    viewer_save = _save(viewer, _plugin_zip("same-kit", ["one"]), db_session)
    assert (viewer_save.target.kind, viewer_save.target.plugin_name) == (
        "new_plugin",
        "same-kit",
    )
    assert viewer_save.plugin.id != plugin_id

    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count()).where(PluginVersion.plugin_id == plugin_id)
        )
        == 3
    )


def test_an_invalid_zip_gives_the_reason_and_saves_nothing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, _ = users
    upload = _plugin_zip("empty-kit", [])

    with pytest.raises(OnyxError) as error:
        _save(author, upload, db_session)

    assert error.value.detail == (
        "This plugin has no skill and no MCP server. Onyx uses only skills in "
        "skills/<name>/SKILL.md and MCP servers in .mcp.json or plugin.json."
    )
    db_session.rollback()
    assert (
        db_session.scalar(
            select(func.count()).where(Plugin.author_user_id == author.id)
        )
        == 0
    )


def test_need_states_match_integrations_by_url_and_give_no_access(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
    integration_ids: list[int],
) -> None:
    author, owner, _ = users
    available, _ = make_mcp_integration(
        db_session, server_url="HTTPS://MCP.Plugin-Upload.test:443/mcp/"
    )
    give_access(db_session, [available])
    twin_a, _ = make_mcp_integration(db_session, server_url="https://twin.test/mcp")
    twin_b, _ = make_mcp_integration(db_session, server_url="https://twin.test/mcp/")
    give_access(db_session, [twin_a, twin_b])
    private, _ = make_mcp_integration(db_session, server_url="https://private.test/mcp")
    give_access(db_session, [private], published=False, owner_user_id=owner.id)
    gone, _ = make_mcp_integration(db_session, server_url="https://gone.test/mcp")
    give_access(db_session, [gone])
    integration_ids.extend([available.id, twin_a.id, twin_b.id, private.id, gone.id])
    available_id, gone_id = available.id, gone.id

    saved = _save(
        author,
        _plugin_zip(
            "needs-kit",
            ["helper"],
            servers={
                "main": _http(),
                "twins": _http("https://twin.test/mcp"),
                "private": _http("https://private.test/mcp"),
                "gone": _http("https://gone.test/mcp"),
                "local": {"command": "npx", "args": ["server"]},
            },
        ),
        db_session,
    )
    plugin_id = saved.plugin.id
    assert _need_states(author, plugin_id, db_session) == [
        ("gone", PluginNeedState.ON, gone_id),
        ("local", PluginNeedState.NOT_SUPPORTED, None),
        ("main", PluginNeedState.ON, available_id),
        ("private", PluginNeedState.NOT_ADDED, None),
        ("twins", PluginNeedState.MORE_THAN_ONE, None),
    ]
    assert (saved.plugin.available_count, saved.plugin.needed_count) == (2, 4)
    assert not db_session.scalars(
        select(Integration__User).where(Integration__User.user_id == author.id)
    ).all()

    delete_integrations(db_session, [gone_id])
    integration_ids.remove(gone_id)
    assert _need_states(author, plugin_id, db_session)[0] == (
        "gone",
        PluginNeedState.NOT_ADDED,
        None,
    )


def test_turning_a_plugin_on_turns_on_its_integrations(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
    integration_ids: list[int],
) -> None:
    author, _, _ = users
    integration, _ = make_mcp_integration(db_session, server_url=MCP_URL)
    give_access(db_session, [integration])
    integration_ids.append(integration.id)
    integration_id = integration.id
    saved = _save(
        author,
        _plugin_zip("switch-kit", ["switcher"], servers={"main": _http()}),
        db_session,
    )
    plugin_id = saved.plugin.id
    api.set_skill_enabled_for_current_user(
        plugin_id, SkillEnableRequest(enabled=False), author, db_session
    )
    db_session.execute(
        delete(UserIntegrationPreference).where(
            UserIntegrationPreference.user_id == author.id
        )
    )
    db_session.commit()
    off = api.fetch_skill_for_current_user(plugin_id, author, db_session)
    assert (off.enabled, off.available_count, off.needed_count) == (False, 0, 1)

    on = api.set_skill_enabled_for_current_user(
        plugin_id, SkillEnableRequest(enabled=True), author, db_session
    )

    assert on.plugin is not None
    assert [(need.name, need.state) for need in on.plugin.needs] == [
        ("main", PluginNeedState.ON)
    ]
    assert (on.enabled, on.available_count, on.needed_count) == (True, 1, 1)
    listed = {
        skill.id: skill
        for skill in api.list_skills_for_current_user(author, db_session).customs
    }
    assert (
        listed[plugin_id].kind,
        listed[plugin_id].available_count,
        listed[plugin_id].needed_count,
        listed[plugin_id].plugin,
    ) == ("plugin", 1, 1, None)
    assert db_session.scalar(
        select(UserIntegrationPreference.enabled).where(
            UserIntegrationPreference.user_id == author.id,
            UserIntegrationPreference.integration_id == integration_id,
        )
    )


def test_chat_names_the_integrations_a_loaded_plugin_cannot_use(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, _ = users
    _save(
        author,
        _plugin_zip("missing-kit", ["missing"], servers={"tracker": _http()}),
        db_session,
    )

    message = skills_catalog_message([SkillsListTool(author, built_ins=False)], 200_000)

    assert message is not None
    assert message.content.endswith(
        "\nSome skills come from plugins that need integrations the user cannot "
        "use now: tracker. If a step needs one, tell the user to add it, turn it "
        "on or sign in under Customize > Integrations."
    )


def test_org_viewers_see_the_published_description_not_a_draft(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, viewer = users
    plugin_id = _save(
        author, _plugin_zip("draft-kit", ["drafted"]), db_session
    ).plugin.id
    apply_plugin_access_change__no_commit(
        [plugin_id], PluginAccessChange(publish=True), None, db_session
    ).raise_first_failure()
    db_session.commit()

    _save(
        author,
        _plugin_zip("draft-kit", ["drafted"], description="Draft."),
        db_session,
    )

    def description(user: User) -> str:
        listed = {
            skill.id: skill.description
            for skill in api.list_skills_for_current_user(user, db_session).customs
        }
        fetched = api.fetch_skill_for_current_user(plugin_id, user, db_session)
        assert listed[plugin_id] == fetched.description
        return fetched.description

    assert description(viewer) == "Kit."
    assert description(author) == "Draft."


def test_plugin_versions_preview_and_restore(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, _ = users
    first = _save(
        author,
        _plugin_zip("restore-kit", ["kept"], servers={"main": _http()}),
        db_session,
    )
    plugin_id = first.plugin.id
    _save(
        author,
        _plugin_zip("restore-kit", ["kept", "added"], description="Two."),
        db_session,
    )
    versions = api.list_custom_skill_versions(plugin_id, author, db_session)
    second_id, first_id = versions[0].id, versions[1].id

    preview = api.preview_custom_skill_version(plugin_id, first_id, author, db_session)

    assert (preview.description, preview.instructions_markdown) == ("Kit.", "")
    assert preview.plugin is not None
    assert [skill.name for skill in preview.plugin.skills] == ["kept"]
    assert [(need.name, need.state) for need in preview.plugin.needs] == [
        ("main", PluginNeedState.NOT_ADDED)
    ]
    assert [file.path for file in preview.files] == [
        ".claude-plugin/plugin.json",
        ".mcp.json",
        "skills/kept/SKILL.md",
        "skills/kept/notes.md",
    ]

    restored = api.restore_custom_skill_version(
        plugin_id,
        first_id,
        SkillVersionRestoreRequest(base_version_id=second_id),
        author,
        db_session,
    )

    assert restored.current_version_id is not None
    assert restored.current_version_number == 3
    assert restored.description == "Kit."
    assert restored.plugin is not None
    assert [skill.name for skill in restored.plugin.skills] == ["kept"]
    again = api.restore_custom_skill_version(
        plugin_id,
        first_id,
        SkillVersionRestoreRequest(base_version_id=restored.current_version_id),
        author,
        db_session,
    )
    assert again.current_version_id == restored.current_version_id
    with pytest.raises(OnyxError):
        api.restore_custom_skill_version(
            plugin_id,
            first_id,
            SkillVersionRestoreRequest(base_version_id=second_id),
            author,
            db_session,
        )


def test_a_shown_version_gives_the_detail_and_counts_of_that_version(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, _ = users
    first = _save(
        author,
        _plugin_zip("shown-kit", ["kept"], servers={"main": _http()}),
        db_session,
    )
    _save(author, _plugin_zip("shown-kit", ["kept", "added"]), db_session)
    plugin = db_session.get_one(Plugin, first.plugin.id)
    versions = api.list_custom_skill_versions(plugin.id, author, db_session)
    assert [version.manifest_version for version in versions] == ["1.0.0", "1.0.0"]
    first_id = versions[1].id

    shown = skill_response_for_user(
        plugin,
        author,
        db_session,
        shown_version_id=first_id,
        include_plugin_detail=True,
    )

    assert shown.current_version_id == first_id
    assert shown.plugin is not None
    assert [skill.name for skill in shown.plugin.skills] == ["kept"]
    assert [need.name for need in shown.plugin.needs] == ["main"]
    assert shown.needed_count == 1
    current = skill_response_for_user(
        plugin, author, db_session, include_plugin_detail=True
    )
    assert current.plugin is not None
    assert [skill.name for skill in current.plugin.skills] == ["added", "kept"]
    assert current.needed_count == 0


def test_a_failed_push_state_commit_keeps_the_saved_version(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author, _, _ = users
    real_commit = db_session.commit

    def fail_the_next_commit(*_args: object) -> None:
        def failing_commit() -> None:
            monkeypatch.setattr(db_session, "commit", real_commit)
            raise RuntimeError("connection lost")

        monkeypatch.setattr(db_session, "commit", failing_commit)

    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", fail_the_next_commit)

    first = _save(author, _plugin_zip("commit-kit", ["one"]), db_session)
    second = _save(author, _plugin_zip("commit-kit", ["one", "two"]), db_session)
    versions = api.list_custom_skill_versions(first.plugin.id, author, db_session)
    restored = api.restore_custom_skill_version(
        first.plugin.id,
        versions[1].id,
        SkillVersionRestoreRequest(base_version_id=versions[0].id),
        author,
        db_session,
    )

    assert second.target.version_number == 2
    assert restored.current_version_number == 3


def test_bulk_enable_turns_on_the_integrations_of_a_plugin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
    integration_ids: list[int],
) -> None:
    author, _, _ = users
    integration, _ = make_mcp_integration(db_session, server_url=MCP_URL)
    give_access(db_session, [integration])
    integration_ids.append(integration.id)
    plugin_id = _save(
        author,
        _plugin_zip("bulk-kit", ["bulked"], servers={"main": _http()}),
        db_session,
    ).plugin.id
    api.bulk_update_skills(
        SkillBulkActionRequest(skill_ids=[plugin_id], action="disable"),
        author,
        db_session,
    )
    db_session.execute(
        delete(UserIntegrationPreference).where(
            UserIntegrationPreference.user_id == author.id
        )
    )
    db_session.commit()

    with patch("onyx.server.features.skill.api.reload_craft_sessions") as reload:
        result = api.bulk_update_skills(
            SkillBulkActionRequest(skill_ids=[plugin_id], action="enable"),
            author,
            db_session,
        )

    assert (result.succeeded, result.failed) == ([plugin_id], [])
    on = api.fetch_skill_for_current_user(plugin_id, author, db_session)
    assert (on.enabled, on.available_count, on.needed_count) == (True, 1, 1)
    reload.assert_called_once_with({author.id}, db_session)


def test_a_group_limited_integration_is_no_access_without_its_url(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
    integration_ids: list[int],
) -> None:
    author, _, _ = users
    limited_url = "https://limited.plugin-upload.test/mcp"
    integration, _ = make_mcp_integration(db_session, server_url=limited_url)
    integration_ids.append(integration.id)
    integration_id = integration.id
    group = make_group(db_session)
    group_id = group.id
    integration.installation_policy = PluginInstallationPolicy.NOT_AVAILABLE
    db_session.add(
        Integration__UserGroup(
            integration_id=integration_id,
            user_group_id=group_id,
            installation_policy=PluginInstallationPolicy.AVAILABLE,
        )
    )
    db_session.commit()
    try:
        plugin_id = _save(
            author,
            _plugin_zip(
                "limited-kit", ["limited"], servers={"main": _http(limited_url)}
            ),
            db_session,
        ).plugin.id

        assert _need_states(author, plugin_id, db_session) == [
            ("main", PluginNeedState.NO_ACCESS, integration_id)
        ]
        rows = {row.id: row for row in list_member_integrations(author, db_session)}
        assert rows[integration_id].server_url is None
    finally:
        db_session.rollback()
        db_session.execute(
            delete(Integration__UserGroup).where(
                Integration__UserGroup.user_group_id == group_id
            )
        )
        db_session.execute(delete(UserGroup).where(UserGroup.id == group_id))
        db_session.commit()


def test_an_editor_share_uploads_a_new_version_of_the_shared_plugin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, editor, _ = users
    plugin_id = _save(author, _plugin_zip("shared-kit", ["one"]), db_session).plugin.id
    apply_plugin_access_change__no_commit(
        [plugin_id],
        PluginAccessChange(
            user_grants=(
                PluginUserGrant(
                    user_id=editor.id, permission=SkillSharePermission.EDITOR
                ),
            )
        ),
        None,
        db_session,
    ).raise_first_failure()
    db_session.commit()

    saved = _save(editor, _plugin_zip("shared-kit", ["one", "two"]), db_session)

    assert (saved.plugin.id, saved.target.kind, saved.target.version_number) == (
        plugin_id,
        "new_version",
        2,
    )


def test_an_unchanged_upload_adds_no_version(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, _ = users
    first = _save(author, _plugin_zip("same-files", ["one"]), db_session)
    again = _save(author, _plugin_zip("same-files", ["one"]), db_session)

    assert first.unchanged is False
    assert (again.unchanged, again.target.kind, again.target.version_number) == (
        True,
        "new_version",
        1,
    )
    assert again.plugin.id == first.plugin.id
    assert (
        db_session.scalar(
            select(func.count()).where(PluginVersion.plugin_id == first.plugin.id)
        )
        == 1
    )


def test_uploads_of_one_new_name_at_the_same_time_make_one_plugin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, _ = users
    uploads = 6
    start = threading.Barrier(uploads)

    def save(index: int) -> UUID:
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            user = session.get_one(User, author.id)
            start.wait()
            return _save(
                user,
                _plugin_zip("race-kit", ["one"], description=f"Kit {index}."),
                session,
            ).plugin.id

    with ThreadPoolExecutor(max_workers=uploads) as pool:
        plugin_ids = list(
            pool.map(
                lambda index: contextvars.copy_context().run(save, index),
                range(uploads),
            )
        )

    assert len(set(plugin_ids)) == 1
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count()).where(PluginVersion.plugin_id == plugin_ids[0])
        )
        == uploads
    )


def test_an_admin_list_marks_a_members_private_plugin_not_member_visible(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
    created_user_ids: list[UUID],
) -> None:
    author, _, _ = users
    admin = make_user(db_session, is_admin=True)
    db_session.commit()
    created_user_ids.append(admin.id)
    private = _save(author, _plugin_zip("private-kit", ["one"]), db_session)
    own = _save(admin, _plugin_zip("admin-kit", ["two"]), db_session)

    listed = {
        skill.id: skill.member_visible
        for skill in api.list_skills_for_current_user(admin, db_session).customs
    }

    assert (listed[private.plugin.id], listed[own.plugin.id]) == (False, True)


def test_a_viewer_reads_the_instructions_of_one_skill_in_a_plugin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, viewer, outsider = users
    saved = _save(author, _plugin_zip("read-kit", ["one", "two"]), db_session)
    apply_plugin_access_change__no_commit(
        [saved.plugin.id],
        PluginAccessChange(
            user_grants=(
                PluginUserGrant(
                    user_id=viewer.id, permission=SkillSharePermission.VIEWER
                ),
            )
        ),
        None,
        db_session,
    ).raise_first_failure()
    db_session.commit()

    read = api.read_plugin_skill_for_current_user(
        saved.plugin.id, "skills/two", viewer, db_session
    )

    assert read.instructions_markdown.strip() == "Steps."
    with pytest.raises(OnyxError):
        api.read_plugin_skill_for_current_user(
            saved.plugin.id, "skills/two", outsider, db_session
        )


def test_a_skill_name_clash_is_shown_before_and_after_the_save(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    author, _, _ = users
    _save(author, _plugin_zip("first-kit", ["clash"]), db_session)

    preview = api.inspect_plugin_upload(
        bundle=_plugin_zip("second-kit", ["clash", "other"]),
        save_as_new=False,
        user=author,
        db_session=db_session,
    )
    saved = _save(author, _plugin_zip("second-kit", ["clash", "other"]), db_session)

    assert (preview.will_enable, preview.name_conflicts) == (False, ["first-kit"])
    assert (saved.enabled, saved.name_conflicts) == (False, ["first-kit"])


def test_a_plugin_that_loses_its_skill_name_says_which_plugin_holds_it(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
) -> None:
    member, publisher, _ = users
    own = _save(member, _plugin_zip("own-kit", ["shared-name"]), db_session)
    company = _save(publisher, _plugin_zip("company-kit", ["shared-name"]), db_session)
    apply_plugin_access_change__no_commit(
        [company.plugin.id],
        PluginAccessChange(
            publish=True,
            company_installation_policy=PluginInstallationPolicy.DEFAULT,
        ),
        None,
        db_session,
    ).raise_first_failure()
    db_session.commit()

    listed = {
        skill.id: (skill.enabled, skill.name_held_by)
        for skill in api.list_skills_for_current_user(member, db_session).customs
    }

    assert own.enabled is True
    assert listed[own.plugin.id] == (False, ["company-kit"])
    assert listed[company.plugin.id] == (True, [])


def test_a_new_version_of_an_enabled_plugin_turns_on_its_new_integrations(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    users: tuple[User, User, User],
    integration_ids: list[int],
) -> None:
    author, _, _ = users
    integration, _ = make_mcp_integration(db_session, server_url=MCP_URL)
    give_access(db_session, [integration])
    integration_ids.append(integration.id)
    integration_id = integration.id
    plugin_id = _save(author, _plugin_zip("grow-kit", ["one"]), db_session).plugin.id

    preview = api.inspect_plugin_upload(
        bundle=_plugin_zip("grow-kit", ["one"], servers={"main": _http()}),
        save_as_new=False,
        user=author,
        db_session=db_session,
    )
    saved = _save(
        author, _plugin_zip("grow-kit", ["one"], servers={"main": _http()}), db_session
    )

    assert preview.will_enable is True
    assert saved.enabled is True
    assert _need_states(author, plugin_id, db_session) == [
        ("main", PluginNeedState.ON, integration_id)
    ]
