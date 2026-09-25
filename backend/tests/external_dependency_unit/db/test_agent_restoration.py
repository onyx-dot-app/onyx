"""A new request restores registered research conversations and their source references."""

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.agents.compaction import history_digest
from onyx.agents.coordination import AgentCoordinator
from onyx.agents.items import (
    build_response_items,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.agents.transcript import (
    OperationSnapshot,
    RunStatus,
)
from onyx.chat.models import MessageRendering, ResponseRecord
from onyx.chat.prompt_utils import prepare_prompt
from onyx.chat.subagents import create_chat_agent_coordinator
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import create_db_search_doc
from onyx.db.chat_history import (
    capture_chat_history,
    convert_chat_history,
)
from onyx.db.chat_response import save_response_content
from onyx.db.chat_subagents import (
    load_agent_history,
    load_session_agent_metadata,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatMessage, ChatSession
from onyx.deep_research.models import ResearchConfiguration
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.chat_prompts import TOOL_CALL_RESPONSE_CROSS_MESSAGE
from tests.unit.onyx.agents.fakes import FakeModelClient


def test_research_restores_across_request_contexts(db_session: Session) -> None:
    session = ChatSession(id=uuid4(), description="restored research")
    db_session.add(session)
    db_session.flush()
    question = ChatMessage(
        chat_session_id=session.id,
        message="Investigate cedar",
        token_count=3,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.flush()
    previous = ChatMessage(
        parent_message_id=question.id,
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(previous)
    db_session.flush()
    continuation = ChatMessage(
        chat_session_id=session.id,
        parent_message_id=previous.id,
        message="Continue",
        token_count=1,
        message_type=MessageType.USER,
    )
    db_session.add(continuation)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=session.id,
        parent_message_id=continuation.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.flush()
    root_id = str(session.id)
    agent_id, first_run = (str(uuid4()) for _ in range(2))
    source = SearchDoc(
        document_id="source",
        chunk_ind=0,
        semantic_identifier="Source",
        blurb="Evidence",
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    document = create_db_search_doc(source, db_session, commit=False)
    previous.search_docs.append(document)
    settings = ResearchConfiguration(
        language_section="",
        reasoning_effort=ReasoningEffort.LOW,
    )
    run_id = str(uuid4())
    transcript = ResponseRecord(
        run_id=run_id,
        agent_id=root_id,
        input_messages=[UserMessage(content="Investigate cedar")],
        status=RunStatus.COMPLETE,
        items=build_response_items(
            run_id,
            [
                AssistantMessage(
                    content=[ToolCall(id="delegate", name="delegate", arguments={})]
                )
            ],
            [
                OperationSnapshot(
                    step_index=0, message_index=0, status=RunStatus.COMPLETE
                )
            ],
            answer_message_index=None,
        ),
        child_runs=[
            ResponseRecord(
                run_id=first_run,
                agent_id=agent_id,
                agent_path="/root/research",
                agent_description="Check evidence",
                restoration_config=settings,
                status=RunStatus.COMPLETE,
                input_messages=[UserMessage(content="Investigate cedar")],
                items=build_response_items(
                    first_run,
                    [
                        AssistantMessage(
                            content=[TextContent(text="Cedar evidence [1].")]
                        )
                    ],
                    [
                        OperationSnapshot(
                            step_index=0, message_index=0, status=RunStatus.COMPLETE
                        )
                    ],
                    answer_message_index=None,
                ),
            )
        ],
    )
    transcript.child_runs[0].parent_run_id = transcript.run_id
    transcript.child_runs[0].parent_message_id = f"{transcript.run_id}:0"
    transcript.child_runs[0].parent_tool_call_id = "delegate"
    save_response_content(
        previous,
        transcript,
        db_session=db_session,
        persist_content=True,
        presentation={
            transcript.child_runs[0].items[0].id: MessageRendering(
                citation_documents={1: "source"}
            )
        },
    )
    db_session.commit()
    response_id, session_id, previous_id = response.id, session.id, previous.id
    db_session.expunge_all()
    requests: list[GenerationRequest] = []

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        return AssistantMessage(
            content=[TextContent(text="Additional cedar evidence [1].")]
        )

    research_llm = FakeModelClient(generate)
    root_replies = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="reuse", name="reuse", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="Done")]),
        ]
    )

    saved_run_id: str

    def reuse(invocation: ToolInvocation) -> ToolResult:
        historical = invocation.agents.wait_run(saved_run_id, timeout=2)
        assert (
            historical is not None and historical.output.text == "Cedar evidence [1]."
        )
        run_id = invocation.agents.start_run(
            agent_id,
            messages=[UserMessage(content="Check the evidence again")],
            max_steps=1,
        )
        assert run_id != saved_run_id
        result = invocation.agents.wait_run(run_id, timeout=5)
        assert (
            result is not None
            and result.output.text == "Additional cedar evidence [1]."
        )
        return ToolResult(content=result.output.text)

    root = Agent(
        FakeModelClient(lambda *_: next(root_replies)),
        tools=[
            AgentTool(
                name="reuse",
                description="Read saved research",
                parameters={},
                execute=reuse,
            )
        ],
    )
    coordinator: AgentCoordinator | None = None
    try:
        saved_child = load_agent_history(response_id, agent_id)
        assert saved_child.sources[1].document_id == "source"
        persisted_run_id = saved_child.previous_run_id
        assert persisted_run_id is not None
        saved_run_id = persisted_run_id
        coordinator = create_chat_agent_coordinator(
            root,
            message_id=response_id,
            chat_session_id=session_id,
            persist_content=True,
            previous_run_id=str(previous_id),
            llm=research_llm,
            tools=[],
            user_identity=LLMUserIdentity(),
        )
        assert root.id == root_id
        assert (
            root.start(
                background=False,
                max_steps=2,
                messages=[UserMessage(content="Continue")],
                coordinator=coordinator,
            )
            .result()
            .output.text
            == "Done"
        )
        assert len(requests) == 1
        assert any(
            "Investigate cedar" in message.text for message in requests[0].messages
        )
        assert any(
            "Cedar evidence [1]." in message.text for message in requests[0].messages
        )
        assert any(
            "Check the evidence again" in message.text
            for message in requests[0].messages
        )
        assert coordinator.close(timeout=10)
        continued = load_agent_history(response_id, agent_id)
        assert continued.previous_run_id != saved_run_id
        assert any(
            message.text == "Additional cedar evidence [1]."
            for message in continued.messages
        )
    finally:
        if coordinator is not None:
            assert coordinator.close(timeout=10)
        db_session.execute(
            delete(ChatMessage).where(ChatMessage.chat_session_id == session_id)
        )
        db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
        db_session.delete(db_session.merge(document))
        db_session.commit()


