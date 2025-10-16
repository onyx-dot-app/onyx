from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.chat.turn.models import ChatTurnContext
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations_v2.okta_profile import _okta_profile_core


class MockEmitter:
    """Mock emitter for dependency injection"""

    def __init__(self) -> None:
        self.packet_history: list[Packet] = []

    def emit(self, packet: Packet) -> None:
        self.packet_history.append(packet)


class MockAggregatedContext:
    """Mock aggregated context for dependency injection"""

    def __init__(self) -> None:
        self.global_iteration_responses: list[IterationAnswer] = []


class MockRunDependencies:
    """Mock run dependencies for dependency injection"""

    def __init__(self) -> None:
        self.emitter = MockEmitter()


class MockOktaProfileTool:
    """Mock Okta profile tool for dependency injection"""

    def __init__(
        self, responses: list | None = None, should_raise_exception: bool = False
    ) -> None:
        self.responses = responses or []
        self.should_raise_exception = should_raise_exception

    def run(self) -> list:
        if self.should_raise_exception:
            raise Exception("Test exception from Okta profile tool")
        return self.responses


def create_test_run_context(
    current_run_step: int = 0,
) -> RunContextWrapper[ChatTurnContext]:
    """Create a real RunContextWrapper with test dependencies"""

    # Create test dependencies
    emitter = MockEmitter()
    aggregated_context = MockAggregatedContext()

    run_dependencies = MockRunDependencies()
    run_dependencies.emitter = emitter

    # Create the actual context object
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.THOUGHTFUL,
        current_run_step=current_run_step,
        iteration_instructions=[],
        aggregated_context=aggregated_context,  # type: ignore[arg-type]
        run_dependencies=run_dependencies,  # type: ignore[arg-type]
    )

    # Create the run context wrapper
    run_context = RunContextWrapper(context=context)

    return run_context


def test_okta_profile_core_basic_functionality() -> None:
    """Test basic functionality of _okta_profile_core function"""
    # Arrange
    test_run_context = create_test_run_context()

    # Create test profile data
    test_profile_data = {
        "firstName": "John",
        "lastName": "Doe",
        "email": "john.doe@example.com",
        "title": "Software Engineer",
        "department": "Engineering",
        "location": "San Francisco",
        "manager": "Jane Smith",
        "phone": "+1-555-0123",
        "employeeId": "EMP001",
    }

    test_responses = [
        Mock(
            id="okta_profile",
            response=test_profile_data,
        ),
    ]

    test_tool = MockOktaProfileTool(responses=test_responses)

    # Act
    result = _okta_profile_core(test_run_context, test_tool)

    # Assert
    assert isinstance(result, dict)
    assert result == test_profile_data
    assert result["firstName"] == "John"
    assert result["lastName"] == "Doe"
    assert result["email"] == "john.doe@example.com"
    assert result["title"] == "Software Engineer"
    assert result["department"] == "Engineering"
    assert result["location"] == "San Francisco"
    assert result["manager"] == "Jane Smith"
    assert result["phone"] == "+1-555-0123"
    assert result["employeeId"] == "EMP001"

    # Verify context was updated
    assert test_run_context.context.current_run_step == 2

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 4

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, CustomToolStart)
    assert isinstance(emitter.packet_history[1].obj, CustomToolDelta)
    assert isinstance(emitter.packet_history[2].obj, CustomToolDelta)
    assert isinstance(emitter.packet_history[3].obj, SectionEnd)

    # Check the CustomToolStart event
    start_event = emitter.packet_history[0].obj
    assert start_event.type == "custom_tool_start"
    assert start_event.tool_name == "Okta Profile"

    # Check the first CustomToolDelta event (fetching message)
    first_delta = emitter.packet_history[1].obj
    assert first_delta.type == "custom_tool_delta"
    assert first_delta.tool_name == "Okta Profile"
    assert first_delta.response_type == "text"
    assert first_delta.data == "Fetching profile information..."

    # Check the second CustomToolDelta event (final result)
    second_delta = emitter.packet_history[2].obj
    assert second_delta.type == "custom_tool_delta"
    assert second_delta.tool_name == "Okta Profile"
    assert second_delta.response_type == "json"
    assert second_delta.data == test_profile_data


def test_okta_profile_core_minimal_profile() -> None:
    """Test _okta_profile_core with minimal profile data"""
    # Arrange
    test_run_context = create_test_run_context()

    # Create minimal profile data
    test_profile_data = {
        "firstName": "Jane",
        "lastName": "Smith",
        "email": "jane.smith@example.com",
    }

    test_responses = [
        Mock(
            id="okta_profile",
            response=test_profile_data,
        ),
    ]

    test_tool = MockOktaProfileTool(responses=test_responses)

    # Act
    result = _okta_profile_core(test_run_context, test_tool)

    # Assert
    assert isinstance(result, dict)
    assert result == test_profile_data
    assert result["firstName"] == "Jane"
    assert result["lastName"] == "Smith"
    assert result["email"] == "jane.smith@example.com"
    assert len(result) == 3

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 4


def test_okta_profile_core_no_profile_data() -> None:
    """Test _okta_profile_core when no profile data is returned"""
    # Arrange
    test_run_context = create_test_run_context()

    # Create responses that don't contain profile data
    test_responses = [
        Mock(
            id="other_response",
            response="some other data",
        ),
    ]

    test_tool = MockOktaProfileTool(responses=test_responses)

    # Act & Assert
    with pytest.raises(RuntimeError, match="No profile data was retrieved from Okta"):
        _okta_profile_core(test_run_context, test_tool)

    # Verify that even though an exception was raised, we still emitted the initial events
    # and the SectionEnd packet was emitted by the decorator
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 3

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, CustomToolStart)
    assert isinstance(emitter.packet_history[1].obj, CustomToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SectionEnd)

    # Verify that the decorator properly handled the exception and updated current_run_step
    assert test_run_context.context.current_run_step == 2


