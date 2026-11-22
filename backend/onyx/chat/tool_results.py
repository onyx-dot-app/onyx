"""The contract of tool results that carry documents.

Each function here handles every result type that carries documents: how to read
its sources, its saved form, its restored form, and the type that stages its
files. Callers do not branch on result types; a new type changes only this module.
"""

from collections.abc import Callable, Mapping, Sequence
from functools import partial

from pydantic import BaseModel

from onyx.chat.citation_processor import cited_documents
from onyx.chat.models import (
    ChatCodeModeResult,
    ChatSearchResult,
    ResultSources,
    StagedChatFiles,
)
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.llm.models import ToolResultMessage
from onyx.tools.models import ChatFile
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeExecutionResult,
)
from onyx.utils.pydantic_util import as_base, shallow_model_dump


def _by_id(documents: Sequence[SearchDoc]) -> dict[str, SearchDoc]:
    """Documents by id; the first of a repeated id wins."""
    found: dict[str, SearchDoc] = {}
    for document in documents:
        found.setdefault(document.document_id, document)
    return found


def _search_sources(searches: Sequence[SearchDocsResponse]) -> ResultSources:
    """The documents and citations of one or more searches, merged in order.

    Each search shows its `displayed_docs`, or all its documents when it has no
    selection; an empty selection shows none.
    """
    documents = _by_id(
        [
            document
            for search in searches
            for document in [*search.search_docs, *(search.displayed_docs or [])]
        ]
    )
    displayed = _by_id(
        [
            document
            for search in searches
            for document in (
                search.displayed_docs
                if search.displayed_docs is not None
                else search.search_docs
            )
        ]
    )
    mapping = {
        number: document_id
        for search in searches
        for number, document_id in search.citation_mapping.items()
    }
    return ResultSources(
        documents=list(documents.values()),
        displayed=list(displayed.values()),
        citations=cited_documents(dict(sorted(mapping.items())), documents),
    )


def tool_result_sources(details: BaseModel | None) -> ResultSources | None:
    """The documents and citations of any tool result; None if it carries none."""
    if isinstance(details, ResearchAgentCallResult):
        return ResultSources(
            documents=list(details.citation_mapping.values()),
            displayed=None,
            citations=dict(details.citation_mapping),
        )
    if isinstance(details, SearchDocsResponse):
        return _search_sources([details])
    if isinstance(details, CodeModeExecutionResult):
        # The nested searches of every window, the closing record's included.
        return _search_sources(
            [
                call.details
                for call in details.all_calls()
                if isinstance(call.details, SearchDocsResponse)
            ]
        )
    return None


def saved_result_details(details: BaseModel | None) -> BaseModel | None:
    """The form of a result that a saved response keeps.

    Documents are saved through the tool call relation, so search results keep
    only their citation numbers. Staged files stay in execution state.
    """
    if isinstance(details, SearchDocsResponse):
        return as_base(details, SearchDocsResponse).model_copy(
            update={
                "search_docs": [],
                "displayed_docs": [] if details.displayed_docs == [] else None,
            }
        )
    if isinstance(details, CodeModeExecutionResult):
        return as_base(details, CodeModeExecutionResult).map_calls(_saved_call)
    return details


def _saved_call(call: CodeModeCall) -> CodeModeCall:
    """A nested call in its saved form; it keeps the ids of the documents that
    its search displayed. Planning metadata applies to the current turn, as for
    direct calls."""
    details = call.details
    displayed = (
        _search_sources([details]).displayed
        if isinstance(details, SearchDocsResponse)
        else None
    )
    return call.model_copy(
        update={
            "details": saved_result_details(details),
            "metadata": None,
            "displayed_document_ids": None
            if displayed is None
            else [doc.document_id for doc in displayed],
        }
    )


def restored_result_details[T: BaseModel](
    details: T, documents: Mapping[str, SearchDoc]
) -> T:
    """Refill the documents that a saved result keeps only as citation numbers.

    Each cited document comes back once, in citation order.
    """
    if isinstance(details, SearchDocsResponse):
        cited = cited_documents(details.citation_mapping, documents)
        return details.model_copy(
            update={"search_docs": list(_by_id(list(cited.values())).values())}
        )
    if isinstance(details, CodeModeExecutionResult):
        return details.map_calls(partial(_restored_call, documents=documents))
    return details


def _restored_call(
    call: CodeModeCall, documents: Mapping[str, SearchDoc]
) -> CodeModeCall:
    if call.details is None:
        return call
    details = restored_result_details(call.details, documents)
    ids = call.displayed_document_ids
    if isinstance(details, SearchDocsResponse) and ids is not None:
        details = details.model_copy(
            update={
                "displayed_docs": [documents[key] for key in ids if key in documents]
            }
        )
    return call.model_copy(update={"details": details})


def staged_result_details(
    details: BaseModel | None,
    known_file_ids: set[str],
    read_files: Callable[[list[SearchDoc]], list[ChatFile]],
) -> BaseModel | None:
    """The result with the files of its documents staged for later Python calls.

    `read_files` reads the files of documents. Files that the result already
    stages, or that are in `known_file_ids`, are not read again.
    """
    staged_type: type[StagedChatFiles]
    if isinstance(details, SearchDocsResponse):
        staged_type = ChatSearchResult
    elif isinstance(details, CodeModeExecutionResult):
        staged_type = ChatCodeModeResult
    else:
        return details
    sources = tool_result_sources(details)
    staged = list(details.staged_files) if isinstance(details, StagedChatFiles) else []
    staged_ids = {file.file_id for file in staged}
    added = [
        doc
        for doc in (sources.documents if sources is not None else [])
        if doc.file_id not in staged_ids and doc.file_id not in known_file_ids
    ]
    if isinstance(details, StagedChatFiles) and not added:
        return details
    staged.extend(read_files(added))
    fields = shallow_model_dump(details)
    fields.pop("staged_files", None)
    return staged_type(**fields, staged_files=staged)


def merged_chat_files(
    chat_files: Sequence[ChatFile], added: Sequence[ChatFile]
) -> list[ChatFile]:
    """`chat_files`, then the `added` files with a filename not yet present."""
    names = {file.filename for file in chat_files}
    return [*chat_files, *(file for file in added if file.filename not in names)]


def tool_result_parts(result: ToolResultMessage) -> list[ToolResultMessage]:
    """The result, then a result for each tool call that it made."""
    details = result.details
    if not isinstance(details, CodeModeExecutionResult):
        return [result]
    return [
        result,
        *(call.as_result() for call in details.all_calls()),
    ]
