"""Main chat Skill delivery with real PostgreSQL authority and bundle storage."""

import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from onyx.agents.models import ExecutionCheckpoint, RunProgress, RunState, RunStatus
from onyx.agents.tools import ToolInvocation
from onyx.cache.factory import get_cache_backend
from onyx.chat.agent import ChatAgent
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.execution import create_chat_agent
from onyx.chat.models import (
    AvailableFiles,
    ChatTurnSetup,
    PersonaPromptConfig,
    ReservedChatResponse,
    SearchParams,
)
from onyx.chat.restoration import restore_chat_agent
from onyx.context.models import UserInfo, UserMemoryContext
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType, IndexModelStatus, Permission
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import (
    Base,
    Marketplace,
    Persona,
    SearchSettings,
    Skill,
    User,
    User__UserGroup,
)
from onyx.db.models import Tool as ToolRow
from onyx.db.resource_version import write_resource_version
from onyx.db.skill import set_skill_enabled_for_user
from onyx.db.skill_version import SkillVersionAdapter
from onyx.db.tools import capture_persona_tool_configuration
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.skills.bundle import build_skill_md
from onyx.skills.ingest import save_skill_bundle_bytes
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from onyx.tools.models import (
    PersonaToolConfiguration,
    SearchToolUsage,
    ToolConfiguration,
    ToolContext,
)
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_implementations.skills.skill_tool import (
    CATALOG_MAX_BYTES,
    MARKDOWN_MAX_BYTES,
    READ_ONLY_NOTICE,
    SkillTool,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_built_in_skill_row,
    make_external_app,
    make_group,
    make_skill,
    make_user,
    share_skill_with_group,
    share_skill_with_user,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


@pytest.fixture
def tool_row(session: Session) -> ToolRow:
    tables = {Base.metadata.tables["tool"], Base.metadata.tables["search_settings"]}
    while (
        dependencies := {
            fk.column.table for table in tables for fk in table.foreign_keys
        }
        - tables
    ):
        tables |= dependencies
    Base.metadata.create_all(session.connection(), tables=list(tables))
    row = ToolRow(
        name=SkillTool.NAME,
        display_name="Skills",
        in_code_tool_id="SkillTool",
        enabled=True,
    )
    session.add(row)
    session.add(
        SearchSettings(
            model_name="test",
            model_dim=8,
            normalize=True,
            status=IndexModelStatus.PRESENT,
            index_name="test",
        )
    )
    session.commit()
    return row


def saved_skill(
    session: Session,
    user: User,
    name: str = "report",
    body: str = "Follow the report workflow.",
    *,
    public: bool = False,
    files: dict[str, bytes] | None = None,
) -> Skill:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "SKILL.md",
            build_skill_md(
                name=name, description="Reports", instructions_markdown=body
            ),
        )
        for path, content in (files or {}).items():
            archive.writestr(path, content)
    file_id = save_skill_bundle_bytes(
        output.getvalue(), display_name="test.zip", file_store=get_default_file_store()
    )
    skill = make_skill(
        session,
        name=name,
        author_user_id=None if public else user.id,
        is_public=public,
        bundle_file_id=file_id,
        is_valid=True,
    )
    skill.installation_policy = Policy.DEFAULT
    session.commit()
    return skill


def call(
    tool: SkillTool,
    name: str | None = None,
    path: str | None = None,
    after: str | None = None,
) -> ToolResult:
    result = tool.run(
        ToolInvocation(
            call_id=str(uuid4()),
            arguments={"skill_name": name, "path": path, "after": after},
            cancellation=CancellationSignal(),
            update=lambda _: None,
        ),
        ToolContext(),
    )
    assert isinstance(result, ToolResult)
    return result


def configuration(row: ToolRow) -> PersonaToolConfiguration:
    return PersonaToolConfiguration(
        persona_id=0,
        persona_name="Default",
        tools=[ToolConfiguration.model_validate(row)],
        search=PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        ),
    )


