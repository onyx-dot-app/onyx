import html
import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import pytest

from onyx.configs.constants import INDEX_SEPARATOR
from onyx.connectors.confluence.onyx_confluence import extract_text_from_confluence_html
from onyx.context.search.models import IndexFilters, Tag
from onyx.document_index.vespa import chunk_retrieval
from onyx.document_index.vespa.internal_types import VespaChunkRequest
from onyx.document_index.vespa.shared_utils import vespa_request_builders as builders


@pytest.mark.parametrize(
    "field", ["document_set", "access_control_list", "tags", "tenant_id"]
)
def test_filter_values_remain_literals(field: str) -> None:
    value = 'folder\\" or true or "'
    escaped = r"folder\\\" or true or \""
    filters = IndexFilters(access_control_list=None)
    if field == "tags":
        filters.tags = [Tag(tag_key=value, tag_value=value)]
        expected = f'"{escaped}{INDEX_SEPARATOR}{escaped}"'
    else:
        filters = filters.model_copy(
            update={field: value if field == "tenant_id" else [value]}
        )
        expected = f'"{escaped}"'
    with patch.object(builders, "MULTI_TENANT", True):
        query = builders.build_vespa_filters(filters)
    assert expected in query
    assert value not in query


def test_document_id_remains_literal() -> None:
    query = builders.build_vespa_id_based_retrieval_yql(
        VespaChunkRequest(document_id='doc\\" or true or "', max_chunk_ind=2)
    )
    assert r'document_id contains "doc\\\" or true or \""' in query
    assert "chunk_id >= 0 and chunk_id <= 2" in query


def test_batch_keeps_all_ids_under_access_filters() -> None:
    with patch.object(chunk_retrieval, "query_vespa", return_value=[]) as query:
        chunk_retrieval._get_chunks_via_batch_search(
            "test_index",
            [VespaChunkRequest("first", 0, 1), VespaChunkRequest("second", 0, 1)],
            IndexFilters(access_control_list=["allowed"]),
        )
    yql = query.call_args.args[0]["yql"]
    assert (
        'weightedSet(access_control_list, {"allowed":1}) and ((document_id contains "first"'
        in yql
    )
    assert yql.endswith(
        'or (document_id contains "second" and chunk_id >= 0 and chunk_id <= 1))'
    )


def test_confluence_include_escapes_cql_before_transport_encoding() -> None:
    title = "page\\' or type=space or title='"
    client = MagicMock()
    client.paginated_cql_retrieval.return_value = []
    extract_text_from_confluence_html(
        client,
        {
            "body": {
                "storage": {
                    "value": '<ac:structured-macro ac:name="include"><ri:page ri:content-title="'
                    + html.escape(title, quote=True)
                    + '" /></ac:structured-macro>'
                }
            }
        },
        set(),
    )
    cql = unquote(client.paginated_cql_retrieval.call_args.kwargs["cql"])
    assert cql == r"type=page and title='page\\\' or type=space or title=\''"


@pytest.fixture
def migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[5] / "alembic/versions/90e3b9af7da4_tag_fix.py"
    )
    spec = importlib.util.spec_from_file_location("tag_fix", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_tag_lookup_binds_document_id(migration: ModuleType) -> None:
    document_id = "doc' OR true --"
    bind = MagicMock()
    with patch.object(migration.op, "get_bind", return_value=bind):
        migration._get_document_tags(document_id)
    statement, parameters = bind.execute.call_args.args
    assert document_id not in str(statement)
    assert parameters == {"document_id": document_id}


def test_migration_pagination_binds_cursor(migration: ModuleType) -> None:
    document_id = "doc' OR true --"
    bind = MagicMock()
    bind.execute.return_value.fetchall.side_effect = [[(document_id,)], []]
    with patch.object(migration.op, "get_bind", return_value=bind):
        assert list(migration._get_batch_documents_with_multiple_tags(1)) == [
            [document_id]
        ]
    statement, parameters = bind.execute.call_args.args
    assert document_id not in str(statement)
    assert parameters == {"last_doc_id": document_id}


def test_migration_delete_binds_document_and_tag_ids(migration: ModuleType) -> None:
    document_id = "doc' OR true --"
    bind = MagicMock()
    bind.execute.return_value.rowcount = 1
    with (
        patch.object(migration.op, "get_bind", return_value=bind),
        patch.object(
            migration, "active_search_settings", return_value=(MagicMock(), None)
        ),
        patch.object(
            migration,
            "_get_batch_documents_with_multiple_tags",
            return_value=[[document_id]],
        ),
        patch.object(migration, "_get_vespa_metadata", return_value={"key": "current"}),
        patch.object(migration, "_get_document_tags", return_value=[(7, "key", "old")]),
    ):
        migration.remove_old_tags()
    statement, parameters = bind.execute.call_args.args
    assert document_id not in str(statement)
    assert parameters == {"document_id": document_id, "tag_ids": [7]}


def test_migration_metadata_selector_keeps_document_id_literal(
    migration: ModuleType,
) -> None:
    client = MagicMock()
    client.get.return_value.json.return_value = {
        "documents": [{"fields": {"metadata": '{"key": "current"}'}}]
    }
    with patch.object(migration, "get_vespa_http_client") as get_client:
        get_client.return_value.__enter__.return_value = client
        assert migration._get_vespa_metadata(
            """doc\\"' or true or 'other""", "test_index"
        ) == {"key": "current"}
    assert client.get.call_args.kwargs["params"]["selection"] == (
        r"""test_index.document_id=="doc\\\"' or true or 'other" and test_index.chunk_id==0"""
    )


@pytest.mark.parametrize("field", ["document_id", "tenant_id"])
def test_visit_selector_keeps_values_literal(field: str) -> None:
    value = """value\\"' or true or 'other"""
    document_id = value if field == "document_id" else "document"
    tenant_id = value if field == "tenant_id" else "tenant"
    client = MagicMock()
    client.get.return_value.json.return_value = {"documents": []}
    with (
        patch.object(chunk_retrieval, "MULTI_TENANT", True),
        patch.object(chunk_retrieval, "get_vespa_http_client") as get_client,
    ):
        get_client.return_value.__enter__.return_value = client
        assert (
            chunk_retrieval.get_chunks_via_visit_api(
                VespaChunkRequest(document_id, 0, 2),
                "test_index",
                IndexFilters(access_control_list=["allowed"], tenant_id=tenant_id),
            )
            == []
        )
    selection = client.get.call_args.kwargs["params"]["selection"]
    assert f"test_index.{field}==" + r'''"value\\\"' or true or 'other"''' in selection
    assert " and test_index.chunk_id>=0 and test_index.chunk_id<=2" in selection
    assert " and test_index.large_chunk_reference_ids == null" in selection