def test_incognito_does_not_persist_child_conversations(db_session: Session) -> None:
    session = ChatSession(
        id=uuid4(),
        description="private",
        incognito_record_mode=IncognitoRecordMode.USAGE_ONLY,
    )
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(message)
    db_session.commit()
    try:
        metadata = load_session_agent_metadata(message.id)
        assert [agent.id for agent in metadata] == [str(session.id)]
        assert metadata[0].restoration_config is None
        assert (
            db_session.scalar(
                select(ChatSession)
                .join(ChatMessage, ChatSession.spawned_by_message_id == ChatMessage.id)
                .where(ChatMessage.chat_session_id == session.id)
            )
            is None
        )
    finally:
        db_session.delete(message)
        db_session.delete(session)
        db_session.commit()


def test_saved_tools_filter_at_request_boundary(db_session: Session) -> None:
    session = ChatSession(id=uuid4(), description="History context")
    db_session.add(session)
    db_session.flush()
    question = ChatMessage(
        chat_session_id=session.id,
        message="Find evidence",
        token_count=2,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=session.id,
        parent_message_id=question.id,
        message="Answer",
        token_count=1,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.flush()
    image_content = '[{"file_id":"image","revised_prompt":"Evidence chart"}]'
    run_id = str(uuid4())
    transcript = ResponseRecord(
        run_id=run_id,
        agent_id=str(session.id),
        status=RunStatus.COMPLETE,
        input_messages=[UserMessage(content=question.message)],
        items=build_response_items(
            run_id,
            [
                AssistantMessage(
                    content=[
                        ToolCall(id="search", name="web_search", arguments={}),
                        ToolCall(id="image", name="generate_image", arguments={}),
                    ]
                ),
                ToolResultMessage(
                    tool_call_id="search",
                    tool_name="web_search",
                    content="Stored evidence",
                ),
                ToolResultMessage(
                    tool_call_id="image",
                    tool_name="generate_image",
                    content=image_content,
                ),
                AssistantMessage(content=[TextContent(text="Answer")]),
            ],
            [
                OperationSnapshot(
                    step_index=0, message_index=0, status=RunStatus.COMPLETE
                ),
                OperationSnapshot(
                    step_index=1, message_index=3, status=RunStatus.COMPLETE
                ),
            ],
            answer_message_index=3,
        ),
    )
    session_id, question_id, response_id = session.id, question.id, response.id
    try:
        save_response_content(
            response, transcript, db_session=db_session, persist_content=True
        )
        db_session.commit()
        db_session.expunge_all()
        saved_question = db_session.get(ChatMessage, question_id)
        saved_response = db_session.get(ChatMessage, response_id)
        assert saved_question is not None and saved_response is not None
        history = convert_chat_history(
            capture_chat_history([saved_question, saved_response], {}, len),
            files=[],
            context_image_files=[],
            additional_context=None,
            token_counter=len,
        ).messages
        original_digest = history_digest(history)
        history.append(UserMessage(content="Next question"))
        request = prepare_prompt(
            history,
            system_prompt=None,
            custom_agent_prompt=None,
            reminder_message=None,
            context_files=None,
            token_counter=len,
        )
        assert [m.text for m in request if isinstance(m, ToolResultMessage)] == [
            TOOL_CALL_RESPONSE_CROSS_MESSAGE,
            image_content,
        ]
        assert [m.text for m in history if isinstance(m, ToolResultMessage)] == [
            "Stored evidence",
            image_content,
        ]
        assert history_digest(history[:-1]) == original_digest
    finally:
        db_session.rollback()
        db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
        db_session.commit()
