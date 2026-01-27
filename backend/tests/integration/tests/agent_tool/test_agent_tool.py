"""
Integration tests for AgentTool functionality.

Tests the ability for one persona to call another persona as a tool.
"""

import pytest

from onyx.chat.emitter import get_default_emitter
from onyx.document_index.factory import get_default_document_index
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.search_settings import get_active_search_settings
from onyx.llm.factory import get_default_llm
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import AgentToolOverrideKwargs, ToolCallException
from onyx.tools.tool_implementations.agent.agent_tool import AgentTool
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture
def parent_persona_fixture(admin_user: DATestUser):
    """Create parent persona for tests."""
    return PersonaManager.create(
        name="Parent Agent",
        description="Parent agent that can delegate to other agents",
        system_prompt="You are a parent agent that can delegate tasks",
        task_prompt="Delegate complex tasks to specialists",
        user_performing_action=admin_user,
    )


@pytest.fixture
def sub_persona_fixture(admin_user: DATestUser):
    """Create sub-agent persona for tests."""
    return PersonaManager.create(
        name="Sub Agent",
        description="Specialized sub-agent for handling delegated tasks",
        system_prompt="You are a specialized sub-agent",
        task_prompt="Answer questions concisely",
        user_performing_action=admin_user,
    )


def test_agent_tool_construction(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    parent_persona_fixture,
    sub_persona_fixture,
):
    """Test that AgentTool can be constructed properly."""

    with get_session_with_current_tenant() as db_session:
        active = get_active_search_settings(db_session)
        # Get user from database
        user = (
            db_session.query(User).filter_by(email=admin_user.email).first()
        )
        assert user is not None, "Test user not found in database"

        # Get personas from database
        parent_persona = get_persona_by_id(
            persona_id=parent_persona_fixture.id,
            db_session=db_session,
            user=user,
        )
        sub_persona = get_persona_by_id(
            persona_id=sub_persona_fixture.id,
            db_session=db_session,
            user=user,
        )

        assert parent_persona is not None, "Parent persona not found"
        assert sub_persona is not None, "Sub-agent persona not found"

        # Create AgentTool
        agent_tool = AgentTool(
            tool_id=99999,
            target_persona=sub_persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=get_default_llm(),
            document_index=get_default_document_index(active.primary, active.secondary),
            user_selected_filters=None,
        )

        # Verify tool properties
        assert agent_tool.id == 99999
        assert agent_tool.name == f"call_{sub_persona.name.lower().replace(' ', '_')}"
        assert agent_tool.display_name == f"Call {sub_persona.name}"
        assert sub_persona.name in agent_tool.description

        # Verify tool definition
        tool_def = agent_tool.tool_definition()
        assert tool_def["type"] == "function"
        assert "task" in tool_def["function"]["parameters"]["properties"]
        assert "task" in tool_def["function"]["parameters"]["required"]


def test_agent_tool_execution(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    parent_persona_fixture,
    sub_persona_fixture,
):
    """Test that AgentTool can execute and call sub-agent."""

    with get_session_with_current_tenant() as db_session:
        active = get_active_search_settings(db_session)
        # Get user from database
        user = (
            db_session.query(User).filter_by(email=admin_user.email).first()
        )
        assert user is not None

        # Get personas
        sub_persona = get_persona_by_id(
            persona_id=sub_persona_fixture.id,
            db_session=db_session,
            user=user,
        )

        # Create tool
        agent_tool = AgentTool(
            tool_id=99999,
            target_persona=sub_persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=get_default_llm(),
            document_index=get_default_document_index(active.primary, active.secondary),
            user_selected_filters=None,
        )

        # Execute tool
        result = agent_tool.run(
            placement=Placement(turn_index=0, tab_index=0, sub_turn_index=None),
            override_kwargs=AgentToolOverrideKwargs(
                agent_call_stack=[],
                max_recursion_depth=2,
                starting_citation_num=1,
                citation_mapping={},
            ),
            task="What are the main features of this application?",
        )

        # Verify result
        assert result is not None
        assert result.llm_facing_response is not None
        assert len(result.llm_facing_response) > 0


def test_recursion_prevention(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    sub_persona_fixture,
):
    """Test that AgentTool prevents recursive calls."""

    with get_session_with_current_tenant() as db_session:
        active = get_active_search_settings(db_session)
        # Get user
        user = (
            db_session.query(User).filter_by(email=admin_user.email).first()
        )
        assert user is not None

        # Get persona
        persona = get_persona_by_id(
            persona_id=sub_persona_fixture.id,
            db_session=db_session,
            user=user,
        )

        # Create tool
        agent_tool = AgentTool(
            tool_id=99999,
            target_persona=persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=get_default_llm(),
            document_index=get_default_document_index(active.primary, active.secondary),
            user_selected_filters=None,
        )

        # Attempt recursive call (persona already in call stack)
        with pytest.raises(ToolCallException) as exc_info:
            agent_tool.run(
                placement=Placement(turn_index=0, tab_index=0, sub_turn_index=None),
                override_kwargs=AgentToolOverrideKwargs(
                    agent_call_stack=[persona.id],  # Already in stack!
                    max_recursion_depth=2,
                    starting_citation_num=1,
                    citation_mapping={},
                ),
                task="Test recursion",
            )

        # Verify exception message
        assert "recursively" in exc_info.value.llm_facing_message.lower()


def test_depth_limiting(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    sub_persona_fixture,
):
    """Test that AgentTool enforces maximum recursion depth."""

    with get_session_with_current_tenant() as db_session:
        active = get_active_search_settings(db_session)
        # Get user
        user = (
            db_session.query(User).filter_by(email=admin_user.email).first()
        )
        assert user is not None

        # Get persona
        persona = get_persona_by_id(
            persona_id=sub_persona_fixture.id,
            db_session=db_session,
            user=user,
        )

        # Create tool
        agent_tool = AgentTool(
            tool_id=99999,
            target_persona=persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=get_default_llm(),
            document_index=get_default_document_index(active.primary, active.secondary),
            user_selected_filters=None,
        )

        # Attempt call at maximum depth
        # Use high IDs that won't collide with actual persona IDs to avoid
        # triggering the recursion check before the depth check
        with pytest.raises(ToolCallException) as exc_info:
            agent_tool.run(
                placement=Placement(turn_index=0, tab_index=0, sub_turn_index=None),
                override_kwargs=AgentToolOverrideKwargs(
                    agent_call_stack=[999998, 999999],  # Already at depth 2
                    max_recursion_depth=2,
                    starting_citation_num=1,
                    citation_mapping={},
                ),
                task="Test depth limit",
            )

        # Verify exception message
        assert "depth" in exc_info.value.llm_facing_message.lower()
