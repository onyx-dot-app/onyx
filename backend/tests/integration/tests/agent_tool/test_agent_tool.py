"""
Integration tests for AgentTool functionality.

Tests the ability for one persona to call another persona as a tool.
"""

import pytest

from onyx.chat.emitter import get_default_emitter
from onyx.document_index.factory import get_default_document_index
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Persona__CallablePersona, User
from onyx.db.persona import get_persona_by_id
from onyx.db.search_settings import get_active_search_settings
from onyx.llm.factory import get_default_llm
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import AgentToolOverrideKwargs, ToolCallException
from onyx.tools.tool_constructor import AgentToolConfig, construct_tools
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


def test_missing_task_parameter(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    sub_persona_fixture,
):
    """Test that AgentTool raises error when task parameter is missing."""

    with get_session_with_current_tenant() as db_session:
        active = get_active_search_settings(db_session)
        user = db_session.query(User).filter_by(email=admin_user.email).first()
        assert user is not None

        persona = get_persona_by_id(
            persona_id=sub_persona_fixture.id,
            db_session=db_session,
            user=user,
        )

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

        # Call without task parameter
        with pytest.raises(ToolCallException) as exc_info:
            agent_tool.run(
                placement=Placement(turn_index=0, tab_index=0, sub_turn_index=None),
                override_kwargs=AgentToolOverrideKwargs(),
                # No task parameter provided
            )

        assert "task" in exc_info.value.llm_facing_message.lower()


# =============================================================================
# Integration tests for callable_personas relationship
# =============================================================================


@pytest.fixture
def specialist_agent_fixture(admin_user: DATestUser):
    """Create a specialist agent persona."""
    return PersonaManager.create(
        name="Specialist Agent",
        description="A specialist agent for specific tasks",
        system_prompt="You are a specialist",
        task_prompt="Handle specialized requests",
        user_performing_action=admin_user,
    )


@pytest.fixture
def researcher_agent_fixture(admin_user: DATestUser):
    """Create a researcher agent persona."""
    return PersonaManager.create(
        name="Researcher Agent",
        description="A researcher agent for research tasks",
        system_prompt="You are a researcher",
        task_prompt="Conduct research",
        user_performing_action=admin_user,
    )


def test_callable_personas_relationship(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    parent_persona_fixture,
    sub_persona_fixture,
    specialist_agent_fixture,
):
    """Test that callable_personas relationship works correctly."""

    with get_session_with_current_tenant() as db_session:
        user = db_session.query(User).filter_by(email=admin_user.email).first()
        assert user is not None

        # Get personas
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
        specialist = get_persona_by_id(
            persona_id=specialist_agent_fixture.id,
            db_session=db_session,
            user=user,
        )

        # Initially, no callable personas
        assert len(parent_persona.callable_personas) == 0

        # Add callable personas through the association table
        db_session.add(Persona__CallablePersona(
            caller_persona_id=parent_persona.id,
            callee_persona_id=sub_persona.id,
        ))
        db_session.add(Persona__CallablePersona(
            caller_persona_id=parent_persona.id,
            callee_persona_id=specialist.id,
        ))
        db_session.commit()

        # Refresh the persona
        db_session.refresh(parent_persona)

        # Should now have two callable personas
        assert len(parent_persona.callable_personas) == 2

        callable_ids = {p.id for p in parent_persona.callable_personas}
        assert sub_persona.id in callable_ids
        assert specialist.id in callable_ids


def test_construct_tools_creates_agent_tools_for_callable_personas(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    parent_persona_fixture,
    sub_persona_fixture,
    specialist_agent_fixture,
):
    """Test that construct_tools creates AgentTools for each callable persona."""

    with get_session_with_current_tenant() as db_session:
        user = db_session.query(User).filter_by(email=admin_user.email).first()
        assert user is not None

        # Get personas
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
        specialist = get_persona_by_id(
            persona_id=specialist_agent_fixture.id,
            db_session=db_session,
            user=user,
        )

        # Add callable personas
        db_session.add(Persona__CallablePersona(
            caller_persona_id=parent_persona.id,
            callee_persona_id=sub_persona.id,
        ))
        db_session.add(Persona__CallablePersona(
            caller_persona_id=parent_persona.id,
            callee_persona_id=specialist.id,
        ))
        db_session.commit()
        db_session.refresh(parent_persona)

        # Construct tools
        tool_dict = construct_tools(
            persona=parent_persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=get_default_llm(),
            agent_tool_config=AgentToolConfig(),
        )

        # Should have AgentTools for each callable persona
        # IDs are negative of target persona IDs
        assert -sub_persona.id in tool_dict
        assert -specialist.id in tool_dict

        # Verify tools are AgentTool instances
        sub_agent_tool = tool_dict[-sub_persona.id][0]
        specialist_tool = tool_dict[-specialist.id][0]

        assert isinstance(sub_agent_tool, AgentTool)
        assert isinstance(specialist_tool, AgentTool)

        # Verify tool names follow pattern
        assert sub_agent_tool.name == "call_sub_agent"
        assert specialist_tool.name == "call_specialist_agent"


