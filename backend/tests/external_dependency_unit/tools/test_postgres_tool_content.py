"""Tests for postgres_query's document content filter, with real Postgres and
a test OpenSearch index.

Both ways of matching (Postgres first, OpenSearch first) must list the same
documents in the same order, apply the Postgres filters and both copies of the
permissions, and page with cursors that keep their way.
"""

import base64
import json
import re
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from pydantic import JsonValue
from sqlalchemy.orm import Session

from onyx.access.models import DocumentAccess
from onyx.agents.tools import ToolInvocation
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.db.enums import HierarchyNodeType, VectorQuantization
from onyx.db.models import (
    ConnectorCredentialPair,
    DocumentByConnectorCredentialPair,
    HierarchyNode,
)
from onyx.db.models import Document as DbDocument
from onyx.db.postgres_tool import public_cc_pair_ids_for_sources
from onyx.db.postgres_tool_models import DocumentScope
from onyx.document_index.interfaces import (
    IndexingMetadata,
    MetadataUpdateRequest,
    TenantState,
)
from onyx.document_index.opensearch.client import wait_for_opensearch_with_timeout
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.models import ChunkEmbedding, DocMetadataAwareIndexChunk
from onyx.kg.models import KGStage
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.postgres import content, postgres_tool
from onyx.tools.tool_implementations.postgres.postgres_tool import PostgresTool
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_EMBEDDING_DIM = 16
_PHRASE = "quick brown"
_PUBLIC = DocumentAccess.build([], [], [], [], is_public=True)
_PRIVATE = DocumentAccess.build(["someone-else@example.com"], [], [], [], False)


@dataclass
class _Doc:
    key: str
    days_ago: int
    text: str
    access: DocumentAccess = _PUBLIC
    hidden: bool = False


# Expected matches, newest first: fox, dog, owl.
_DOCS = [
    _Doc("fox", 1, "the quick brown fox"),
    _Doc("dog", 2, "a quick brown dog"),
    # The words, but not the phrase.
    _Doc("words", 3, "brown and quick"),
    # Public in Postgres but not to this user in OpenSearch.
    _Doc("private", 4, "a quick brown cat", access=_PRIVATE),
    _Doc("hidden", 4, "a quick brown bird", hidden=True),
    _Doc("owl", 5, "a quick brown owl"),
]


@dataclass
class ContentEnv:
    tag: str
    tool: PostgresTool
    ids: dict[str, str]
    cc_pair_id: int


def _chunk(
    doc_id: str, doc: _Doc, updated: datetime, cc_pair_id: int
) -> DocMetadataAwareIndexChunk:
    return DocMetadataAwareIndexChunk(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        access=doc.access,
        cc_pair_ids={cc_pair_id},
        document_sets=set(),
        user_project=[],
        personas=[],
        boost=0,
        aggregated_chunk_boost_factor=0,
        ancestor_hierarchy_node_ids=[],
        embeddings=ChunkEmbedding(
            full_embedding=[1.0] + [0.0] * (_EMBEDDING_DIM - 1),
            mini_chunk_embeddings=[],
        ),
        source_document=Document(
            id=doc_id,
            semantic_identifier=doc_id,
            source=DocumentSource.WEB,
            sections=[],
            metadata={},
            doc_updated_at=updated,
        ),
        title_prefix="",
        metadata_suffix_keyword="",
        metadata_suffix_semantic="",
        contextual_rag_reserved_tokens=0,
        doc_summary="",
        chunk_context="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        chunk_id=0,
        blurb=doc.text,
        content=doc.text,
        source_links={0: ""},
        image_file_id=None,
        section_continuation=False,
    )


@pytest.fixture(scope="module")
def opensearch_index() -> Generator[OpenSearchDocumentIndex, None, None]:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    index = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=f"test_pgtool_content_{uuid.uuid4().hex[:8]}",
        embedding_dim=_EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    index.verify_and_create_index_if_necessary(embedding_dim=_EMBEDDING_DIM)
    try:
        yield index
    finally:
        index._client.delete_index()