def test_discover_read_support_and_current_version(
    session: Session, user: User, tool_row: ToolRow, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = saved_skill(
        session,
        user,
        files={
            "references/notes.md": b"Supporting evidence",
            "scripts/run.py": b"raise RuntimeError('never execute')",
        },
    )
    tool = SkillTool(tool_row.id, user.id)
    # All ZIP indexes on the read path must stay in memory.
    connect = sqlite3.connect

    def memory_only(database: str) -> sqlite3.Connection:
        assert database == ":memory:"
        return connect(database)

    monkeypatch.setattr("onyx.db.zip_metadata.sqlite3.connect", memory_only)
    listing = call(tool)
    assert json.loads(listing.text)["skills"] == [
        {"name": "report", "description": "d"}
    ]
    assert "Follow the report" not in listing.text
    assert call(tool, "report").text == READ_ONLY_NOTICE + "Follow the report workflow."
    assert call(tool, "report", "references/notes.md").text.endswith(
        "Supporting evidence"
    )
    replacement = saved_skill(session, user, "replacement", "New version")
    assert replacement.current_version is not None
    assert replacement.current_version.bundle_file_id is not None
    write_resource_version(
        SkillVersionAdapter(skill),
        bundle_file_id=replacement.current_version.bundle_file_id,
        bundle_sha256="1" * 64,
        is_valid=True,
        metadata=None,
        created_by_user_id=user.id,
        db_session=session,
    )
    session.commit()
    assert call(tool, "report").text.endswith("New version")


@pytest.mark.parametrize(
    "path",
    [
        "../SKILL.md",
        "/SKILL.md",
        "references/../SKILL.md",
        "references\\notes.md",
        "scripts/run.py",
        "missing.md",
        "./SKILL.md",
    ],
)
def test_support_paths_fail_closed(
    session: Session, user: User, tool_row: ToolRow, path: str
) -> None:
    saved_skill(session, user)
    assert call(SkillTool(tool_row.id, user.id), "report", path).is_error


@pytest.mark.parametrize(
    "change",
    [
        "private",
        "disabled",
        "retired",
        "invalid",
        "policy",
        "inactive",
        "permission",
        "tool_disabled",
    ],
)
def test_revocation_after_discovery_uses_fresh_authority(
    session: Session, user: User, tool_row: ToolRow, change: str
) -> None:
    other = make_user(session, standard_account=True)
    skill = saved_skill(session, other, public=True)
    tool = SkillTool(tool_row.id, user.id)
    assert "report" in call(tool).text
    with get_session_with_current_tenant() as update:
        current = update.get(Skill, skill.id)
        actor = update.get(User, user.id)
        configured = update.get(ToolRow, tool_row.id)
        assert current is not None and actor is not None and configured is not None
        if change == "private":
            current.public_permission = None
            current.author_user_id = other.id
        elif change == "disabled":
            set_skill_enabled_for_user(
                skill_id=skill.id, enabled=False, user=actor, db_session=update
            )
        elif change == "retired":
            current.retired_at = datetime.now(timezone.utc)
        elif change == "invalid":
            assert current.current_version is not None
            current.current_version.is_valid = False
        elif change == "policy":
            current.installation_policy = Policy.NOT_AVAILABLE
        elif change == "inactive":
            actor.is_active = False
        elif change == "permission":
            actor.effective_permissions = []
        else:
            configured.enabled = False
        update.commit()
    assert call(tool, "report").is_error
    assert "report" not in call(tool).text


@pytest.mark.parametrize("marketplace", [False, True])
def test_name_priority_and_retirement(
    session: Session, user: User, tool_row: ToolRow, marketplace: bool
) -> None:
    other = make_user(session, standard_account=True)
    shared = saved_skill(session, other, body="Shared")
    own = saved_skill(session, user, body="Personal")
    company = saved_skill(session, other, body="Company", public=True)
    share_skill_with_user(session, shared, user)
    if marketplace:
        for skill in (shared, own, company):
            source = Marketplace(
                name=str(uuid4()),
                provider=MarketplaceProvider.GITHUB,
                provider_config=GitHubMarketplaceConfig(
                    owner="acme", repo="skills", ref="main"
                ),
                owner_user_id=skill.author_user_id,
            )
            session.add(source)
            session.flush()
            skill.marketplace_id = source.id
            skill.marketplace_entry_key = skill.name
    session.commit()
    tool = SkillTool(tool_row.id, user.id)
    for skill, expected in (
        (company, "Company"),
        (own, "Personal"),
        (shared, "Shared"),
    ):
        assert call(tool, "report").text.endswith(expected)
        skill.retired_at = datetime.now(timezone.utc)
        session.commit()
    assert call(tool, "report").is_error


@pytest.mark.parametrize("limit", ["markdown", "metadata"])
def test_oversized_winner_is_not_replaced_and_app_readiness(
    session: Session, user: User, tool_row: ToolRow, limit: str
) -> None:
    own = saved_skill(session, user, body="Personal")
    company = saved_skill(
        session,
        user,
        body="Too big" * MARKDOWN_MAX_BYTES if limit == "markdown" else "Company",
        public=True,
        files={f"refs/{i:04d}-" + "a" * 220 + ".md": b"" for i in range(4000)}
        if limit == "metadata"
        else None,
    )
    tool = SkillTool(tool_row.id, user.id)
    result = call(tool, own.name)
    assert result.is_error
    assert ("context limit" if limit == "markdown" else "file list") in result.text
    assert "Personal" not in result.text
    assert company.current_version is not None
    assert company.current_version.bundle_file_id is not None
    get_default_file_store().delete_file(company.current_version.bundle_file_id)
    assert call(tool, own.name).text.endswith("Personal")
    company.retired_at = datetime.now(timezone.utc)
    make_external_app(session, skill=own, auth_template={}, enabled=False)
    session.commit()
    assert call(tool, own.name).is_error


def test_context_limits_and_no_eager_body(
    session: Session, user: User, tool_row: ToolRow
) -> None:
    for index in range(24):
        skill = saved_skill(
            session, user, f"report-{index:02}", "界" * MARKDOWN_MAX_BYTES
        )
        skill.description = "界" * 1000
    session.commit()
    tool = SkillTool(tool_row.id, user.id)
    names: list[str] = []
    after = None
    while True:
        result = call(tool, after=after)
        assert len(result.text.encode()) <= CATALOG_MAX_BYTES
        page = json.loads(result.text)
        names.extend(item["name"] for item in page["skills"])
        after = page["next_after"]
        if after is None:
            break
    assert names == [f"report-{index:02}" for index in range(24)]
    assert call(tool, names[0]).is_error


@pytest.mark.parametrize(
    "account", [AccountType.ANONYMOUS, AccountType.BOT, AccountType.EXT_PERM_USER]
)
def test_non_user_identities_cannot_read(
    session: Session, user: User, tool_row: ToolRow, account: AccountType
) -> None:
    saved_skill(session, user, public=True)
    tool = SkillTool(tool_row.id, user.id)
    user.account_type = account
    session.commit()
    assert call(tool).is_error
    assert call(tool, "report").is_error


def test_other_tenant_and_unshared_content_are_unavailable(
    session: Session, user: User, tool_row: ToolRow
) -> None:
    other = make_user(session, standard_account=True)
    saved_skill(session, other)
    tool = SkillTool(tool_row.id, user.id)
    assert call(tool, "report").is_error
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("another_tenant")
    try:
        assert call(tool).is_error
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_craft_builtins_excluded_and_tool_selection_preserved(
    session: Session, user: User, tool_row: ToolRow
) -> None:
    for name in ("pptx", "company-search", "craft-documentation"):
        row = make_built_in_skill_row(session, built_in_skill_id=name)
        row.installation_policy = Policy.DEFAULT
    session.commit()
    assert json.loads(call(SkillTool(tool_row.id, user.id)).text)["skills"] == []
    llm = FakeModelClient(lambda _request, _signal: AssistantMessage(content=[]))
    for allowed, expected in ((None, True), ([tool_row.id], True), ([], False)):
        tools = construct_tools(
            configuration(tool_row),
            user,
            llm,
            db_session=session,
            allowed_tool_ids=allowed,
        )
        assert (tool_row.id in tools) is expected
    tool_row.enabled = False
    session.commit()
    assert construct_tools(configuration(tool_row), user, llm, db_session=session) == {}


@pytest.mark.parametrize("code_mode", [False, True])
def test_new_and_restored_chat_agent_loads_only_current_skills(
    session: Session,
    user: User,
    tool_row: ToolRow,
    code_mode: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.chat.execution.CODE_MODE_ENABLED", code_mode)
    skill = saved_skill(session, user, body="PRIVATE_WORKFLOW_TOKEN")
    requests: list[GenerationRequest] = []
    expect_read = True

    def respond(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        results = [
            message
            for message in request.messages
            if isinstance(message, ToolResultMessage)
        ]
        if not results:
            assert "PRIVATE_WORKFLOW_TOKEN" not in str(request)
            assert any(tool.name == SkillTool.NAME for tool in request.tools or [])
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="discover",
                        name=SkillTool.NAME,
                        arguments={"skill_name": None, "path": None, "after": None},
                    )
                ]
            )
        if results[-1].tool_call_id == "discover":
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="read",
                        name=SkillTool.NAME,
                        arguments={"skill_name": "report", "path": None, "after": None},
                    )
                ]
            )
        assert results[-1].is_error is not expect_read
        assert ("PRIVATE_WORKFLOW_TOKEN" in results[-1].text) is expect_read
        return AssistantMessage(content=[TextContent(text="Finished")])

    llm = FakeModelClient(respond)
    cache = get_cache_backend()
    setup = ChatTurnSetup(
        new_msg_req=SendMessageRequest(message="Use report", chat_session_id=uuid4()),
        chat_session_id=uuid4(),
        chat_session_project_id=None,
        incognito_record_mode=None,
        persona_id=0,
        persona=PersonaPromptConfig(
            system_prompt=None,
            task_prompt=None,
            datetime_aware=False,
            replace_base_system_prompt=False,
        ),
        base_system_prompt="Follow authorized workflows.",
        tool_configuration=configuration(tool_row),
        research_tool_id=None,
        checkpoint=None,
        user_message_id=1,
        user_identity=LLMUserIdentity(user_id=str(user.id)),
        responses=[ReservedChatResponse(llm=llm, message_id=2, display_name="Test")],
        messages=[UserMessage(content="Use report")],
        input_messages=[UserMessage(content="Use report")],
        extracted_context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
        ),
        stream_id=1,
        reasoning_effort=ReasoningEffort.AUTO,
        search_params=SearchParams(
            project_id_filter=None,
            persona_id_filter=None,
            search_usage=SearchToolUsage.DISABLED,
        ),
        all_injected_file_metadata={},
        available_files=AvailableFiles(),
        preferred_tool_id=None,
        chat_files_for_tools=[],
        custom_agent_prompt=None,
        user_memory_context=UserMemoryContext(user_id=user.id, user_info=UserInfo()),
        skip_clarification=False,
        cache=cache,
        admission=ChatTurnAdmission(cache),
        slack_context=None,
        custom_tool_additional_headers=None,
        mcp_headers=None,
    )
    original = create_chat_agent(setup, user, 0, CancellationSignal(), False)
    assert isinstance(original, ChatAgent)
    checkpoint = ExecutionCheckpoint(
        agent_state=original.state,
        run_state=RunState(
            run_id="saved-run",
            agent_id=original.id,
            status=RunStatus.SUSPENDED,
            steps=[],
            progress=RunProgress(
                tool_configuration_digest="test",
                step_limit=4,
                feature_state=original.capture_state().model_dump(mode="json"),
            ),
        ),
    )
    checkpoint = ExecutionCheckpoint.model_validate_json(checkpoint.model_dump_json())
    assert "PRIVATE_WORKFLOW_TOKEN" not in checkpoint.model_dump_json()
    assert checkpoint.run_state.progress is not None
    assert "report" not in json.dumps(checkpoint.run_state.progress.feature_state)
    run_agent(original, max_steps=4)
    assert len(requests) == 3
    assert "PRIVATE_WORKFLOW_TOKEN" not in original.capture_state().model_dump_json()
    assert '"report"' not in original.capture_state().model_dump_json()
    # Restoration uses current tools and does not restore a catalog from feature state.
    for revoked in (False, True):
        if revoked:
            skill.retired_at = datetime.now(timezone.utc)
            session.commit()
            expect_read = False
        tools = construct_tools(configuration(tool_row), user, llm)
        restored = restore_chat_agent(
            checkpoint,
            llm=llm,
            tools=[tool for group in tools.values() for tool in group],
            user_identity=setup.user_identity,
        )
        assert isinstance(restored, ChatAgent)
        run_agent(restored, max_steps=4)
    assert len(requests) == 9
    # A current request that excludes the tool cannot recover it from the checkpoint.
    restored_without_tools = restore_chat_agent(
        checkpoint, llm=llm, tools=[], user_identity=setup.user_identity
    )
    assert isinstance(restored_without_tools, ChatAgent)
    assert restored_without_tools.configured_tools == []


