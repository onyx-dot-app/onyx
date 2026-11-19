"""The renderer's packets for a postgres_query call: the start packet carries
the query for the step's summary, and listed documents stream for citations."""

from onyx.agents.models import (
    ExecutionStatus,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.chat.models import ResponseRecord, ToolReplayData
from onyx.chat.presentation import replay_response
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.models import AssistantMessage, ToolCall, ToolResultMessage
from onyx.server.query_and_chat.streaming_models import (
    PostgresToolDocuments,
    PostgresToolStart,
)
from onyx.tools.constants import POSTGRES_TOOL_NAME


def test_replayed_query_step_carries_its_query_and_documents() -> None:
    document = SearchDoc(
        document_id="jira-1",
        chunk_ind=0,
        semantic_identifier="Ticket",
        blurb="",
        source_type=DocumentSource.JIRA,
        score=0.0,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    arguments = {
        "table": "document",
        "source_type": "jira",
        "updated_after": "2026-02-01",
        "limit": 100,
    }
    response = ResponseRecord(
        run_id="root",
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=AssistantMessage(
                    id="root-message",
                    content=[
                        ToolCall(
                            id="query", name=POSTGRES_TOOL_NAME, arguments=arguments
                        )
                    ],
                ),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    "query": ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            tool_call_id="query",
                            tool_name=POSTGRES_TOOL_NAME,
                            content="1 matching documents:",
                            details=SearchDocsResponse(
                                search_docs=[], citation_mapping={1: "jira-1"}
                            ),
                        ),
                    )
                },
            )
        ],
    )
    packets = replay_response(
        response,
        {("root-message", "query"): ToolReplayData(tool_id=1, search_docs=[document])},
        {},
        {"jira-1": document},
    )

    starts = [p.obj for p in packets if isinstance(p.obj, PostgresToolStart)]
    assert [start.query for start in starts] == [arguments]
    documents = [p.obj for p in packets if isinstance(p.obj, PostgresToolDocuments)]
    assert [doc.document_id for d in documents for doc in d.documents] == ["jira-1"]
