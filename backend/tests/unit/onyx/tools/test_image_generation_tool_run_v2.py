"""Tests for ImageGenerationTool.run_v2() using dependency injection.

This test module focuses on testing the ImageGenerationTool.run_v2() method directly,
using dependency injection via creating fake implementations instead of using mocks.
"""

from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import GeneratedImage
from onyx.chat.models import PromptConfig
from onyx.chat.turn.models import ChatTurnContext
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from tests.unit.onyx.chat.turn.utils import FakeRedis


# =============================================================================
# Fake Classes for Dependency Injection
# =============================================================================


def create_fake_database_session() -> Any:
    """Create a fake SQLAlchemy Session for testing"""
    from unittest.mock import Mock
    from sqlalchemy.orm import Session

    # Create a mock that behaves like a real Session
    fake_session = Mock(spec=Session)
    fake_session.committed = False
    fake_session.rolled_back = False

    def mock_commit() -> None:
        fake_session.committed = True

    def mock_rollback() -> None:
        fake_session.rolled_back = True

    fake_session.commit = mock_commit
    fake_session.rollback = mock_rollback
    fake_session.add = Mock()
    fake_session.flush = Mock()

    return fake_session


class FakeEmitter:
    """Fake emitter for testing that records all emitted packets"""

    def __init__(self) -> None:
        self.packet_history: list[Any] = []

    def emit(self, packet: Any) -> None:
        self.packet_history.append(packet)


class FakeRunDependencies:
    """Fake run dependencies for testing"""

    def __init__(
        self,
        db_session: Any,
        redis_client: FakeRedis,
        image_generation_tool: ImageGenerationTool,
    ) -> None:
        self.db_session = db_session
        self.redis_client = redis_client
        self.emitter = FakeEmitter()
        self.tools = [image_generation_tool]

    def get_prompt_config(self) -> PromptConfig:
        return PromptConfig(
            default_behavior_system_prompt="You are a helpful assistant.",
            reminder="Answer the user's question.",
            custom_instructions="",
            datetime_aware=False,
        )


class FakeCancelledRedis(FakeRedis):
    """Fake Redis client that always reports the session as cancelled."""

    def exists(self, key: str) -> bool:  # pragma: no cover - trivial override
        return True


# =============================================================================
# Test Helper Functions
# =============================================================================


def create_fake_image_generation_tool(tool_id: int = 1) -> ImageGenerationTool:
    """Create an ImageGenerationTool instance for testing"""
    return ImageGenerationTool(
        api_key="fake-api-key",
        api_base=None,
        api_version=None,
        tool_id=tool_id,
        model="dall-e-3",
        num_imgs=1,
    )


def create_fake_run_context(
    chat_session_id: UUID,
    message_id: int,
    db_session: Any,
    redis_client: FakeRedis,
    image_generation_tool: ImageGenerationTool,
) -> RunContextWrapper[ChatTurnContext]:
    """Create a fake run context for testing"""
    run_dependencies = FakeRunDependencies(
        db_session, redis_client, image_generation_tool
    )

    context = ChatTurnContext(
        chat_session_id=chat_session_id,
        message_id=message_id,
        run_dependencies=run_dependencies,  # type: ignore
    )

    return RunContextWrapper(context=context)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def chat_session_id() -> UUID:
    """Fixture providing fake chat session ID."""
    return uuid4()


@pytest.fixture
def message_id() -> int:
    """Fixture providing fake message ID."""
    return 123


@pytest.fixture
def research_type() -> ResearchType:
    """Fixture providing fake research type."""
    return ResearchType.FAST


@pytest.fixture
def fake_db_session() -> Any:
    """Fixture providing a fake database session."""
    return create_fake_database_session()


@pytest.fixture
def fake_redis_client() -> FakeRedis:
    """Fixture providing a fake Redis client."""
    return FakeRedis()


@pytest.fixture
def image_generation_tool() -> ImageGenerationTool:
    """Fixture providing an ImageGenerationTool with fake API credentials."""
    return create_fake_image_generation_tool()


@pytest.fixture
def fake_run_context(
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
    image_generation_tool: ImageGenerationTool,
) -> RunContextWrapper[ChatTurnContext]:
    """Fixture providing a complete RunContextWrapper with fake implementations."""
    return create_fake_run_context(
        chat_session_id,
        message_id,
        fake_db_session,
        fake_redis_client,
        image_generation_tool,
    )


# =============================================================================
# Test Functions
# =============================================================================


