"""Concurrent writes of the Default Chat tool selection serialize on the
default assistant and keep every tool that each writer adds."""

from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.models import Persona__Tool, Tool
from onyx.db.persona import (
    get_default_assistant,
    set_default_chat_tools__no_commit,
    update_default_assistant_configuration,
)

ToolFactory = Callable[[], int]


@pytest.fixture
def make_tool(db_session: Session) -> Generator[ToolFactory, None, None]:
    persona = get_default_assistant(db_session)
    assert persona is not None
    persona_id = persona.id
    original_tool_ids = {tool.id for tool in persona.tools}
    created: list[int] = []

    def _make() -> int:
        tool = Tool(
            name=f"default-chat-{uuid4().hex[:8]}",
            description="",
            in_code_tool_id=f"DefaultChatTestTool{uuid4().hex}",
            custom_headers=[],
            passthrough_auth=False,
            enabled=True,
        )
        db_session.add(tool)
        db_session.commit()
        created.append(tool.id)
        return tool.id

    try:
        yield _make
    finally:
        db_session.rollback()
        db_session.execute(
            delete(Persona__Tool).where(
                Persona__Tool.persona_id == persona_id,
                Persona__Tool.tool_id.not_in(original_tool_ids),
            )
        )
        kept = set(
            db_session.scalars(
                select(Persona__Tool.tool_id).where(
                    Persona__Tool.persona_id == persona_id
                )
            )
        )
        db_session.add_all(
            Persona__Tool(persona_id=persona_id, tool_id=tool_id)
            for tool_id in original_tool_ids - kept
        )
        db_session.execute(delete(Tool).where(Tool.id.in_(created)))
        db_session.commit()


def _selected(db_session: Session) -> set[int]:
    db_session.expire_all()
    persona = get_default_assistant(db_session)
    assert persona is not None
    return set(
        db_session.scalars(
            select(Persona__Tool.tool_id).where(Persona__Tool.persona_id == persona.id)
        )
    )


def test_concurrent_full_list_updates_do_not_fail(
    db_session: Session, make_tool: ToolFactory
) -> None:
    shared_ids = [make_tool() for _ in range(30)]
    extra_ids = [make_tool() for _ in range(8)]
    bind = db_session.get_bind()

    def replace_full_list(extra_id: int) -> None:
        with Session(bind=bind) as session:
            update_default_assistant_configuration(
                db_session=session, tool_ids=[*shared_ids, extra_id]
            )

    for _ in range(3):
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(replace_full_list, extra_ids))

    selected = _selected(db_session)
    assert set(shared_ids) <= selected
    assert len(selected & set(extra_ids)) == 1


def test_concurrent_targeted_adds_keep_every_tool(
    db_session: Session, make_tool: ToolFactory
) -> None:
    groups = [[make_tool() for _ in range(5)] for _ in range(6)]
    bind = db_session.get_bind()

    def add_tools(tool_ids: list[int]) -> None:
        with Session(bind=bind) as session:
            set_default_chat_tools__no_commit(session, tool_ids, True)
            session.commit()

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(add_tools, groups))

    selected = _selected(db_session)
    for ids in groups:
        assert set(ids) <= selected

    set_default_chat_tools__no_commit(db_session, groups[0], False)
    db_session.commit()
    selected = _selected(db_session)
    assert not set(groups[0]) & selected
    assert set(groups[1]) <= selected


def test_targeted_updates_do_not_replace_concurrent_selections(
    db_session: Session, make_tool: ToolFactory
) -> None:
    tool_ids = [make_tool(), make_tool()]
    bind = db_session.get_bind()

    def select_tool(tool_id: int) -> None:
        with Session(bind=bind) as session:
            set_default_chat_tools__no_commit(session, [tool_id], True)
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(select_tool, tool_ids))

    assert set(tool_ids) <= _selected(db_session)
