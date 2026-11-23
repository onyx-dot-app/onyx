"""The file sentence of internal search results in a chat without a sandbox:
a result names its file only when the chat stages it for the Python tool."""

import json
from collections.abc import Iterator, Mapping
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat import agent as agent_module
from onyx.chat.models import AnswerStreamPart
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.model_response import Delta
from onyx.server.features.build.sandbox.harness_base import search_file_name
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseStart,
    Packet,
    SearchToolDocumentsDelta,
)
from onyx.tools.constants import PYTHON_TOOL_NAME
from onyx.tools.models import ChatFile, SearchResult, SearchResults
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.utils import FILE_ASSOCIATED_GUIDANCE
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
    final_answer,
)
from tests.external_dependency_unit.code_mode_helpers import (
    ChatLLM,
    last_tool_text,
    send,
    tool_step,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.mock_search_pipeline import (
    MockInternalSearchResult,
    use_mock_search_pipeline,
)

pytestmark = pytest.mark.usefixtures(
    "full_deployment_setup", "mock_external_deps", "default_llm_provider"
)

TITLE = "Q2 revenue.csv"
EXCERPT = "region,revenue"
# The next chunk of the document: a result without the sentence shows both.
REST = "west,10"


@pytest.fixture
def stored_files() -> Iterator[list[str]]:
    file_ids: list[str] = []
    yield file_ids
    for file_id in file_ids:
        get_default_file_store().delete_file(file_id, error_on_missing=False)


def _stored_file(stored_files: list[str], origin: FileOrigin | None) -> str:
    """A connector file with `origin`; None: an ID the file store lacks."""
    if origin is None:
        return f"missing-{uuid4().hex}"
    file_id = get_default_file_store().save_file(
        content=BytesIO(b"region,revenue\nwest,10\n"),
        display_name=TITLE,
        file_origin=origin,
        file_type="text/csv",
    )
    stored_files.append(file_id)
    return file_id


def _chat_searches(
    db_session: Session,
    make_test_user: MakeTestUser,
    searches: list[list[MockInternalSearchResult]],
    *,
    python_tool: bool,
) -> tuple[list[SearchResult], list[ChatFile], list[AnswerStreamPart]]:
    """Run one search step for each entry of `searches` in a new chat; the
    results that the model gets, in order, the files that the chat stages for
    the Python tool, and the streamed parts."""
    user = make_test_user("search_file_sentence")
    session = create_chat_session(db_session, user)
    llm = ChatLLM(
        [
            *(
                tool_step(SearchTool.NAME, f"found-{index}", {"queries": [f"q{index}"]})
                for index in range(len(searches))
            ),
            Delta(content="Revenue grew."),
        ]
    )
    staged: list[ChatFile] = []
    stage_files = agent_module.build_python_chat_files_from_search_docs

    def stage(file_names: Mapping[str, str]) -> list[ChatFile]:
        files = stage_files(file_names)
        staged.extend(files)
        return files

    with (
        patch.object(agent_module, "build_python_chat_files_from_search_docs", stage),
        use_mock_search_pipeline([DocumentSource.GOOGLE_DRIVE]) as internal,
        # The mocked pipeline has no Document rows; keep the chunk's file.
        patch(
            "onyx.tools.tool_implementations.search.search_tool.populate_file_ids_on_sections"
        ),
        patch.object(
            PythonTool, "is_available", classmethod(lambda _cls, _db: python_tool)
        ),
    ):
        for index, results in enumerate(searches):
            internal.add_search_results(f"q{index}", results)
        parts = send(
            session.id, user, llm, "How did Q2 revenue change?", code_mode=False
        )
    assert final_answer(parts) == "Revenue grew."
    offered = {tool["function"]["name"] for tool in llm.requests[0]["tools"]}
    assert (PYTHON_TOOL_NAME in offered) == python_tool
    results = [
        result
        for index in range(len(searches))
        for result in SearchResults.model_validate(
            json.loads(last_tool_text(llm, f"found-{index}"))
        ).results
    ]
    return results, staged, parts


def _search_result(
    db_session: Session,
    make_test_user: MakeTestUser,
    stored_files: list[str],
    *,
    origin: FileOrigin | None,
    python_tool: bool,
) -> tuple[str, SearchResult, list[str]]:
    """Search in a new chat for a document whose file has `origin` (None: the
    file store has no such file); the file's ID, the result the model gets,
    and the file IDs that the chat stages for the Python tool. The streamed
    documents keep the file's ID whatever the chat does with it."""
    file_id = _stored_file(stored_files, origin)
    [result], staged, parts = _chat_searches(
        db_session,
        make_test_user,
        [
            [
                MockInternalSearchResult(
                    document_id="q2",
                    source_type=DocumentSource.GOOGLE_DRIVE,
                    semantic_identifier=TITLE,
                    chunk_ind=index,
                    content=content,
                    file_id=file_id,
                )
                for index, content in enumerate((EXCERPT, REST))
            ]
        ],
        python_tool=python_tool,
    )
    # The search's documents and the answer's documents.
    streamed = [
        document.file_id
        for part in parts
        if isinstance(part, Packet)
        for document in (
            part.obj.documents
            if isinstance(part.obj, SearchToolDocumentsDelta)
            else part.obj.final_documents or []
            if isinstance(part.obj, AgentResponseStart)
            else []
        )
    ]
    assert streamed and set(streamed) == {file_id}
    return file_id, result, [file.file_id for file in staged if file.file_id]


def test_a_chat_without_the_python_tool_names_no_file(
    db_session: Session, make_test_user: MakeTestUser, stored_files: list[str]
) -> None:
    _, result, staged = _search_result(
        db_session,
        make_test_user,
        stored_files,
        origin=FileOrigin.CONNECTOR,
        python_tool=False,
    )
    assert result.file_name is None
    assert result.content == f"{EXCERPT}\n{REST}"
    assert staged == []


@pytest.mark.parametrize(
    "origin", [FileOrigin.CONNECTOR, FileOrigin.CONNECTOR_FILE_UPLOAD]
)
def test_a_chat_with_the_python_tool_names_the_staged_file(
    db_session: Session,
    make_test_user: MakeTestUser,
    stored_files: list[str],
    origin: FileOrigin,
) -> None:
    file_id, result, staged = _search_result(
        db_session,
        make_test_user,
        stored_files,
        origin=origin,
        python_tool=True,
    )
    name = search_file_name(file_id, TITLE)
    assert result.file_name == name
    assert result.content == FILE_ASSOCIATED_GUIDANCE.format(
        filename=name, content=EXCERPT
    )
    assert staged == [file_id]


@pytest.mark.parametrize("origin", [FileOrigin.CHAT_UPLOAD, None])
def test_a_file_that_python_does_not_stage_gets_no_sentence(
    db_session: Session,
    make_test_user: MakeTestUser,
    stored_files: list[str],
    origin: FileOrigin | None,
) -> None:
    """Another origin's file, or one that the file store no longer has."""
    _, result, staged = _search_result(
        db_session,
        make_test_user,
        stored_files,
        origin=origin,
        python_tool=True,
    )
    assert result.file_name is None
    assert result.content == f"{EXCERPT}\n{REST}"
    assert staged == []


def test_a_result_without_a_title_names_the_staged_file(
    db_session: Session, make_test_user: MakeTestUser, stored_files: list[str]
) -> None:
    file_id = _stored_file(stored_files, FileOrigin.CONNECTOR)
    [result], staged, _ = _chat_searches(
        db_session,
        make_test_user,
        [
            [
                MockInternalSearchResult(
                    document_id="untitled",
                    source_type=DocumentSource.GOOGLE_DRIVE,
                    semantic_identifier="",
                    chunk_ind=0,
                    content=EXCERPT,
                    file_id=file_id,
                )
            ]
        ],
        python_tool=True,
    )
    assert [(file.file_id, file.filename) for file in staged] == [
        (file_id, result.file_name)
    ]


def test_documents_that_share_a_file_name_the_staged_file(
    db_session: Session, make_test_user: MakeTestUser, stored_files: list[str]
) -> None:
    """Two documents with different titles have one file; the searches that
    show it name it as the chat staged it."""
    file_id = _stored_file(stored_files, FileOrigin.CONNECTOR)
    results, staged, _ = _chat_searches(
        db_session,
        make_test_user,
        [
            [
                MockInternalSearchResult(
                    document_id=document_id,
                    source_type=DocumentSource.GOOGLE_DRIVE,
                    semantic_identifier=title,
                    chunk_ind=0,
                    content=EXCERPT,
                    file_id=file_id,
                )
            ]
            for document_id, title in (("first", "First.csv"), ("second", "Second.csv"))
        ],
        python_tool=True,
    )
    [file] = staged
    assert file.file_id == file_id
    assert [result.file_name for result in results] == [file.filename] * 2
