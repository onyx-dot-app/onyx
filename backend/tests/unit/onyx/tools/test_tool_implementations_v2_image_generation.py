from typing import Any
from unittest.mock import Mock
from unittest.mock import patch
from uuid import uuid4

import pytest
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import GeneratedImage
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.turn.models import ChatTurnContext
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolDelta
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationResponse,
)
from onyx.tools.tool_implementations_v2.image_generation import _image_generation_core


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


class MockRedisClient:
    """Mock Redis client for dependency injection"""

    def __init__(self, is_cancelled: bool = False) -> None:
        self.is_cancelled = is_cancelled

    def exists(self, key: str) -> bool:
        """Mock Redis exists method - returns True if session is cancelled"""
        return self.is_cancelled


class MockRunDependencies:
    """Mock run dependencies for dependency injection"""

    def __init__(self, redis_client: MockRedisClient | None = None) -> None:
        self.emitter = MockEmitter()
        self.redis_client = redis_client or MockRedisClient(is_cancelled=False)


class MockImageGenerationTool:
    """Mock image generation tool for dependency injection"""

    def __init__(
        self, responses: list | None = None, should_raise_exception: bool = False
    ) -> None:
        self.responses = responses or []
        self.should_raise_exception = should_raise_exception
        self.name = "image_generation_tool"
        self.id = 2
        self.run = Mock(side_effect=self._run_side_effect)

    def _run_side_effect(self, **kwargs: Any) -> list:
        if self.should_raise_exception:
            raise Exception("Test exception from image generation tool")
        return self.responses


def create_test_run_context(
    current_run_step: int = 0,
    redis_client: MockRedisClient | None = None,
) -> RunContextWrapper[ChatTurnContext]:
    """Create a real RunContextWrapper with test dependencies"""

    # Create test dependencies
    emitter = MockEmitter()
    aggregated_context = MockAggregatedContext()

    run_dependencies = MockRunDependencies(redis_client=redis_client)
    run_dependencies.emitter = emitter

    # Create the actual context object
    context = ChatTurnContext(
        current_run_step=current_run_step,
        iteration_instructions=[],
        aggregated_context=aggregated_context,  # type: ignore[arg-type]
        run_dependencies=run_dependencies,  # type: ignore[arg-type]
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.THOUGHTFUL,
    )

    # Create the run context wrapper
    run_context = RunContextWrapper(context=context)

    return run_context