def test_seed_migration_and_capture(session: Session, tool_row: ToolRow) -> None:
    tables = {
        Base.metadata.tables[name]
        for name in (
            "persona",
            "persona__tool",
            "persona__document_set",
            "persona__document",
            "persona__hierarchy_node",
        )
    }
    while (
        dependencies := {
            fk.column.table for table in tables for fk in table.foreign_keys
        }
        - tables
    ):
        tables |= dependencies
    Base.metadata.create_all(session.connection(), tables=list(tables))
    session.delete(tool_row)
    persona = Persona(id=0, name="Default", description="Default chat")
    session.add(persona)
    session.flush()
    migration = ScriptDirectory(
        str(Path(__file__).resolve().parents[3] / "alembic")
    ).get_revision("7b3f24d8a901")
    assert migration is not None
    session.execute(
        text("SELECT set_config('search_path', :schema, true)"),
        {"schema": CURRENT_TENANT_ID_CONTEXTVAR.get()},
    )
    with Operations.context(MigrationContext.configure(session.connection())):
        migration.module.upgrade()
        session.expire_all()
        captured = capture_persona_tool_configuration(persona)
        assert [tool.in_code_tool_id for tool in captured.tools] == ["SkillTool"]
        migration.module.downgrade()
        session.expire_all()
        assert capture_persona_tool_configuration(persona).tools == []
    session.commit()


