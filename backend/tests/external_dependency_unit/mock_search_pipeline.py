from collections.abc import Callable
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchDoc
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex
from onyx.llm.interfaces import LLM


def run_functions_tuples_sequential(
    functions_with_args: list[tuple[Callable, tuple]],
    allow_failures: bool = False,
    max_workers: int | None = None,  # noqa: ARG001
    timeout: float | None = None,  # noqa: ARG001
    timeout_callback: Callable | None = None,  # noqa: ARG001
) -> list[Any]:
    """
    A sequential replacement for run_functions_tuples_in_parallel.
    Useful in tests to make parallel tool calls deterministic.
    """
    results = []
    for func, args in functions_with_args:
        try:
            results.append(func(*args))
        except Exception:
            if allow_failures:
                results.append(None)
            else:
                raise
    return results


class MockInternalSearchResult(BaseModel):
    document_id: str
    source_type: DocumentSource
    semantic_identifier: str
    chunk_ind: int

    def to_inference_chunk(self) -> InferenceChunk:
        return InferenceChunk(
            document_id=f"{self.source_type.value.upper()}_{self.document_id}",
            source_type=self.source_type,
            semantic_identifier=self.semantic_identifier,
            title=self.semantic_identifier,
            chunk_id=self.chunk_ind,
            blurb="",
            content="",
            source_links=None,
            image_file_id=None,
            section_continuation=False,
            boost=0,
            score=1.0,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary="",
            chunk_context="",
            updated_at=None,
        )

    def to_search_doc(self) -> SearchDoc:
        return SearchDoc(
            document_id=f"{self.source_type.value.upper()}_{self.document_id}",
            chunk_ind=self.chunk_ind,
            semantic_identifier=self.semantic_identifier,
            link=None,
            blurb="",
            source_type=self.source_type,
            boost=0,
            hidden=False,
            metadata={},
            score=1.0,
            match_highlights=[],
            updated_at=None,
        )


class SearchPipelineController:
    def __init__(self) -> None:
        self.search_results: dict[str, list[MockInternalSearchResult]] = {}

    def add_search_results(
        self, query: str, results: list[MockInternalSearchResult]
    ) -> None:
        self.search_results[query] = results

    def get_search_results(self, query: str) -> list[InferenceChunk]:
        return [
            result.to_inference_chunk() for result in self.search_results.get(query, [])
        ]


@contextmanager
def use_mock_search_pipeline(
    connectors: list[DocumentSource],
) -> Generator[SearchPipelineController, None, None]:
    """Mock the search pipeline and connector availability.

    Args:
        connectors: List of DocumentSource types to pretend are available.
                   Pass an empty list to simulate no connectors.
    """
    controller = SearchPipelineController()

    def mock_check_connectors_exist(db_session: Session) -> bool:  # noqa: ARG001
        return len(connectors) > 0

    def mock_check_federated_connectors_exist(
        db_session: Session,  # noqa: ARG001
    ) -> bool:
        # For now, federated connectors are not mocked as available
        return False

    def mock_check_user_files_exist(db_session: Session) -> bool:  # noqa: ARG001
        # For now, user files are not mocked as available
        return False

    def mock_fetch_unique_document_sources(
        db_session: Session,  # noqa: ARG001
    ) -> list[DocumentSource]:
        return connectors

    def override_search_pipeline(
        chunk_search_request: ChunkSearchRequest,
        document_index: DocumentIndex,  # noqa: ARG001
        user: User | None,  # noqa: ARG001
        persona: Persona | None,  # noqa: ARG001
        db_session: Session,  # noqa: ARG001
        auto_detect_filters: bool = False,  # noqa: ARG001
        llm: LLM | None = None,  # noqa: ARG001
        project_id: int | None = None,  # noqa: ARG001
    ) -> list[InferenceChunk]:
        return controller.get_search_results(chunk_search_request.query)

    with (
        patch(
            "onyx.tools.tool_implementations.search.search_tool.search_pipeline",
            new=override_search_pipeline,
        ),
        patch(
            "onyx.tools.tool_implementations.search.search_tool.check_connectors_exist",
            new=mock_check_connectors_exist,
        ),
        patch(
            "onyx.tools.tool_implementations.search.search_tool.check_federated_connectors_exist",
            new=mock_check_federated_connectors_exist,
        ),
        patch(
            "onyx.tools.tool_implementations.search.search_tool.semantic_query_rephrase",
            return_value="",
        ),
        patch(
            "onyx.tools.tool_implementations.search.search_tool.keyword_query_expansion",
            return_value=[],
        ),
        patch(
            "onyx.tools.tool_runner.run_functions_tuples_in_parallel",
            new=run_functions_tuples_sequential,
        ),
        patch(
            "onyx.db.connector.check_connectors_exist",
            new=mock_check_connectors_exist,
        ),
        patch(
            "onyx.db.connector.check_federated_connectors_exist",
            new=mock_check_federated_connectors_exist,
        ),
        patch(
            "onyx.db.connector.check_user_files_exist",
            new=mock_check_user_files_exist,
        ),
        patch(
            "onyx.db.connector.fetch_unique_document_sources",
            new=mock_fetch_unique_document_sources,
        ),
    ):
        yield controller