def test_agent_tool_execution_via_construct_tools(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    parent_persona_fixture,
    sub_persona_fixture,
):
    """Test that AgentTools created via construct_tools can execute."""

    with get_session_with_current_tenant() as db_session:
        user = db_session.query(User).filter_by(email=admin_user.email).first()
        assert user is not None

        # Get personas
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

        # Add callable persona
        db_session.add(Persona__CallablePersona(
            caller_persona_id=parent_persona.id,
            callee_persona_id=sub_persona.id,
        ))
        db_session.commit()
        db_session.refresh(parent_persona)

        # Construct tools
        tool_dict = construct_tools(
            persona=parent_persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=get_default_llm(),
        )

        # Get the agent tool
        agent_tool = tool_dict[-sub_persona.id][0]

        # Execute the tool
        result = agent_tool.run(
            placement=Placement(turn_index=0, tab_index=0, sub_turn_index=None),
            override_kwargs=AgentToolOverrideKwargs(
                agent_call_stack=[],
                max_recursion_depth=2,
                starting_citation_num=1,
                citation_mapping={},
            ),
            task="Summarize your capabilities",
        )

        # Verify result
        assert result is not None
        assert result.llm_facing_response is not None


def test_cascade_delete_callable_persona(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    parent_persona_fixture,
    sub_persona_fixture,
):
    """Test that deleting a persona cascades to callable_persona relationships."""

    with get_session_with_current_tenant() as db_session:
        user = db_session.query(User).filter_by(email=admin_user.email).first()
        assert user is not None

        # Get personas
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

        # Add callable persona relationship
        db_session.add(Persona__CallablePersona(
            caller_persona_id=parent_persona.id,
            callee_persona_id=sub_persona.id,
        ))
        db_session.commit()

        # Verify relationship exists
        relationship = db_session.query(Persona__CallablePersona).filter_by(
            caller_persona_id=parent_persona.id,
            callee_persona_id=sub_persona.id,
        ).first()
        assert relationship is not None

        # Delete the sub-persona (callee)
        sub_persona_id = sub_persona.id
        db_session.delete(sub_persona)
        db_session.commit()

        # Verify relationship was cascaded
        relationship = db_session.query(Persona__CallablePersona).filter_by(
            caller_persona_id=parent_persona.id,
            callee_persona_id=sub_persona_id,
        ).first()
        assert relationship is None


def test_multiple_callers_single_callee(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    parent_persona_fixture,
    sub_persona_fixture,
    researcher_agent_fixture,
):
    """Test that multiple personas can call the same target persona."""

    with get_session_with_current_tenant() as db_session:
        user = db_session.query(User).filter_by(email=admin_user.email).first()
        assert user is not None

        # Get personas
        caller1 = get_persona_by_id(
            persona_id=parent_persona_fixture.id,
            db_session=db_session,
            user=user,
        )
        caller2 = get_persona_by_id(
            persona_id=researcher_agent_fixture.id,
            db_session=db_session,
            user=user,
        )
        target = get_persona_by_id(
            persona_id=sub_persona_fixture.id,
            db_session=db_session,
            user=user,
        )

        # Both callers can call the same target
        db_session.add(Persona__CallablePersona(
            caller_persona_id=caller1.id,
            callee_persona_id=target.id,
        ))
        db_session.add(Persona__CallablePersona(
            caller_persona_id=caller2.id,
            callee_persona_id=target.id,
        ))
        db_session.commit()

        # Refresh
        db_session.refresh(caller1)
        db_session.refresh(caller2)

        # Both should be able to call target
        assert len(caller1.callable_personas) == 1
        assert len(caller2.callable_personas) == 1
        assert caller1.callable_personas[0].id == target.id
        assert caller2.callable_personas[0].id == target.id