@patch("onyx.tools.tool_implementations_v2.image_generation.save_files")
@patch("onyx.tools.tool_implementations_v2.image_generation.build_frontend_file_url")
def test_image_generation_core_basic_functionality(
    mock_build_frontend_file_url: Mock, mock_save_files: Mock
) -> None:
    """Test basic functionality of _image_generation_core function"""
    # Arrange
    test_run_context = create_test_run_context()
    prompt = "test image prompt"
    shape = "square"

    # Mock file operations
    mock_save_files.return_value = ["file_id_1", "file_id_2"]
    mock_build_frontend_file_url.return_value = "http://frontend/file_id_1"

    # Create test image generation responses
    test_responses = [
        Mock(
            id="image_generation_heartbeat",
            response=None,
        ),
        Mock(
            id="image_generation_response",
            response=[
                ImageGenerationResponse(
                    url="https://example.com/image1.jpg",
                    image_data=None,
                    revised_prompt="Revised: test image prompt",
                ),
                ImageGenerationResponse(
                    url=None,
                    image_data="base64_image_data",
                    revised_prompt="Revised: test image prompt 2",
                ),
            ],
        ),
    ]

    test_tool = MockImageGenerationTool(responses=test_responses)

    # Act
    result = _image_generation_core(test_run_context, prompt, shape, test_tool)  # type: ignore[arg-type]

    # Assert
    assert isinstance(result, list)
    assert len(result) == 2

    # Check first generated image
    assert isinstance(result[0], GeneratedImage)
    assert result[0].file_id == "file_id_1"
    assert result[0].revised_prompt == "Revised: test image prompt"

    # Check second generated image
    assert isinstance(result[1], GeneratedImage)
    assert result[1].file_id == "file_id_2"
    assert (
        result[1].url == "http://frontend/file_id_1"
    )  # Mock returns same URL for all calls
    assert result[1].revised_prompt == "Revised: test image prompt 2"

    # Verify context was updated
    assert test_run_context.context.current_run_step == 2
    assert (
        len(test_run_context.context.aggregated_context.global_iteration_responses) == 1
    )

    # Check iteration answer
    answer = test_run_context.context.aggregated_context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == "image_generation_tool"
    assert answer.tool_id == 2
    assert answer.iteration_nr == 1
    assert answer.question == prompt
    assert answer.generated_images == result

    # Check iteration instructions
    assert len(test_run_context.context.iteration_instructions) == 1
    instructions = test_run_context.context.iteration_instructions[0]
    assert isinstance(instructions, IterationInstructions)
    assert instructions.purpose == "Generating images"

    # Verify emitter events were captured
    emitter = test_run_context.context.run_dependencies.emitter
    assert len(emitter.packet_history) == 4

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, ImageGenerationToolStart)
    assert isinstance(emitter.packet_history[1].obj, ImageGenerationToolHeartbeat)
    assert isinstance(emitter.packet_history[2].obj, ImageGenerationToolDelta)
    assert isinstance(emitter.packet_history[3].obj, SectionEnd)

    # Verify save_files was called correctly
    mock_save_files.assert_called_once_with(
        urls=["https://example.com/image1.jpg"],
        base64_files=["base64_image_data"],
    )

    # Verify build_frontend_file_url was called for the second image
    mock_build_frontend_file_url.assert_called_with("file_id_2")


def test_image_generation_core_exception_handling() -> None:
    """Test that _image_generation_core handles exceptions properly"""
    # Arrange
    test_run_context = create_test_run_context()
    prompt = "test image prompt"
    shape = "landscape"

    # Create a tool that will raise an exception
    test_tool = MockImageGenerationTool(should_raise_exception=True)

    # Act & Assert
    with pytest.raises(Exception, match="Test exception from image generation tool"):
        _image_generation_core(test_run_context, prompt, shape, test_tool)  # type: ignore[arg-type]

    # Verify that even though an exception was raised, we still emitted the initial events
    # and the SectionEnd packet was emitted by the decorator
    emitter = test_run_context.context.run_dependencies.emitter
    assert len(emitter.packet_history) == 2

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, ImageGenerationToolStart)
    assert isinstance(emitter.packet_history[1].obj, SectionEnd)

    # Verify that the decorator properly handled the exception and updated current_run_step
    assert test_run_context.context.current_run_step == 2


@patch("onyx.tools.tool_implementations_v2.image_generation.save_files")
@patch("onyx.tools.tool_implementations_v2.image_generation.build_frontend_file_url")
def test_image_generation_core_different_shapes(
    mock_build_frontend_file_url: Mock, mock_save_files: Mock
) -> None:
    """Test _image_generation_core with different shapes"""
    # Arrange
    test_run_context = create_test_run_context()
    prompt = "test image prompt"

    # Mock file operations
    mock_save_files.return_value = ["file_id_1"]
    mock_build_frontend_file_url.return_value = "http://frontend/file_id_1"

    # Create test responses
    test_responses = [
        Mock(
            id="image_generation_response",
            response=[
                ImageGenerationResponse(
                    url="https://example.com/image1.jpg",
                    image_data=None,
                    revised_prompt="Revised: test image prompt",
                ),
            ],
        ),
    ]

    # Test with different shapes
    for shape in ["square", "portrait", "landscape"]:
        test_run_context = create_test_run_context()
        # Create a fresh mock for each test to avoid call history issues
        fresh_test_tool = MockImageGenerationTool(responses=test_responses)
        result = _image_generation_core(
            test_run_context, prompt, shape, fresh_test_tool  # type: ignore[arg-type]
        )

        assert len(result) == 1
        assert isinstance(result[0], GeneratedImage)

        # Check iteration instructions were created
        assert len(test_run_context.context.iteration_instructions) == 1
        instructions = test_run_context.context.iteration_instructions[0]
        assert isinstance(instructions, IterationInstructions)
        assert instructions.purpose == "Generating images"

        # Check iteration answer was created
        assert (
            len(test_run_context.context.aggregated_context.global_iteration_responses)
            == 1
        )
        answer = test_run_context.context.aggregated_context.global_iteration_responses[
            0
        ]
        assert isinstance(answer, IterationAnswer)
        assert answer.tool == "image_generation_tool"

        # Verify the tool was called with the correct shape argument
        assert fresh_test_tool.run.called
        call_args = fresh_test_tool.run.call_args
        if shape != "square":
            assert call_args[1]["shape"] == shape
        else:
            # Square is default, so shape shouldn't be in kwargs
            assert "shape" not in call_args[1]


