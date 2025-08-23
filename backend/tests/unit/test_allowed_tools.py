"""
Unit tests for the allowed_tool_ids functionality
"""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.chat.models import PromptConfig
from onyx.context.search.enums import OptionalSearchSetting
from onyx.db.models import Persona
from onyx.db.models import Tool as DbToolModel
from onyx.db.models import User
from onyx.llm.interfaces import LLM
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_implementations.search.search_tool import SearchTool


def test_construct_tools_with_allowed_ids_filtering() -> None:
    """Test that construct_tools filters tools based on allowed_tool_ids"""
    # Create mock tools
    tool1 = Mock(spec=DbToolModel)
    tool1.id = 1
    tool1.in_code_tool_id = "SearchTool"

    tool2 = Mock(spec=DbToolModel)
    tool2.id = 2
    tool2.in_code_tool_id = "ImageGenerationTool"

    tool3 = Mock(spec=DbToolModel)
    tool3.id = 3
    tool3.in_code_tool_id = None
    tool3.openapi_schema = {"openapi": "3.0.0"}
    tool3.custom_headers = []
    tool3.passthrough_auth = False

    # Create mock persona with tools
    persona = Mock(spec=Persona)
    persona.tools = [tool1, tool2, tool3]
    persona.llm_relevance_filter = False

    # Create other required mocks
    prompt_config = Mock(spec=PromptConfig)
    db_session = Mock(spec=Session)
    user = Mock(spec=User)
    user.oauth_accounts = []

    llm = Mock(spec=LLM)
    llm.config.model_name = "gpt-4"
    llm.config.model_provider = "openai"

    fast_llm = Mock(spec=LLM)

    # Mock the get_built_in_tool_by_id function
    def mock_get_built_in_tool(tool_id: str, db_session: Session) -> type | None:
        if tool_id == "SearchTool":
            return SearchTool
        elif tool_id == "ImageGenerationTool":
            from onyx.tools.tool_implementations.images.image_generation_tool import (
                ImageGenerationTool,
            )

            return ImageGenerationTool
        return None

    # Test: Allow only tools 1 and 3
    with patch(
        "onyx.tools.tool_constructor.get_built_in_tool_by_id", mock_get_built_in_tool
    ):
        with patch(
            "onyx.tools.tool_constructor.build_custom_tools_from_openapi_schema_and_headers"
        ) as mock_custom:
            mock_custom.return_value = [Mock()]

            result = construct_tools(
                persona=persona,
                prompt_config=prompt_config,
                db_session=db_session,
                user=user,
                llm=llm,
                fast_llm=fast_llm,
                run_search_setting=OptionalSearchSetting.AUTO,
                allowed_tool_ids=[1, 3],  # Only allow tools 1 and 3
            )

            # Should only have tools 1 and 3
            assert len(result) == 2
            assert 1 in result
            assert 3 in result
            assert 2 not in result


def test_construct_tools_with_allowed_ids_all_tools() -> None:
    """Test that construct_tools allows all tools when allowed_tool_ids is None"""
    # Create mock tools
    tool1 = Mock(spec=DbToolModel)
    tool1.id = 1
    tool1.in_code_tool_id = "SearchTool"

    tool2 = Mock(spec=DbToolModel)
    tool2.id = 2
    tool2.in_code_tool_id = "ImageGenerationTool"

    tool3 = Mock(spec=DbToolModel)
    tool3.id = 3
    tool3.in_code_tool_id = None
    tool3.openapi_schema = {"openapi": "3.0.0"}
    tool3.custom_headers = []
    tool3.passthrough_auth = False

    # Create mock persona with tools
    persona = Mock(spec=Persona)
    persona.tools = [tool1, tool2, tool3]
    persona.llm_relevance_filter = False

    # Create other required mocks
    prompt_config = Mock(spec=PromptConfig)
    db_session = Mock(spec=Session)
    user = Mock(spec=User)
    user.oauth_accounts = []

    llm = Mock(spec=LLM)
    llm.config.model_name = "gpt-4"
    llm.config.model_provider = "openai"

    fast_llm = Mock(spec=LLM)

    # Mock the get_built_in_tool_by_id function
    def mock_get_built_in_tool(tool_id: str, db_session: Session) -> type | None:
        if tool_id == "SearchTool":
            return SearchTool
        elif tool_id == "ImageGenerationTool":
            from onyx.tools.tool_implementations.images.image_generation_tool import (
                ImageGenerationTool,
            )

            return ImageGenerationTool
        return None

    # Test: Allow all tools (None)
    with patch(
        "onyx.tools.tool_constructor.get_built_in_tool_by_id", mock_get_built_in_tool
    ):
        with patch(
            "onyx.tools.tool_constructor.build_custom_tools_from_openapi_schema_and_headers"
        ) as mock_custom:
            mock_custom.return_value = [Mock()]

            result = construct_tools(
                persona=persona,
                prompt_config=prompt_config,
                db_session=db_session,
                user=user,
                llm=llm,
                fast_llm=fast_llm,
                run_search_setting=OptionalSearchSetting.AUTO,
                allowed_tool_ids=None,  # Allow all tools
            )

            # Should have all 3 tools
            assert len(result) == 3
            assert 1 in result
            assert 2 in result
            assert 3 in result


def test_construct_tools_with_empty_allowed_list() -> None:
    """Test that construct_tools returns no tools when allowed_tool_ids is empty"""
    # Create mock tools
    tool1 = Mock(spec=DbToolModel)
    tool1.id = 1
    tool1.in_code_tool_id = "SearchTool"

    tool2 = Mock(spec=DbToolModel)
    tool2.id = 2
    tool2.in_code_tool_id = "ImageGenerationTool"

    tool3 = Mock(spec=DbToolModel)
    tool3.id = 3
    tool3.in_code_tool_id = None
    tool3.openapi_schema = {"openapi": "3.0.0"}
    tool3.custom_headers = []
    tool3.passthrough_auth = False

    # Create mock persona with tools
    persona = Mock(spec=Persona)
    persona.tools = [tool1, tool2, tool3]
    persona.llm_relevance_filter = False

    # Create other required mocks
    prompt_config = Mock(spec=PromptConfig)
    db_session = Mock(spec=Session)
    user = Mock(spec=User)
    user.oauth_accounts = []

    llm = Mock(spec=LLM)
    llm.config.model_name = "gpt-4"
    llm.config.model_provider = "openai"

    fast_llm = Mock(spec=LLM)

    # Test: Empty allowed list
    result = construct_tools(
        persona=persona,
        prompt_config=prompt_config,
        db_session=db_session,
        user=user,
        llm=llm,
        fast_llm=fast_llm,
        run_search_setting=OptionalSearchSetting.AUTO,
        allowed_tool_ids=[],  # No tools allowed
    )

    # Should have no tools
    assert len(result) == 0


if __name__ == "__main__":
    pytest.main([__file__])