@pytest.fixture()
def content_env(
    db_session: Session,
    make_test_user: MakeTestUser,
    opensearch_index: OpenSearchDocumentIndex,
) -> Generator[ContentEnv, None, None]:
    tag = uuid.uuid4().hex[:8]
    # OpenSearch stores dates to the second.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    user = make_test_user(f"pgtool_content_{tag}")
    cc_pair: ConnectorCredentialPair = make_cc_pair(
        db_session, source=DocumentSource.WEB
    )
    ids = {doc.key: f"pgtool_content_{doc.key}_{tag}" for doc in _DOCS}
    try:
        chunks = []
        for doc in _DOCS:
            updated = now - timedelta(days=doc.days_ago)
            db_session.add(
                DbDocument(
                    id=ids[doc.key],
                    semantic_id=f"{doc.key} {tag}",
                    link=f"https://example.com/{ids[doc.key]}",
                    doc_updated_at=updated,
                    hidden=doc.hidden,
                    kg_stage=KGStage.NOT_STARTED,
                )
            )
            db_session.flush()
            db_session.add(
                DocumentByConnectorCredentialPair(
                    id=ids[doc.key],
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                    has_been_indexed=True,
                )
            )
            chunks.append(_chunk(ids[doc.key], doc, updated, cc_pair.id))
        db_session.commit()

        opensearch_index.index(
            chunks,
            IndexingMetadata(
                doc_id_to_chunk_cnt_diff={
                    chunk.source_document.id: IndexingMetadata.ChunkCounts(
                        old_chunk_cnt=0, new_chunk_cnt=1
                    )
                    for chunk in chunks
                }
            ),
        )
        opensearch_index.update(
            [
                MetadataUpdateRequest(
                    document_ids=[ids["hidden"]],
                    doc_id_to_chunk_cnt={ids["hidden"]: 1},
                    hidden=True,
                )
            ]
        )
        opensearch_index._client.refresh_index()

        tool = PostgresTool(
            user=user, current_chat_session_id=None, scope=DocumentScope()
        )
        with patch.object(
            postgres_tool,
            "get_default_document_index",
            return_value=opensearch_index,
        ):
            yield ContentEnv(tag=tag, tool=tool, ids=ids, cc_pair_id=cc_pair.id)
    finally:
        db_session.rollback()
        try:
            opensearch_index.delete_documents(list(ids.values()))
            opensearch_index._client.refresh_index()
        finally:
            cleanup_cc_pair(db_session, cc_pair)


def _invoke(tool: PostgresTool, **llm_kwargs: JsonValue) -> ToolResult:
    result = tool.run(
        ToolInvocation(
            call_id="call",
            arguments=llm_kwargs,
            call_index=0,
            cancellation=CancellationSignal(),
            update=lambda _: None,
        ),
        ToolContext(),
    )
    assert isinstance(result, ToolResult)
    return result


def _run(tool: PostgresTool, **llm_kwargs: JsonValue) -> str:
    result = _invoke(tool, **llm_kwargs)
    assert not result.is_error, result.content
    return result.content


def _run_error(tool: PostgresTool, **llm_kwargs: JsonValue) -> str:
    result = _invoke(tool, **llm_kwargs)
    assert result.is_error
    return result.content


def _listed(env: ContentEnv, text: str) -> list[str]:
    """The document keys a result lists, in order. A row shows its ID in the
    link too."""
    by_id = {doc_id: key for key, doc_id in env.ids.items()}
    found = re.findall(r"pgtool_content_\w+", text)
    return [by_id[doc_id] for doc_id in dict.fromkeys(found) if doc_id in by_id]


def _next_cursor(text: str) -> str | None:
    match = re.search(r"next_cursor: (\S+)", text)
    return match.group(1) if match else None


def _list_all(env: ContentEnv, **llm_kwargs: JsonValue) -> list[str]:
    """Pages through a content listing two documents at a time."""
    listed: list[str] = []
    cursor: str | None = None
    while True:
        kwargs = dict(llm_kwargs)
        if cursor is not None:
            kwargs["cursor"] = cursor
        text = _run(
            env.tool, table="document", content_contains=_PHRASE, limit=2, **kwargs
        )
        listed.extend(_listed(env, text))
        cursor = _next_cursor(text)
        if cursor is None:
            return listed


@contextmanager
def _force_path(postgres_first: bool) -> Generator[None, None, None]:
    with patch.object(
        content,
        "MAX_POSTGRES_FIRST_CANDIDATES",
        10**9 if postgres_first else -1,
    ):
        yield


@pytest.mark.parametrize("postgres_first", [True, False])
def test_lists_the_same_matches_either_way(
    content_env: ContentEnv, postgres_first: bool
) -> None:
    with _force_path(postgres_first):
        assert _list_all(content_env, title_contains=content_env.tag) == [
            "fox",
            "dog",
            "owl",
        ]
        assert _list_all(
            content_env, title_contains=content_env.tag, order_by="updated_asc"
        ) == ["owl", "dog", "fox"]


