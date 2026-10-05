"""A disabled action must not reach the model.

Disabling an action leaves its `Persona__Tool` rows in place, and `construct_tools`
used to build every attached tool. Only the tool *listing* endpoints filtered on
`enabled`, so a disabled tool stayed callable by any request that sends no
`allowed_tool_ids` whitelist — which is most of them (the Slack bot and evals pass
None, and the web client omits it unless the user turned something off in chat).
"""

import queue
from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.db.models import Persona, Tool, User
from onyx.llm.factory import get_default_llm
from onyx.tools.tool_constructor import construct_tools
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

USER_EMAIL_PREFIX = "disabled_tool_check_user"

OPENAPI_SCHEMA: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Disabled Tool API", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/test": {
            "get": {
                "operationId": "test_operation",
                "summary": "Test operation",
                "description": "A test operation",
                "responses": {"200": {"description": "Success"}},
            }
        }
    },
}


@pytest.fixture(autouse=True)
def _default_llm_provider(db_session: Session) -> None:
    ensure_default_llm_provider(db_session)


@pytest.fixture(autouse=True)
def _cleanup(db_session: Session) -> Generator[None, None, None]:
    """These rows are public and listed, so leaving them behind would widen what
    other tests see in persona and action listings. Ordered by foreign key:
    personas reference both, and tool.user_id references the user."""
    yield
    db_session.rollback()
    for persona in (
        db_session.query(Persona)
        .filter(Persona.name.like("Disabled Tool Persona %"))
        .all()
    ):
        persona.tools = []
        persona.users = []
        db_session.delete(persona)
    db_session.commit()

    db_session.query(Tool).filter(Tool.name.like("disabled-tool-check-%")).delete(
        synchronize_session=False
    )
    db_session.commit()

    delete_test_user(
        db_session,
        *db_session.query(User)
        .filter(User.__table__.c.email.like(f"{USER_EMAIL_PREFIX}_%@example.com"))
        .all(),
    )
    db_session.commit()


def _create_tool(db_session: Session, user: User, *, enabled: bool) -> Tool:
    tool = Tool(
        name=f"disabled-tool-check-{uuid4().hex[:8]}",
        description="disabled tool construction test action",
        openapi_schema=OPENAPI_SCHEMA,
        user_id=user.id,
        passthrough_auth=False,
        enabled=enabled,
    )
    db_session.add(tool)
    db_session.commit()
    db_session.refresh(tool)
    return tool


def _create_persona(db_session: Session, user: User, tools: list[Tool]) -> Persona:
    persona = Persona(
        name=f"Disabled Tool Persona {uuid4().hex[:8]}",
        description="disabled tool construction test persona",
        system_prompt="You are a helpful assistant",
        task_prompt="Answer the user's question",
        tools=tools,
        document_sets=[],
        users=[user],
        groups=[],
        is_listed=True,
        is_public=True,
        display_priority=None,
        starter_messages=None,
        deleted=False,
    )
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


def test_disabled_tool_is_not_constructed(db_session: Session) -> None:
    """Without a whitelist nothing else filters, so `enabled` has to."""
    user = create_test_user(db_session, USER_EMAIL_PREFIX)
    disabled_tool = _create_tool(db_session, user, enabled=False)
    enabled_tool = _create_tool(db_session, user, enabled=True)
    persona = _create_persona(db_session, user, [disabled_tool, enabled_tool])

    tool_dict = construct_tools(
        persona=persona,
        db_session=db_session,
        emitter=Emitter(merged_queue=queue.Queue()),
        user=user,
        llm=get_default_llm(),
    )

    assert disabled_tool.id not in tool_dict
    assert enabled_tool.id in tool_dict


def test_disabled_tool_is_not_constructed_even_when_whitelisted(
    db_session: Session,
) -> None:
    """`allowed_tool_ids` is built from what the frontend can see, which is not
    filtered on `enabled` — so a whitelist must not resurrect a disabled tool."""
    user = create_test_user(db_session, USER_EMAIL_PREFIX)
    disabled_tool = _create_tool(db_session, user, enabled=False)
    persona = _create_persona(db_session, user, [disabled_tool])

    tool_dict = construct_tools(
        persona=persona,
        db_session=db_session,
        emitter=Emitter(merged_queue=queue.Queue()),
        user=user,
        llm=get_default_llm(),
        allowed_tool_ids=[disabled_tool.id],
    )

    assert disabled_tool.id not in tool_dict
