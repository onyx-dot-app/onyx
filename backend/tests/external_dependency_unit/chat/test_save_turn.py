from datetime import datetime

from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.models import LlmDoc
from onyx.chat.turn.save_turn import save_turn
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import ResearchAgentIteration
from onyx.db.models import ResearchAgentIterationSubStep
from onyx.db.models import User
from tests.external_dependency_unit.conftest import create_test_user


def create_inference_section(
    document_id: str,
    chunk_id: int,
    content: str,
    source_link: str,
    source_type: DocumentSource = DocumentSource.WEB,
) -> InferenceSection:
    """Helper to create an InferenceSection for testing."""
    chunk = InferenceChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        semantic_identifier=f"{document_id}_{chunk_id}",
        title=f"Title {document_id}",
        blurb=content[:100],
        content=content,
        source_links={0: source_link},
        section_continuation=False,
        source_type=source_type,
        boost=0,
        recency_bias=1.0,
        score=1.0,
        hidden=False,
        metadata={},
        match_highlights=[],
        updated_at=datetime.now(),
        image_file_id=None,
        doc_summary="",
        chunk_context="",
    )
    return InferenceSection(
        combined_content=content,
        center_chunk=chunk,
        chunks=[],
    )


def test_save_turn_with_single_citation(
    db_session: Session,
    tenant_context: None,
) -> None:
    """
    Test that save_turn correctly saves only the cited document to the citations field,
    even when multiple documents are fetched.

    The test uses a final answer with citation in format [[1]](https://example.com)
    and verifies only that citation is extracted and saved.

    Validates:
    - Only the cited document appears in citations field
    - ChatMessage is created with correct data
    - ResearchAgentIteration is created
    - ResearchAgentIterationSubStep is created
    """
    # Create test user
    test_user: User = create_test_user(db_session, email_prefix="save_turn_test")

    # Create chat session
    chat_session: ChatSession = create_chat_session(
        db_session=db_session,
        description="Test save_turn",
        user_id=test_user.id,
        persona_id=0,
    )

    # Get root message
    root_message = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )

    # Create user message
    user_message: ChatMessage = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=root_message,
        message="Test query",
        token_count=5,
        message_type=MessageType.USER,
        db_session=db_session,
        commit=True,
    )

    # Create assistant message (this is what we'll update with save_turn)
    assistant_message: ChatMessage = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=user_message,
        message="",  # Will be filled by save_turn
        token_count=0,  # Will be updated by save_turn
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
        commit=True,
    )

    # Create multiple inference sections (fetched documents)
    inference_section_1 = create_inference_section(
        document_id="doc1",
        chunk_id=0,
        content="This is the first document with important information.",
        source_link="https://example.com/doc1",
    )
    inference_section_2 = create_inference_section(
        document_id="doc2",
        chunk_id=0,
        content="This is the second document with other information.",
        source_link="https://example.com/doc2",
    )
    inference_section_3 = create_inference_section(
        document_id="doc3",
        chunk_id=0,
        content="This is the third document with more information.",
        source_link="https://example.com/doc3",
    )

    # Create ordered fetched documents (with citation numbers assigned)
    ordered_fetched_documents = [
        LlmDoc(
            document_id="doc1",
            content="This is the first document with important information.",
            blurb="This is the first document...",
            semantic_identifier="doc1_0",
            source_type=DocumentSource.WEB,
            metadata={},
            updated_at=None,
            link="https://example.com/doc1",
            source_links={0: "https://example.com/doc1"},
            match_highlights=[],
            document_citation_number=1,  # This document gets citation number 1
        ),
        LlmDoc(
            document_id="doc2",
            content="This is the second document with other information.",
            blurb="This is the second document...",
            semantic_identifier="doc2_0",
            source_type=DocumentSource.WEB,
            metadata={},
            updated_at=None,
            link="https://example.com/doc2",
            source_links={0: "https://example.com/doc2"},
            match_highlights=[],
            document_citation_number=2,
        ),
        LlmDoc(
            document_id="doc3",
            content="This is the third document with more information.",
            blurb="This is the third document...",
            semantic_identifier="doc3_0",
            source_type=DocumentSource.WEB,
            metadata={},
            updated_at=None,
            link="https://example.com/doc3",
            source_links={0: "https://example.com/doc3"},
            match_highlights=[],
            document_citation_number=3,
        ),
    ]

    # Create final answer with only citation [[1]](url)
    final_answer = "Based on the research, here's what I found [[1]](https://example.com/doc1). This is the answer."

    # Create iteration instructions
    iteration_instructions = [
        IterationInstructions(
            reasoning="Need to search for information",
            purpose="Find relevant documents",
            plan="Search for relevant documents using web search",
            iteration_nr=0,
        )
    ]

    # Create iteration responses
    global_iteration_responses = [
        IterationAnswer(
            tool="search",
            tool_id=1,
            iteration_nr=0,
            parallelization_nr=0,
            question="What is the relevant information?",
            answer="Found relevant information in documents",
            reasoning="Searched and found matches",
            claims=["Claim 1", "Claim 2"],
            cited_documents={},
            is_web_fetch=False,
        )
    ]

    # Call save_turn
    save_turn(
        db_session=db_session,
        message_id=assistant_message.id,
        chat_session_id=chat_session.id,
        research_type=ResearchType.FAST,
        final_answer=final_answer,
        unordered_fetched_inference_sections=[
            inference_section_1,
            inference_section_2,
            inference_section_3,
        ],
        ordered_fetched_documents=ordered_fetched_documents,
        iteration_instructions=iteration_instructions,
        global_iteration_responses=global_iteration_responses,
        model_name="gpt-4o",
        model_provider="openai",
    )

    # Refresh the assistant message to get updated data
    db_session.refresh(assistant_message)

    # Assertions
    # 1. Verify the message content was updated
    assert assistant_message.message == final_answer
    assert assistant_message.token_count > 0

    # 2. Verify only citation [[1]] is in the citations field
    # Note: citations are stored with string keys in JSONB (PostgreSQL converts int keys to strings)
    assert assistant_message.citations is not None
    assert len(assistant_message.citations) == 1
    assert "1" in assistant_message.citations  # type: ignore  # Citation number 1 should be present
    assert "2" not in assistant_message.citations  # type: ignore  # Citation 2 should NOT be present
    assert "3" not in assistant_message.citations  # type: ignore  # Citation 3 should NOT be present

    # 3. Verify research type and purpose
    assert assistant_message.research_type == ResearchType.FAST
    assert assistant_message.research_answer_purpose == ResearchAnswerPurpose.ANSWER

    # 4. Verify ResearchAgentIteration was created
    iterations = (
        db_session.query(ResearchAgentIteration)
        .filter(ResearchAgentIteration.primary_question_id == assistant_message.id)
        .all()
    )
    assert len(iterations) == 1
    iteration = iterations[0]
    assert iteration.reasoning == "Need to search for information"
    assert iteration.purpose == "Find relevant documents"
    assert iteration.iteration_nr == 0

    # 5. Verify ResearchAgentIterationSubStep was created
    sub_steps = (
        db_session.query(ResearchAgentIterationSubStep)
        .filter(
            ResearchAgentIterationSubStep.primary_question_id == assistant_message.id
        )
        .all()
    )
    assert len(sub_steps) == 1
    sub_step = sub_steps[0]
    assert sub_step.iteration_nr == 0
    assert sub_step.iteration_sub_step_nr == 0
    assert sub_step.sub_step_instructions == "What is the relevant information?"
    assert sub_step.sub_answer == "Found relevant information in documents"
    assert sub_step.reasoning == "Searched and found matches"
    assert sub_step.claims == ["Claim 1", "Claim 2"]

    # 6. Verify all 3 documents are associated with the message via search_docs
    assert len(assistant_message.search_docs) == 3
    doc_ids = {doc.document_id for doc in assistant_message.search_docs}
    assert doc_ids == {"doc1", "doc2", "doc3"}
