"""Code mode results cite, stage, save and reload like the search tools they call."""

import re
from collections.abc import Iterator, Sequence
from io import BytesIO
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.context.search.models import InferenceChunk
from onyx.file_store.postgres_file_store import PostgresBackedFileStore
from onyx.llm.model_request import ChatCompletionMessage, SystemMessage
from onyx.llm.model_response import (
    Delta,
)
from onyx.prompts.chat_prompts import REQUIRE_CITATION_GUIDANCE
from onyx.prompts.tool_prompts import (
    CODE_MODE_GUIDANCE,
    CODE_MODE_SEARCH_USAGE,
    INTERNAL_SEARCH_GUIDANCE,
    TOOL_DESCRIPTION_SEARCH_GUIDANCE,
)
from onyx.server.query_and_chat.chat_backend import get_chat_session
from onyx.server.query_and_chat.streaming_models import (
    CitationInfo,
    CodeModeDelta,
    Packet,
    SearchToolDocumentsDelta,
)
from onyx.tools.tool_implementations.search.constants import MAX_QUERIES_PER_CALL
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
    final_answer,
)
from tests.external_dependency_unit.code_mode_helpers import (
    ChatLLM,
    code_step,
    send,
    tool_text,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.mock_search_pipeline import (
    MockInternalSearchResult,
    use_mock_search_pipeline,
)
from tests.external_dependency_unit.mock_search_provider import (
    MockWebSearchResult,
    use_mock_web_provider,
)

pytestmark = pytest.mark.usefixtures("full_deployment_setup", "mock_external_deps")


class FileSearchResult(MockInternalSearchResult):
    """An internal search result for a connector document with a stored file."""

    file_id: str

    def to_inference_chunk(self) -> InferenceChunk:
        return super().to_inference_chunk().model_copy(update={"file_id": self.file_id})


def _citations(parts: Sequence[object]) -> list[tuple[int, str]]:
    return [
        (packet.obj.citation_number, packet.obj.document_id)
        for packet in parts
        if isinstance(packet, Packet) and isinstance(packet.obj, CitationInfo)
    ]


def _documents(parts: Sequence[object]) -> list[str]:
    return [
        doc.document_id
        for packet in parts
        if isinstance(packet, Packet)
        and isinstance(packet.obj, SearchToolDocumentsDelta)
        for doc in packet.obj.documents
    ]


@pytest.fixture
def connector_file() -> Iterator[tuple[PostgresBackedFileStore, str]]:
    """A connector file in Postgres, so the test needs no object store."""
    file_store = PostgresBackedFileStore()
    file_id = file_store.save_file(
        content=BytesIO(b"region,revenue\nwest,10\n"),
        display_name="q2.csv",
        file_origin=FileOrigin.CONNECTOR,
        file_type="text/csv",
    )
    yield file_store, file_id
    file_store.delete_file(file_id)


@pytest.mark.usefixtures("default_llm_provider")
def test_code_mode_citations_stream_save_reload_and_continue(
    db_session: Session,
    make_test_user: MakeTestUser,
    connector_file: tuple[PostgresBackedFileStore, str],
) -> None:
    user = make_test_user("code_mode_citations")
    session = create_chat_session(db_session, user)
    file_store, file_id = connector_file
    internal_doc = "GOOGLE_DRIVE_q2"

    # Turn 1: a program searches, a later program reads the staged file, and the
    # answer cites the search result.
    first = ChatLLM(
        [
            code_step(
                "search",
                "r = await internal_search(queries=['Q2 revenue'])\n"
                "for doc in r['results']:\n"
                "    print(doc['document'], doc['title'])\n"
                "store('k', 1)\n",
            ),
            code_step(
                "python",
                "out = await run_python(code=\"import os\\nprint(os.listdir('.'))\")\n"
                "print(out)\n"
                "await internal_search(queries=['Q2 costs'])\n",
            ),
            Delta(content="Revenue grew [1]."),
        ]
    )
    with (
        patch("onyx.chat.files.get_default_file_store", return_value=file_store),
        patch(
            "onyx.tools.tool_implementations.python.python_tool.get_default_file_store",
            return_value=file_store,
        ),
        use_mock_search_pipeline([DocumentSource.GOOGLE_DRIVE]) as internal,
        # The mocked pipeline has no Document rows; keep the chunk's file.
        patch(
            "onyx.tools.tool_implementations.search.search_tool.populate_file_ids_on_sections"
        ),
        patch(
            "onyx.tools.tool_implementations.search.search_tool.semantic_query_rephrase",
            return_value="",
        ) as rephrase,
    ):
        internal.add_search_results(
            "Q2 revenue",
            [
                FileSearchResult(
                    document_id="q2",
                    source_type=DocumentSource.GOOGLE_DRIVE,
                    semantic_identifier="Q2 revenue",
                    chunk_ind=0,
                    file_id=file_id,
                )
            ],
        )
        parts = send(session.id, user, first, "How did Q2 revenue change?")
    assert final_answer(parts).startswith("Revenue grew")
    # The prompt keeps the guidance of the tools inside programs.
    system = "\n".join(
        message.content
        for message in first.requests[0]["prompt"]
        if isinstance(message, SystemMessage)
    )
    assert CODE_MODE_GUIDANCE in system
    assert INTERNAL_SEARCH_GUIDANCE in system
    assert TOOL_DESCRIPTION_SEARCH_GUIDANCE in system
    # The real search tool's stub asks for one call per information need.
    [description] = [
        tool["function"]["description"]
        for tool in first.requests[0]["tools"]
        if tool["function"]["name"] == "execute_code"
    ]
    assert CODE_MODE_SEARCH_USAGE in description
    # The tool's own query limit reaches its stub.
    assert f"List of up to {MAX_QUERIES_PER_CALL} search queries" in description
    assert "Output:\n1 Q2 revenue" in tool_text(first.requests[1]["prompt"], "search")
    # The searched document's file reaches the next program's Python tool.
    assert f"Q2 revenue_{file_id}" in tool_text(first.requests[2]["prompt"], "python")
    # The chat knows a program searched, so the next search reuses its expansion.
    assert rephrase.call_count == 1
    assert _citations(parts) == [(1, internal_doc)]
    assert _documents(parts) == [internal_doc]
    # A result with citations asks the model to cite.
    assert any(
        REQUIRE_CITATION_GUIDANCE.strip() in str(message.content)
        for message in first.requests[1]["prompt"]
    )

    detail = get_chat_session(session_id=session.id, user=user, db_session=db_session)
    [answer] = [m for m in detail.messages if m.message_type == "assistant"]
    assert answer.citations is not None
    assert list(answer.citations) == [1]
    assert [doc.document_id for doc in answer.context_docs or []] == [internal_doc]
    [replayed] = detail.packets
    assert _documents(replayed) == [internal_doc]
    assert _citations(replayed) == [(1, internal_doc)]
    # Replay shows the saved output and store keys of each program.
    finals = [
        packet.obj
        for packet in replayed
        if isinstance(packet.obj, CodeModeDelta) and packet.obj.status is not None
    ]
    [search_program, python_program] = finals
    assert (search_program.stdout, search_program.stored_keys) == (
        "1 Q2 revenue\n",
        ["k"],
    )
    assert python_program.status == "completed"
    assert python_program.stored_keys is None
    assert f"Q2 revenue_{file_id}" in (python_program.stdout or "")

    # Turn 2: a new search gets numbers after the saved ones, and the answer can
    # cite both turns.
    def cite_both(prompt: list[ChatCompletionMessage]) -> Delta:
        [number] = re.findall(r"Output:\n(\d+)", tool_text(prompt, "web"))
        return Delta(content=f"Both [1] and [{number}].")

    second = ChatLLM(
        [
            code_step(
                "web",
                "r = await web_search(queries=['beta topic'])\n"
                "print(r['results'][0]['document'])\n",
            ),
            cite_both,
        ]
    )
    with use_mock_web_provider(db_session) as web:
        web.add_results(
            "beta topic",
            [
                MockWebSearchResult(
                    title="Beta page",
                    link="https://example.com/beta",
                    snippet="About beta.",
                )
            ],
        )
        parts = send(session.id, user, second, "And the web?")
    citations = _citations(parts)
    assert citations[0] == (1, internal_doc)
    [(number, web_doc)] = citations[1:]
    assert number != 1
    assert web_doc == "WEB_SEARCH_DOC_https://example.com/beta"
    assert final_answer(parts).startswith("Both")

    detail = get_chat_session(session_id=session.id, user=user, db_session=db_session)
    assert _citations(detail.packets[1]) == citations
    assert _documents(detail.packets[1]) == [web_doc]