@pytest.mark.parametrize("postgres_first", [True, False])
def test_postgres_filters_apply_either_way(
    content_env: ContentEnv, postgres_first: bool
) -> None:
    with _force_path(postgres_first):
        assert _list_all(content_env, title_contains=f"owl {content_env.tag}") == [
            "owl"
        ]


def test_cursor_keeps_its_way(content_env: ContentEnv) -> None:
    tool = content_env.tool
    with _force_path(True):
        first = _run(
            tool,
            table="document",
            content_contains=_PHRASE,
            title_contains=content_env.tag,
            limit=2,
        )
    assert _listed(content_env, first) == ["fox", "dog"]
    cursor = _next_cursor(first)
    assert cursor is not None
    with _force_path(False):
        rest = _run(
            tool,
            table="document",
            content_contains=_PHRASE,
            title_contains=content_env.tag,
            limit=2,
            cursor=cursor,
        )
    assert _listed(content_env, rest) == ["owl"]
    assert _next_cursor(rest) is None

    message = _run_error(
        tool,
        table="document",
        content_contains="brown dog",
        title_contains=content_env.tag,
        cursor=cursor,
    )
    assert "different filters" in message


def _cursor_path(cursor: str) -> str:
    padded = cursor + "=" * (-len(cursor) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode()))["p"]


