"""
Unit tests for tool_constructor.py.

Tests the construction of tools for personas, including AgentTool creation.
"""

from unittest.mock import MagicMock, patch

import pytest

from onyx.tools.tool_constructor import (
    AgentToolConfig,
    construct_tools,
)


class MockPersona:
    """Mock persona for testing."""

    def __init__(
        self,
        id: int,
        name: str,
        tools: list | None = None,
        callable_personas: list | None = None,
    ):
        self.id = id
        self.name = name
        self.description = f"Description for {name}"
        self.system_prompt = f"System prompt for {name}"
        self.task_prompt = f"Task prompt for {name}"
        self.tools = tools or []
        self.callable_personas = callable_personas or []
        self.datetime_aware = True


class MockEmitter:
    """Mock emitter for testing."""

    def emit(self, packet):
        pass


class MockLLM:
    """Mock LLM for testing."""

    def __init__(self):
        self.config = MagicMock()
        self.config.max_input_tokens = 4096


class MockDocumentIndex:
    """Mock document index for testing."""

    pass


class TestAgentToolConfig:
    """Tests for AgentToolConfig class."""

    def test_default_values(self):
        """Test that AgentToolConfig has correct defaults."""
        config = AgentToolConfig()

        assert config.user_selected_filters is None
        assert config.is_connected_fn is None

    def test_with_values(self):
        """Test AgentToolConfig with provided values."""
        from onyx.context.search.models import BaseFilters

        mock_filters = BaseFilters()
        mock_fn = lambda: True

        config = AgentToolConfig(
            user_selected_filters=mock_filters,
            is_connected_fn=mock_fn,
        )

        assert config.user_selected_filters == mock_filters
        assert config.is_connected_fn == mock_fn