def test_image_generation_tool_run_v2_basic_functionality(
    fake_run_context: RunContextWrapper[ChatTurnContext],
    image_generation_tool: ImageGenerationTool,
) -> None:
    """Test basic functionality of ImageGenerationTool.run_v2() using dependency injection.

    This test verifies that the run_v2 method properly integrates with the v2 implementation.
    """
    from unittest.mock import patch

    # Arrange
    prompt = "A beautiful sunset over mountains"
    shape = "landscape"

    # Create fake generated images
    fake_generated_images = [
        GeneratedImage(
            file_id="file-123",
            url="https://example.com/files/file-123",
            revised_prompt="A stunning sunset over mountains with vibrant colors",
        )
    ]

    # Mock the core implementation
    with patch.object(image_generation_tool, "_image_generation_core") as mock_core:
        mock_core.return_value = fake_generated_images

        # Act
        result = image_generation_tool.run_v2(
            fake_run_context, prompt=prompt, shape=shape
        )

    # Assert - verify result is a success message
    assert isinstance(result, str)
    assert "Successfully generated 1 images" in result

    # Verify the core was called with correct parameters
    mock_core.assert_called_once()
    call_args = mock_core.call_args
    # When patching a bound method, self is bound; first arg is run_context
    assert call_args[0][0] == fake_run_context  # run_context
    assert call_args[0][1] == prompt  # prompt
    assert call_args[0][2] == shape  # shape


def test_image_generation_tool_run_v2_missing_prompt(
    fake_run_context: RunContextWrapper[ChatTurnContext],
    image_generation_tool: ImageGenerationTool,
) -> None:
    """Test that run_v2 raises ValueError when prompt is missing."""
    # Act & Assert
    with pytest.raises(ValueError) as exc_info:
        image_generation_tool.run_v2(fake_run_context)

    assert "prompt is required" in str(exc_info.value)


def test_image_generation_tool_run_v2_default_shape(
    fake_run_context: RunContextWrapper[ChatTurnContext],
    image_generation_tool: ImageGenerationTool,
) -> None:
    """Test that run_v2 uses default shape when not provided."""
    from unittest.mock import patch

    # Arrange
    prompt = "A cat playing with yarn"
    fake_generated_images = [
        GeneratedImage(
            file_id="file-456",
            url="https://example.com/files/file-456",
            revised_prompt="A playful cat playing with colorful yarn",
        )
    ]

    # Mock the core implementation
    with patch.object(image_generation_tool, "_image_generation_core") as mock_core:
        mock_core.return_value = fake_generated_images

        # Act - don't provide shape parameter
        image_generation_tool.run_v2(fake_run_context, prompt=prompt)

    # Assert - verify default shape was used
    call_args = mock_core.call_args
    assert call_args[0][2] == "square"  # default shape


def test_image_generation_tool_run_v2_multiple_images(
    fake_run_context: RunContextWrapper[ChatTurnContext],
) -> None:
    """Test that run_v2 handles multiple images correctly."""
    from unittest.mock import patch

    # Arrange
    # Create tool that generates multiple images
    multi_image_tool = ImageGenerationTool(
        api_key="fake-api-key",
        api_base=None,
        api_version=None,
        tool_id=1,
        model="dall-e-3",
        num_imgs=3,
    )

    # Update run dependencies to include the multi-image tool
    fake_run_context.context.run_dependencies.tools = [multi_image_tool]

    prompt = "A series of abstract patterns"
    fake_generated_images = [
        GeneratedImage(
            file_id=f"file-{i}",
            url=f"https://example.com/files/file-{i}",
            revised_prompt=f"Abstract pattern variation {i}",
        )
        for i in range(3)
    ]

    # Mock the core implementation
    with patch.object(multi_image_tool, "_image_generation_core") as mock_core:
        mock_core.return_value = fake_generated_images

        # Act
        result = multi_image_tool.run_v2(fake_run_context, prompt=prompt)

    # Assert
    assert "Successfully generated 3 images" in result


def test_image_generation_tool_run_v2_handles_cancellation_gracefully(
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    image_generation_tool: ImageGenerationTool,
) -> None:
    """Test that run_v2 handles cancellation gracefully without calling external APIs."""
    from unittest.mock import patch

    # Arrange - create a run context with a Redis client that always reports cancellation
    cancelled_run_context = create_fake_run_context(
        chat_session_id=chat_session_id,
        message_id=message_id,
        db_session=fake_db_session,
        redis_client=FakeCancelledRedis(),
        image_generation_tool=image_generation_tool,
    )

    prompt = "A test image prompt that should be cancelled"

    # Patch the tool's run method so it does NOT call the real image API.
    def fake_run(**kwargs: Any) -> Any:
        # Yield a single fake ToolResponse; it will be ignored because of cancellation.
        yield ToolResponse(id="ignored", response=None)

    with patch.object(image_generation_tool, "run", side_effect=fake_run) as mock_run:
        # Act - this should not raise, and should not call external APIs
        result = image_generation_tool.run_v2(
            cancelled_run_context,
            prompt=prompt,
        )

    # Assert - when cancelled gracefully, the tool should report zero generated images
    assert isinstance(result, str)
    assert "Successfully generated 0 images" in result

    # Verify we invoked the patched run exactly once with the expected prompt
    mock_run.assert_called_once()