@pytest.mark.parametrize(
    ("setting", "with_title_filter", "expected_path"),
    [
        # Without a Postgres-only filter, "auto" would go to OpenSearch first.
        (content.ContentFirst.POSTGRES, False, content.ContentPath.POSTGRES_FIRST),
        # With one, "auto" would go to Postgres first.
        (content.ContentFirst.OPENSEARCH, True, content.ContentPath.OPENSEARCH_FIRST),
    ],
)
def test_setting_overrides_the_choice(
    content_env: ContentEnv,
    setting: content.ContentFirst,
    with_title_filter: bool,
    expected_path: content.ContentPath,
) -> None:
    kwargs: dict[str, JsonValue] = {
        "updated_after": (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
    }
    if with_title_filter:
        kwargs["title_contains"] = content_env.tag
    with patch.object(content, "CONTENT_FIRST", setting):
        text = _run(
            content_env.tool,
            table="document",
            content_contains=_PHRASE,
            limit=2,
            **kwargs,
        )
    assert _listed(content_env, text) == ["fox", "dog"]
    cursor = _next_cursor(text)
    assert cursor is not None
    assert _cursor_path(cursor) == expected_path.value


@pytest.mark.parametrize("postgres_first", [True, False])
def test_counts_either_way(content_env: ContentEnv, postgres_first: bool) -> None:
    with _force_path(postgres_first):
        text = _run(
            content_env.tool,
            table="document",
            content_contains=_PHRASE,
            title_contains=content_env.tag,
            count=True,
        )
    assert text.startswith("3 matching documents")


def test_counts_in_opensearch_without_postgres_filters(
    content_env: ContentEnv,
) -> None:
    # The test index holds only this test's documents.
    text = _run(
        content_env.tool, table="document", content_contains=_PHRASE, count=True
    )
    assert text.startswith("3 matching documents")


def test_count_stops_at_its_limit(content_env: ContentEnv) -> None:
    with (
        _force_path(True),
        patch.object(content, "CANDIDATE_BATCH_SIZE", 1),
        patch.object(content, "MAX_COUNT", 2),
    ):
        text = _run(
            content_env.tool,
            table="document",
            content_contains=_PHRASE,
            title_contains=content_env.tag,
            count=True,
        )
    assert text.startswith("At least 2 matching documents")


@pytest.mark.parametrize("postgres_first", [True, False])
def test_out_of_time_returns_a_partial_page_that_continues(
    content_env: ContentEnv, postgres_first: bool
) -> None:
    with (
        _force_path(postgres_first),
        patch.object(content, "TIME_BUDGET_S", 0.0),
        patch.object(content, "CANDIDATE_BATCH_SIZE", 1),
        patch.object(content, "MATCH_BATCH_SIZE", 1),
    ):
        first = _run(
            content_env.tool,
            table="document",
            content_contains=_PHRASE,
            title_contains=content_env.tag,
        )
        assert "took too long" in first
        assert _listed(content_env, first) == ["fox"]
        assert _list_all(content_env, title_contains=content_env.tag) == [
            "fox",
            "dog",
            "owl",
        ]


def test_rejects_unsupported_content_queries(content_env: ContentEnv) -> None:
    tool = content_env.tool
    message = _run_error(
        tool, table="document", content_contains=_PHRASE, count=True, group_by="source"
    )
    assert "'group_by' does not work" in message
    message = _run_error(
        tool, table="document", content_contains=_PHRASE, order_by="title_asc"
    )
    assert "order by date only" in message
    message = _run_error(tool, table="document", content_contains="the and")
    assert "no searchable words" in message


@pytest.mark.parametrize(
    "setting",
    ["DISABLE_POSTGRES_QUERY_CONTENT_FILTER", "DISABLE_VECTOR_DB", "CONTENT_FIRST"],
)
def test_rejects_content_when_unavailable(
    content_env: ContentEnv, setting: str
) -> None:
    # CONTENT_FIRST is None when POSTGRES_QUERY_CONTENT_FIRST is invalid.
    value = None if setting == "CONTENT_FIRST" else True
    with patch.object(content, setting, value):
        message = _run_error(
            content_env.tool, table="document", content_contains=_PHRASE
        )
    assert "not available" in message


def test_invalid_setting_turns_the_filter_off() -> None:
    with patch.object(content, "POSTGRES_QUERY_CONTENT_FIRST", "opensearh"):
        assert content._load_content_first() is None
    with patch.object(content, "POSTGRES_QUERY_CONTENT_FIRST", "postgres"):
        assert content._load_content_first() == content.ContentFirst.POSTGRES


def test_censoring_sources_come_from_ee() -> None:
    with patch.object(global_version, "is_ee_version", return_value=True):
        assert DocumentSource.SALESFORCE in content._censoring_sources()
    with patch.object(global_version, "is_ee_version", return_value=False):
        assert content._censoring_sources() == set()


@pytest.mark.parametrize("postgres_first", [True, False])
@pytest.mark.parametrize("public", [True, False])
def test_censoring_sources_match_only_under_public_cc_pairs(
    content_env: ContentEnv, postgres_first: bool, public: bool
) -> None:
    uncensored = [content_env.cc_pair_id] if public else []
    with (
        _force_path(postgres_first),
        patch.object(content, "_censoring_sources", return_value={DocumentSource.WEB}),
        patch.object(
            content, "public_cc_pair_ids_for_sources", return_value=uncensored
        ),
    ):
        for title_filter in ({}, {"title_contains": content_env.tag}):
            text = _run(
                content_env.tool,
                table="document",
                content_contains=_PHRASE,
                count=True,
                **title_filter,
            )
            assert text.startswith("3" if public else "0")
            text = _run(
                content_env.tool,
                table="document",
                content_contains=_PHRASE,
                **title_filter,
            )
            assert _listed(content_env, text) == (
                ["fox", "dog", "owl"] if public else []
            )


def test_public_cc_pair_ids_for_sources(
    db_session: Session, content_env: ContentEnv
) -> None:
    # The fixture's pair is a public WEB pair.
    assert content_env.cc_pair_id in public_cc_pair_ids_for_sources(
        db_session, [DocumentSource.WEB]
    )
    assert content_env.cc_pair_id not in public_cc_pair_ids_for_sources(
        db_session, [DocumentSource.SALESFORCE]
    )


def test_sources_outside_the_scope_match_nothing(content_env: ContentEnv) -> None:
    tool = PostgresTool(
        user=content_env.tool._user,
        current_chat_session_id=None,
        scope=DocumentScope(source_types=[DocumentSource.SLACK]),
    )
    # Without a Postgres-only filter, OpenSearch counts alone.
    text = _run(
        tool, table="document", content_contains=_PHRASE, source_type="web", count=True
    )
    assert "\n0 matching documents" in text


def test_selected_node_matches_its_own_document(
    db_session: Session, content_env: ContentEnv
) -> None:
    node = HierarchyNode(
        raw_node_id=f"pgtool_content_node_{content_env.tag}",
        display_name="fox page",
        source=DocumentSource.WEB,
        node_type=HierarchyNodeType.FOLDER,
        document_id=content_env.ids["fox"],
    )
    db_session.add(node)
    db_session.commit()
    try:
        tool = PostgresTool(
            user=content_env.tool._user,
            current_chat_session_id=None,
            scope=DocumentScope(hierarchy_node_ids=[node.id]),
        )
        # Without a Postgres-only filter, OpenSearch counts alone.
        text = _run(tool, table="document", content_contains=_PHRASE, count=True)
        assert "\n1 matching documents" in text
        text = _run(tool, table="document", content_contains=_PHRASE)
        assert _listed(content_env, text) == ["fox"]
    finally:
        db_session.delete(node)
        db_session.commit()
