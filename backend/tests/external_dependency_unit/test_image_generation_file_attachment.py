"""
External dependency unit test for image generation file attachment.
This test verifies that generated image file IDs are properly attached to chat messages in the database.
"""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import GeneratedImage
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.configs.constants import MessageType
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import ChatSession
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.file_store.models import ChatFileType
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def test_user(db_session: Session) -> User:
    """Create a test user."""
    return create_test_user(db_session, "test_image")


@pytest.fixture
def test_persona(db_session: Session) -> Persona:
    """Create a test persona."""
    from onyx.context.search.enums import RecencyBiasSetting

    persona = Persona(
        name="Test Persona",
        description="Test persona for image generation",
        num_chunks=10.0,
        chunks_above=0,
        chunks_below=0,
        llm_relevance_filter=False,
        llm_filter_extraction=False,
        recency_bias=RecencyBiasSetting.AUTO,
        llm_model_provider_override=None,
        llm_model_version_override=None,
        starter_messages=None,
        is_visible=True,
        builtin_persona=False,
        system_prompt="You are a helpful assistant.",
        task_prompt="Answer the user's question.",
    )
    db_session.add(persona)
    db_session.commit()
    return persona


@pytest.fixture
def test_chat_session(
    db_session: Session, test_user: User, test_persona: Persona
) -> ChatSession:
    """Create a test chat session."""
    chat_session = ChatSession(
        user_id=test_user.id,
        persona_id=test_persona.id,
        description="Test chat session for image generation",
    )
    db_session.add(chat_session)
    db_session.commit()
    return chat_session


def test_image_generation_file_attachment(
    db_session: Session,
    test_user: User,
    test_chat_session: ChatSession,
) -> None:
    """
    Test that generated image file IDs are properly attached to chat messages.

    This test:
    1. Creates a user message
    2. Simulates the fast_chat_turn flow with pre-populated iteration answers containing generated images
    3. Verifies that the assistant message has the image files attached
    """
    # Create root message
    root_message = get_or_create_root_message(
        chat_session_id=test_chat_session.id, db_session=db_session
    )

    # Create a user message
    user_message = create_new_chat_message(
        chat_session_id=test_chat_session.id,
        parent_message=root_message,
        message="Generate an image of a sunset",
        token_count=10,
        message_type=MessageType.USER,
        db_session=db_session,
        commit=True,
    )

    # Create mock generated images as they would appear after image generation
    test_file_id_1 = str(uuid4())
    test_file_id_2 = str(uuid4())

    generated_images = [
        GeneratedImage(
            file_id=test_file_id_1,
            url=f"http://example.com/image/{test_file_id_1}",
            revised_prompt="A beautiful sunset over the ocean",
        ),
        GeneratedImage(
            file_id=test_file_id_2,
            url=f"http://example.com/image/{test_file_id_2}",
            revised_prompt="A beautiful sunset over the mountains",
        ),
    ]

    # Create an iteration answer with generated images (as would be created by image_generation tool)
    iteration_answer = IterationAnswer(
        tool="generate_image",
        tool_id=1,  # Mock tool ID
        iteration_nr=0,
        parallelization_nr=0,
        question="Generate an image of a sunset",
        answer="",
        reasoning="",
        claims=[],
        generated_images=generated_images,
        additional_data={},
        response_type=None,
        data=None,
        file_ids=None,
        cited_documents={},
    )

    # Now we need to test the session_sink.save_iteration function
    # We'll call it directly to verify it saves files correctly
    from onyx.chat.turn.infra.session_sink import save_iteration
    from onyx.chat.turn.models import ChatTurnContext
    from unittest.mock import Mock

    # Create a mock context with the iteration answer
    from onyx.agents.agent_search.dr.models import IterationInstructions

    mock_ctx = Mock(spec=ChatTurnContext)
    mock_ctx.aggregated_context = AggregatedDRContext(
        context="",
        cited_documents=[],
        is_internet_marker_dict={},
        global_iteration_responses=[iteration_answer],
    )
    mock_ctx.iteration_instructions = [
        IterationInstructions(
            iteration_nr=0,
            plan="Generate an image",
            purpose="Image generation",
            reasoning="To create a visual representation",
        )
    ]

    # Mock the dependencies
    mock_dependencies = Mock()
    mock_llm = Mock()
    mock_llm.config.model_name = "gpt-4"
    mock_llm.config.model_provider = "openai"
    mock_dependencies.llm = mock_llm
    mock_ctx.run_dependencies = mock_dependencies

    # Reserve a message id for the assistant response
    from onyx.db.chat import reserve_message_id

    assistant_message_id = reserve_message_id(
        db_session=db_session,
        chat_session_id=test_chat_session.id,
        parent_message=user_message.id,
        message_type=MessageType.ASSISTANT,
    )

    # Call save_iteration which should attach the image files
    save_iteration(
        db_session=db_session,
        message_id=assistant_message_id,
        chat_session_id=test_chat_session.id,
        research_type=ResearchType.THOUGHTFUL,
        ctx=mock_ctx,
        final_answer="",
        all_cited_documents=[],
    )

    # Retrieve the assistant message from the database
    assistant_message = get_chat_message(
        chat_message_id=assistant_message_id,
        user_id=test_user.id,
        db_session=db_session,
    )

    # Verify that the assistant message has files attached
    assert assistant_message is not None, "Assistant message should exist"
    assert assistant_message.files is not None, "Assistant message should have files"
    assert len(assistant_message.files) == 2, "Should have 2 image files attached"

    # Verify the file descriptors have the correct structure
    file_ids = [file["id"] for file in assistant_message.files]
    assert (
        test_file_id_1 in file_ids
    ), "First generated image file ID should be attached"
    assert (
        test_file_id_2 in file_ids
    ), "Second generated image file ID should be attached"

    # Verify the file type
    for file in assistant_message.files:
        assert file["type"] == ChatFileType.IMAGE.value, "File type should be 'image'"


if __name__ == "__main__":
    # Run with: python -m pytest tests/external_dependency_unit/test_image_generation_file_attachment.py -v -s
    pytest.main([__file__, "-v", "-s"])
