"""Default Chat selection preserves disabled tools and enables legacy OpenAPI."""

from collections.abc import Callable, Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import Tool
from onyx.db.persona import (
    get_default_assistant,
    update_default_assistant_configuration,
)

ToolFactory = Callable[..., Tool]


@pytest.fixture
def make_tool(db_session: Session) -> Generator[ToolFactory, None, None]:
    """Build throwaway tools, and leave neither them nor their effect on the
    tenant-wide default assistant behind for the next test."""
    persona = get_default_assistant(db_session)
    assert persona is not None, "default assistant is seeded by migrations"
    original_tool_ids = [tool.id for tool in persona.tools]
    created_tool_ids: list[int] = []

    def _make_tool(*, enabled: bool, openapi: bool = False) -> Tool:
        tool = Tool(
            name=f"default-assistant-toggle-{uuid4().hex[:8]}",
            description="default assistant toggle test action",
            in_code_tool_id=None,
            openapi_schema={"openapi": "3.0.0"} if openapi else None,
            custom_headers=[],
            user_id=None,
            passthrough_auth=False,
            enabled=enabled,
        )
        db_session.add(tool)
        db_session.commit()
        db_session.refresh(tool)
        created_tool_ids.append(tool.id)
        return tool

    try:
        yield _make_tool
    finally:
        db_session.rollback()
        # Restore the tool list first: it drops the associations to the created
        # tools, which would otherwise block deleting them.
        persona = get_default_assistant(db_session)
        assert persona is not None
        persona.tools = (
            db_session.query(Tool).filter(Tool.id.in_(original_tool_ids)).all()
        )
        db_session.commit()

        db_session.query(Tool).filter(Tool.id.in_(created_tool_ids)).delete(
            synchronize_session=False
        )
        db_session.commit()


def test_toggle_succeeds_while_a_disabled_tool_is_attached(
    db_session: Session, make_tool: ToolFactory
) -> None:
    """The reported flow: an attached-but-disabled tool must not block a toggle."""
    disabled_tool = make_tool(enabled=False)
    attached_tool = make_tool(enabled=True)
    newly_toggled_tool = make_tool(enabled=True)

    update_default_assistant_configuration(
        db_session=db_session, tool_ids=[disabled_tool.id, attached_tool.id]
    )

    assert disabled_tool.enabled is False

    # Disabled non-OpenAPI tools remain in the default selection.
    persona = get_default_assistant(db_session)
    assert persona is not None
    assert disabled_tool.id in [tool.id for tool in persona.tools]

    # Toggling another tool on resends the whole list, disabled tool included.
    update_default_assistant_configuration(
        db_session=db_session,
        tool_ids=[disabled_tool.id, attached_tool.id, newly_toggled_tool.id],
    )

    persona = get_default_assistant(db_session)
    assert persona is not None
    assert {disabled_tool.id, attached_tool.id, newly_toggled_tool.id} <= {
        tool.id for tool in persona.tools
    }


def test_unknown_tool_id_is_still_rejected(
    db_session: Session,
    make_tool: ToolFactory,  # noqa: ARG001  # restores the default assistant
) -> None:
    with pytest.raises(ValueError, match="not found"):
        update_default_assistant_configuration(
            db_session=db_session, tool_ids=[2_000_000_000]
        )


def test_explicit_legacy_openapi_selection_enables_default_chat(
    db_session: Session, make_tool: ToolFactory
) -> None:
    tool = make_tool(enabled=False, openapi=True)
    update_default_assistant_configuration(db_session=db_session, tool_ids=[tool.id])
    db_session.refresh(tool)
    assert tool.enabled is True
    persona = get_default_assistant(db_session)
    assert persona is not None
    assert tool.id in [selected.id for selected in persona.tools]