class TestConstructToolsWithCallablePersonas:
    """Tests for construct_tools with callable personas."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = MagicMock()
        return session

    @pytest.fixture
    def mock_search_settings(self):
        """Mock for search settings."""
        settings = MagicMock()
        settings.primary = MagicMock()
        settings.secondary = None
        return settings

    @patch("onyx.tools.tool_constructor.get_current_search_settings")
    @patch("onyx.tools.tool_constructor.get_default_document_index")
    def test_no_callable_personas_returns_empty_agent_tools(
        self,
        mock_get_doc_index,
        mock_get_search_settings,
        mock_db_session,
        mock_search_settings,
    ):
        """Test that no AgentTools are created when no callable personas."""
        mock_get_search_settings.return_value = mock_search_settings
        mock_get_doc_index.return_value = MockDocumentIndex()

        # Persona with no callable personas
        persona = MockPersona(
            id=1,
            name="Test Persona",
            tools=[],
            callable_personas=[],
        )

        tool_dict = construct_tools(
            persona=persona,
            db_session=mock_db_session,
            emitter=MockEmitter(),
            user=None,
            llm=MockLLM(),
        )

        # Should have no tools
        assert len(tool_dict) == 0

    @patch("onyx.tools.tool_constructor.get_current_search_settings")
    @patch("onyx.tools.tool_constructor.get_default_document_index")
    def test_single_callable_persona_creates_agent_tool(
        self,
        mock_get_doc_index,
        mock_get_search_settings,
        mock_db_session,
        mock_search_settings,
    ):
        """Test that one AgentTool is created for one callable persona."""
        mock_get_search_settings.return_value = mock_search_settings
        mock_get_doc_index.return_value = MockDocumentIndex()

        # Target persona
        target_persona = MockPersona(id=2, name="Research Agent")

        # Main persona with one callable persona
        persona = MockPersona(
            id=1,
            name="Main Persona",
            tools=[],
            callable_personas=[target_persona],
        )

        tool_dict = construct_tools(
            persona=persona,
            db_session=mock_db_session,
            emitter=MockEmitter(),
            user=None,
            llm=MockLLM(),
        )

        # Should have one AgentTool with synthetic negative ID
        assert len(tool_dict) == 1
        assert -2 in tool_dict  # -target_persona.id

        agent_tool = tool_dict[-2][0]
        assert agent_tool.name == "call_research_agent"
        assert agent_tool.target_persona == target_persona

    @patch("onyx.tools.tool_constructor.get_current_search_settings")
    @patch("onyx.tools.tool_constructor.get_default_document_index")
    def test_multiple_callable_personas_creates_multiple_agent_tools(
        self,
        mock_get_doc_index,
        mock_get_search_settings,
        mock_db_session,
        mock_search_settings,
    ):
        """Test that multiple AgentTools are created for multiple callable personas."""
        mock_get_search_settings.return_value = mock_search_settings
        mock_get_doc_index.return_value = MockDocumentIndex()

        # Target personas
        target_1 = MockPersona(id=10, name="Research Agent")
        target_2 = MockPersona(id=20, name="Writing Agent")
        target_3 = MockPersona(id=30, name="Code Agent")

        # Main persona with multiple callable personas
        persona = MockPersona(
            id=1,
            name="Orchestrator",
            tools=[],
            callable_personas=[target_1, target_2, target_3],
        )

        tool_dict = construct_tools(
            persona=persona,
            db_session=mock_db_session,
            emitter=MockEmitter(),
            user=None,
            llm=MockLLM(),
        )

        # Should have three AgentTools
        assert len(tool_dict) == 3

        # Check each tool exists with correct synthetic ID
        assert -10 in tool_dict
        assert -20 in tool_dict
        assert -30 in tool_dict

        # Verify tool names
        tool_names = {tool_dict[tid][0].name for tid in tool_dict}
        assert "call_research_agent" in tool_names
        assert "call_writing_agent" in tool_names
        assert "call_code_agent" in tool_names

    @patch("onyx.tools.tool_constructor.get_current_search_settings")
    @patch("onyx.tools.tool_constructor.get_default_document_index")
    def test_agent_tool_config_is_passed(
        self,
        mock_get_doc_index,
        mock_get_search_settings,
        mock_db_session,
        mock_search_settings,
    ):
        """Test that AgentToolConfig values are used when creating AgentTools."""
        from onyx.context.search.models import BaseFilters

        mock_get_search_settings.return_value = mock_search_settings
        mock_get_doc_index.return_value = MockDocumentIndex()

        target_persona = MockPersona(id=5, name="Helper")

        persona = MockPersona(
            id=1,
            name="Main",
            tools=[],
            callable_personas=[target_persona],
        )

        # Create config with real filter type
        test_filters = BaseFilters()
        agent_config = AgentToolConfig(
            user_selected_filters=test_filters,
        )

        tool_dict = construct_tools(
            persona=persona,
            db_session=mock_db_session,
            emitter=MockEmitter(),
            user=None,
            llm=MockLLM(),
            agent_tool_config=agent_config,
        )

        # Verify config was passed
        agent_tool = tool_dict[-5][0]
        assert agent_tool.user_selected_filters == test_filters

    @patch("onyx.tools.tool_constructor.get_current_search_settings")
    @patch("onyx.tools.tool_constructor.get_default_document_index")
    def test_synthetic_ids_are_unique_negative(
        self,
        mock_get_doc_index,
        mock_get_search_settings,
        mock_db_session,
        mock_search_settings,
    ):
        """Test that synthetic tool IDs are negative and unique per target."""
        mock_get_search_settings.return_value = mock_search_settings
        mock_get_doc_index.return_value = MockDocumentIndex()

        # Targets with different IDs
        targets = [
            MockPersona(id=100, name="Agent A"),
            MockPersona(id=200, name="Agent B"),
        ]

        persona = MockPersona(
            id=1,
            name="Orchestrator",
            tools=[],
            callable_personas=targets,
        )

        tool_dict = construct_tools(
            persona=persona,
            db_session=mock_db_session,
            emitter=MockEmitter(),
            user=None,
            llm=MockLLM(),
        )

        # All IDs should be negative
        for tool_id in tool_dict.keys():
            assert tool_id < 0, f"Expected negative ID, got {tool_id}"

        # IDs should match -persona_id pattern
        assert -100 in tool_dict
        assert -200 in tool_dict


class TestAgentToolDefinition:
    """Tests for AgentTool tool_definition method via construct_tools."""

    @patch("onyx.tools.tool_constructor.get_current_search_settings")
    @patch("onyx.tools.tool_constructor.get_default_document_index")
    def test_tool_definition_structure(
        self,
        mock_get_doc_index,
        mock_get_search_settings,
    ):
        """Test that created AgentTool has correct tool definition structure."""
        mock_search_settings = MagicMock()
        mock_search_settings.primary = MagicMock()
        mock_search_settings.secondary = None
        mock_get_search_settings.return_value = mock_search_settings
        mock_get_doc_index.return_value = MockDocumentIndex()

        target = MockPersona(id=5, name="Specialist")

        persona = MockPersona(
            id=1,
            name="Main",
            tools=[],
            callable_personas=[target],
        )

        tool_dict = construct_tools(
            persona=persona,
            db_session=MagicMock(),
            emitter=MockEmitter(),
            user=None,
            llm=MockLLM(),
        )

        agent_tool = tool_dict[-5][0]
        tool_def = agent_tool.tool_definition()

        # Verify structure
        assert tool_def["type"] == "function"
        assert "function" in tool_def

        func_def = tool_def["function"]
        assert func_def["name"] == "call_specialist"
        assert "parameters" in func_def
        assert func_def["parameters"]["type"] == "object"
        assert "task" in func_def["parameters"]["properties"]
        assert "task" in func_def["parameters"]["required"]
