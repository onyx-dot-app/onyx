"""Code mode type-checks a program's postgres_query calls against the stub
built from the tool's schema."""

from unittest.mock import MagicMock

from onyx.db.postgres_tool_models import DocumentScope
from onyx.tools.tool_implementations.code_mode.stubs import build_tool_stubs
from onyx.tools.tool_implementations.postgres.postgres_tool import PostgresTool


def test_list_filters_take_one_value_or_a_list() -> None:
    tool = PostgresTool(
        user=MagicMock(), current_chat_session_id=None, scope=DocumentScope()
    )
    stub = build_tool_stubs([tool]).listed_text
    assert "title_contains: str | list[str] | None" in stub
    assert "parent_id: int | list[int] | None" in stub
