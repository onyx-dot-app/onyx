"""A new request restores registered research conversations and their source references."""

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.agents.transcript import (
    AgentConfiguration,
    AgentTranscript,
    OperationSnapshot,
    RunStatus,
)
from onyx.chat.agent_registry import bind_chat_agents
from onyx.chat.models import MessagePresentation
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.agent_transcript import (
    get_or_create_root_agent,
    load_agent_history,
    load_session_agent_metadata,
    set_agent_transcript,
)
from onyx.db.chat import create_db_search_doc
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatMessage, ChatSession, ChatSessionAgent
from onyx.deep_research.research_agent import ResearchConfiguration
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResult,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient


def test_research_restores_across_request_contexts(db_session: Session) -> None:
    session = ChatSession(id=uuid4(), description="restored research")
    db_session.add(session)
    db_session.flush()
    previous = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(previous)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=session.id,
        parent_message_id=previous.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.flush()
    root_id, agent_id, first_run = (str(uuid4()) for _ in range(3))
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
    transcript = AgentTranscript(
        run_id=str(uuid4()),
        agent_id=root_id,
        status=RunStatus.COMPLETE,
        messages=[],
        child_runs=[
            AgentTranscript(
                run_id=first_run,
                agent_id=agent_id,
                agent_path="/root/research",
                agent_description="Check evidence",
                restoration_config=AgentConfiguration(
                    feature="research", settings=settings.model_dump(mode="json")
                ),
                status=RunStatus.COMPLETE,
                operations=[
                    OperationSnapshot(
                        step_index=0, message_index=0, status=RunStatus.COMPLETE
                    )
                ],
                input_messages=[UserMessage(content="Investigate cedar")],
                messages=[
                    AssistantMessage(content=[TextContent(text="Cedar evidence [1].")])
                ],
            )
        ],
    )
    db_session.add(
        ChatSessionAgent(id=root_id, chat_session_id=session.id, name="root")
    )
    db_session.flush()
    set_agent_transcript(
        previous,
        transcript,
        db_session=db_session,
        persist_content=True,
        presentation=[
            MessagePresentation(
                run_id=first_run, step_index=0, citation_documents={1: "source"}
            )
        ],
    )
    db_session.commit()
    response_id, session_id = response.id, session.id
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

    async def reuse(invocation: ToolInvocation) -> ToolResult:
        historical = await invocation.agents.wait_run(first_run, timeout=2)
        assert (
            historical is not None and historical.output.text == "Cedar evidence [1]."
        )
        run_id = await invocation.agents.start_run(
            agent_id,
            messages=[UserMessage(content="Check the evidence again")],
            max_steps=1,
        )
        assert run_id != first_run
        result = await invocation.agents.wait_run(run_id, timeout=5)
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
                execute_async=reuse,
            )
        ],
    )
    try:
        saved_child = load_agent_history(response_id, agent_id)
        assert saved_child.sources[1].document_id == "source"
        bind_chat_agents(
            root,
            message_id=response_id,
            chat_session_id=session_id,
            persist_content=True,
            previous_run_id=transcript.run_id,
            llm=research_llm,
            tools=[],
            user_identity=LLMUserIdentity(),
        )
        assert root.id == root_id
        assert (
            root.run(
                max_steps=2, messages=[UserMessage(content="Continue")]
            ).output.text
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
        assert (
            load_agent_history(response_id, agent_id).transcripts[0].run_id == first_run
        )
    finally:
        db_session.execute(
            delete(ChatMessage).where(ChatMessage.chat_session_id == session_id)
        )
        db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
        db_session.delete(db_session.merge(document))
        db_session.commit()


def test_incognito_root_is_not_persisted(db_session: Session) -> None:
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
        agent_id = str(uuid4())
        assert get_or_create_root_agent(message.id, agent_id) == agent_id
        assert load_session_agent_metadata(message.id) == []
        assert (
            db_session.scalar(
                select(ChatSessionAgent).where(
                    ChatSessionAgent.chat_session_id == session.id
                )
            )
            is None
        )
    finally:
        db_session.delete(message)
        db_session.delete(session)
        db_session.commit()