def test_okta_profile_core_exception_handling() -> None:
    """Test that _okta_profile_core handles exceptions properly"""
    # Arrange
    test_run_context = create_test_run_context()

    # Create a tool that will raise an exception
    test_tool = MockOktaProfileTool(should_raise_exception=True)

    # Act & Assert
    with pytest.raises(Exception, match="Test exception from Okta profile tool"):
        _okta_profile_core(test_run_context, test_tool)

    # Verify that even though an exception was raised, we still emitted the initial events
    # and the SectionEnd packet was emitted by the decorator
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 3

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, CustomToolStart)
    assert isinstance(emitter.packet_history[1].obj, CustomToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SectionEnd)

    # Verify that the decorator properly handled the exception and updated current_run_step
    assert test_run_context.context.current_run_step == 2


def test_okta_profile_core_none_tool() -> None:
    """Test that _okta_profile_core handles None tool properly"""
    # Arrange
    test_run_context = create_test_run_context()

    # Act & Assert
    with pytest.raises(
        RuntimeError, match="Okta profile tool not available in context"
    ):
        _okta_profile_core(test_run_context, None)

    # Verify that even though an exception was raised, we still emitted the SectionEnd packet
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 1
    assert isinstance(emitter.packet_history[0].obj, SectionEnd)

    # Verify that the decorator properly handled the exception and updated current_run_step
    assert test_run_context.context.current_run_step == 2


def test_okta_profile_core_empty_responses() -> None:
    """Test _okta_profile_core with empty tool responses"""
    # Arrange
    test_run_context = create_test_run_context()

    # Create empty responses
    test_tool = MockOktaProfileTool(responses=[])

    # Act & Assert
    with pytest.raises(RuntimeError, match="No profile data was retrieved from Okta"):
        _okta_profile_core(test_run_context, test_tool)

    # Verify that even though an exception was raised, we still emitted the initial events
    # and the SectionEnd packet was emitted by the decorator
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 3

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, CustomToolStart)
    assert isinstance(emitter.packet_history[1].obj, CustomToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SectionEnd)


def test_okta_profile_core_multiple_responses() -> None:
    """Test _okta_profile_core with multiple tool responses"""
    # Arrange
    test_run_context = create_test_run_context()

    # Create test profile data
    test_profile_data = {
        "firstName": "Alice",
        "lastName": "Johnson",
        "email": "alice.johnson@example.com",
        "title": "Product Manager",
    }

    # Create multiple responses (should break after first "okta_profile" id)
    test_responses = [
        Mock(
            id="other_response",
            response="ignored data",
        ),
        Mock(
            id="okta_profile",
            response=test_profile_data,
        ),
        Mock(
            id="another_response",
            response="should_not_be_processed",
        ),
    ]

    test_tool = MockOktaProfileTool(responses=test_responses)

    # Act
    result = _okta_profile_core(test_run_context, test_tool)

    # Assert
    assert result == test_profile_data
    assert result["firstName"] == "Alice"
    assert result["lastName"] == "Johnson"
    assert result["email"] == "alice.johnson@example.com"
    assert result["title"] == "Product Manager"

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 4


def test_okta_profile_core_complex_profile_data() -> None:
    """Test _okta_profile_core with complex profile data"""
    # Arrange
    test_run_context = create_test_run_context()

    # Create complex profile data with nested structures
    test_profile_data = {
        "firstName": "Bob",
        "lastName": "Wilson",
        "email": "bob.wilson@example.com",
        "title": "Senior Software Engineer",
        "department": "Engineering",
        "location": {
            "city": "New York",
            "state": "NY",
            "country": "USA",
        },
        "manager": {
            "firstName": "Carol",
            "lastName": "Davis",
            "email": "carol.davis@example.com",
        },
        "skills": ["Python", "JavaScript", "React", "Docker"],
        "certifications": [
            {
                "name": "AWS Solutions Architect",
                "date": "2023-01-15",
            },
            {
                "name": "Kubernetes Administrator",
                "date": "2023-06-20",
            },
        ],
        "phone": "+1-555-9876",
        "employeeId": "EMP123",
        "startDate": "2022-03-01",
    }

    test_responses = [
        Mock(
            id="okta_profile",
            response=test_profile_data,
        ),
    ]

    test_tool = MockOktaProfileTool(responses=test_responses)

    # Act
    result = _okta_profile_core(test_run_context, test_tool)

    # Assert
    assert isinstance(result, dict)
    assert result == test_profile_data
    assert result["firstName"] == "Bob"
    assert result["lastName"] == "Wilson"
    assert result["location"]["city"] == "New York"
    assert result["location"]["state"] == "NY"
    assert result["manager"]["firstName"] == "Carol"
    assert result["skills"] == ["Python", "JavaScript", "React", "Docker"]
    assert len(result["certifications"]) == 2
    assert result["certifications"][0]["name"] == "AWS Solutions Architect"

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 4

    # Check the final CustomToolDelta event contains the complex data
    final_delta = emitter.packet_history[2].obj
    assert isinstance(final_delta, CustomToolDelta)
    assert final_delta.data == test_profile_data
