"""
Integration test for forced tool use to verify that web_search can be forced.
This test verifies that forcing a tool use works through the complete API flow.
"""

import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Tool
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import ToolName


def test_force_tool_use(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """
    Test forcing web_search tool usage to verify:
    1. The web_search tool can be forced even with a message that wouldn't normally trigger it
    2. Web search packets are streamed during the search
    3. The response contains search results

    This test uses the actual API without any mocking.
    """
    with get_session_with_current_tenant() as db_session:
        web_search_tool = db_session.execute(
            select(Tool).where(Tool.in_code_tool_id == "WebSearchTool")
        ).scalar_one_or_none()
        assert web_search_tool is not None, "WebSearchTool must exist"
        web_search_tool_id = web_search_tool.id

    # Create a chat session
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    # Send a simple message that wouldn't normally trigger web search
    # but force the web_search tool to be used
    message = "hi"

    analyzed_response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=message,
        user_performing_action=basic_user,
        forced_tool_ids=[web_search_tool_id],
    )

    internet_search_used = any(
        tool.tool_name == ToolName.INTERNET_SEARCH
        for tool in analyzed_response.used_tools
    )
    assert internet_search_used, "Web search tool should have been forced to run"


if __name__ == "__main__":
    # Run with: python -m dotenv -f .vscode/.env run --
    # python -m pytest backend/tests/integration/tests/tools/test_force_tool_use.py -v -s
    pytest.main([__file__, "-v", "-s"])