def test_group_revocation_and_management_do_not_grant_runtime_access(
    session: Session, user: User, tool_row: ToolRow
) -> None:
    other = make_user(session, standard_account=True)
    skill = saved_skill(session, other)
    group = make_group(session)
    add_user_to_group(session, user, group)
    share_skill_with_group(session, skill, group)
    session.commit()
    tool = SkillTool(tool_row.id, user.id)
    assert call(tool, "report").text.endswith("Follow the report workflow.")
    with get_session_with_current_tenant() as change:
        change.execute(
            delete(User__UserGroup).where(
                User__UserGroup.user_id == user.id,
                User__UserGroup.user_group_id == group.id,
            )
        )
        actor = change.get(User, user.id)
        assert actor is not None
        actor.effective_permissions = [Permission.FULL_ADMIN_PANEL_ACCESS.value]
        change.commit()
    # Even global management authority is not runtime audience membership.
    assert call(tool, "report").is_error
    assert json.loads(call(tool).text)["skills"] == []


def test_support_limit_and_symlink_are_refused(
    session: Session, user: User, tool_row: ToolRow
) -> None:
    saved_skill(
        session,
        user,
        files={
            "long.md": b"x" * (MARKDOWN_MAX_BYTES + 1),
            "exact.md": b"x" * MARKDOWN_MAX_BYTES,
        },
    )
    tool = SkillTool(tool_row.id, user.id)
    assert call(tool, "report", "long.md").is_error
    assert (
        call(tool, "report", "exact.md").text
        == READ_ONLY_NOTICE + "x" * MARKDOWN_MAX_BYTES
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("SKILL.md", "Text")
        link = zipfile.ZipInfo("link.md")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "../../private.md")
    file_id = save_skill_bundle_bytes(
        output.getvalue(),
        display_name="unsafe.zip",
        file_store=get_default_file_store(),
    )
    unsafe = make_skill(
        session,
        name="unsafe",
        author_user_id=user.id,
        bundle_file_id=file_id,
        is_valid=True,
    )
    unsafe.installation_policy = Policy.DEFAULT
    session.commit()
    assert call(tool, "unsafe", "link.md").is_error