@pytest.mark.parametrize("enabled", [True, False])
def test_targeted_default_chat_update_preserves_other_selection(
    db_session: Session, make_tool: ToolFactory, enabled: bool
) -> None:
    from onyx.db.persona import set_default_chat_tool__no_commit

    legacy = make_tool(enabled=False, openapi=True)
    target = make_tool(enabled=True, openapi=True)
    persona = get_default_assistant(db_session)
    assert persona is not None
    persona.tools = [legacy, target]
    db_session.commit()
    set_default_chat_tool__no_commit(db_session, target, enabled)
    db_session.commit()
    assert legacy.enabled is False
    assert legacy.id in [tool.id for tool in persona.tools]
    assert (target.id in [tool.id for tool in persona.tools]) is enabled


def test_targeted_default_chat_updates_do_not_replace_concurrent_selections(
    db_session: Session, make_tool: ToolFactory
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from onyx.db.persona import set_default_chat_tool__no_commit

    tools = [make_tool(enabled=True, openapi=True) for _ in range(2)]
    bind = db_session.get_bind()

    def select_tool(tool_id: int) -> None:
        with Session(bind=bind) as session:
            tool = session.get(Tool, tool_id)
            assert tool is not None
            set_default_chat_tool__no_commit(session, tool, True)
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(select_tool, [tool.id for tool in tools]))
    db_session.expire_all()
    persona = get_default_assistant(db_session)
    assert persona is not None
    assert {tool.id for tool in tools} <= {tool.id for tool in persona.tools}


@pytest.mark.parametrize("enabled", [True, False])
def test_custom_tool_api_saves_default_chat_with_metadata(
    db_session: Session,
    make_tool: ToolFactory,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    from onyx.db.models import User
    from onyx.db.tools import delete_tool__no_commit
    from onyx.server.features.tool import api
    from onyx.server.features.tool.models import CustomToolCreate, CustomToolUpdate
    from tests.external_dependency_unit.tools.test_disabled_tool_not_constructed import (
        OPENAPI_SCHEMA,
    )

    monkeypatch.setattr(api, "has_global_permission", lambda *_: True)
    monkeypatch.setattr(api, "can_manage_tool", lambda *_: True)
    monkeypatch.setattr(api, "_connected_tool_ids", lambda *_: set())
    unrelated = make_tool(enabled=False, openapi=True)
    persona = get_default_assistant(db_session)
    assert persona is not None
    persona.tools.append(unrelated)
    db_session.commit()
    created = api.create_custom_tool(
        CustomToolCreate(
            name="terraform-default-chat-test",
            definition={
                **OPENAPI_SCHEMA,
                "info": {**OPENAPI_SCHEMA["info"], "description": "Test API"},
            },
            passthrough_auth=False,
            default_chat_enabled=enabled,
        ),
        db_session,
        User(),
    )
    try:
        assert created.enabled is True
        assert created.default_chat_enabled is enabled
        assert (
            api.get_custom_tool(created.id, db_session, User()).default_chat_enabled
            is enabled
        )
        updated = api.update_custom_tool(
            created.id,
            CustomToolUpdate(name="renamed", default_chat_enabled=not enabled),
            db_session,
            User(),
        )
        assert updated.name == "renamed"
        assert updated.enabled is True
        assert updated.default_chat_enabled is not enabled
        assert (
            api.get_custom_tool(created.id, db_session, User()).default_chat_enabled
            is not enabled
        )
        assert unrelated.enabled is False
        assert unrelated.id in [tool.id for tool in persona.tools]

        def fail_selection(*_: object) -> None:
            raise ValueError("Default assistant not found")

        monkeypatch.setattr(api, "set_default_chat_tool__no_commit", fail_selection)
        from onyx.error_handling.exceptions import OnyxError

        with pytest.raises(OnyxError, match="Default assistant not found"):
            api.update_custom_tool(
                created.id,
                CustomToolUpdate(name="must roll back", default_chat_enabled=enabled),
                db_session,
                User(),
            )
        db_session.rollback()
        assert api.get_custom_tool(created.id, db_session, User()).name == "renamed"
    finally:
        delete_tool__no_commit(created.id, db_session)
        db_session.commit()
