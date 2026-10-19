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