@patch("onyx.tools.tool_implementations_v2.image_generation.save_files")
@patch("onyx.tools.tool_implementations_v2.image_generation.build_frontend_file_url")
def test_image_generation_core_empty_response(
    mock_build_frontend_file_url: Mock, mock_save_files: Mock
) -> None:
    """Test _image_generation_core with empty tool responses"""
    # Arrange
    test_run_context = create_test_run_context()
    prompt = "test image prompt"
    shape = "square"

    # Create empty responses
    test_tool = MockImageGenerationTool(responses=[])

    # Act & Assert
    _image_generation_core(test_run_context, prompt, shape, test_tool)  # type: ignore[arg-type]

    emitter = test_run_context.context.run_dependencies.emitter
    assert len(emitter.packet_history) > 0


@patch("onyx.tools.tool_implementations_v2.image_generation.save_files")
@patch("onyx.tools.tool_implementations_v2.image_generation.build_frontend_file_url")
def test_image_generation_core_handles_cancellation_gracefully(
    mock_build_frontend_file_url: Mock, mock_save_files: Mock
) -> None:
    """Test that _image_generation_core handles cancellation gracefully without erroring"""
    # Arrange
    # Create a redis client that indicates the session is cancelled
    redis_client = MockRedisClient(is_cancelled=True)
    test_run_context = create_test_run_context(redis_client=redis_client)
    prompt = "test image prompt"
    shape = "square"

    # Create test responses with some heartbeats and a response
    # (but the response should never be processed due to cancellation check)
    test_responses = [
        Mock(
            id="image_generation_heartbeat",
            response=None,
        ),
        Mock(
            id="image_generation_response",
            response=[
                ImageGenerationResponse(
                    url="https://example.com/image1.jpg",
                    image_data=None,
                    revised_prompt="Revised: test image prompt",
                ),
            ],
        ),
    ]

    test_tool = MockImageGenerationTool(responses=test_responses)

    # Act - This should NOT raise an exception when cancelled gracefully
    result = _image_generation_core(test_run_context, prompt, shape, test_tool)  # type: ignore[arg-type]

    # Assert - When cancelled gracefully, we should get an empty list or appropriate response
    # The implementation should handle cancellation without throwing RuntimeError
    assert isinstance(result, list)
    # Could be empty list or have some sentinel value
    # The key is that no exception should be raised

    # Verify emitter events - should have start and section end at minimum
    emitter = test_run_context.context.run_dependencies.emitter
    assert len(emitter.packet_history) >= 2

    # Check that we emitted at least the start event
    assert isinstance(emitter.packet_history[0].obj, ImageGenerationToolStart)

    # The last event should be SectionEnd (added by decorator)
    assert isinstance(emitter.packet_history[-1].obj, SectionEnd)

    # Verify that the decorator properly handled the flow and updated current_run_step
    assert test_run_context.context.current_run_step == 2
