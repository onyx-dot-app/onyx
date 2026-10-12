"""Tests for the document index factory.

`get_default_document_index` is the only way callers get a document index, for
both retrieval and indexing. These tests pin how it maps search settings to the
OpenSearch primary/secondary pair.
"""

from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from onyx.db.enums import VectorQuantization
from onyx.db.models import SearchSettings
from onyx.document_index import factory
from onyx.document_index.disabled import DisabledDocumentIndex
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchIndexPair,
)

_FACTORY = "onyx.document_index.factory"


def _search_settings(index_name: str) -> MagicMock:
    search_settings = MagicMock(spec=SearchSettings)
    search_settings.index_name = index_name
    return search_settings


def _indexing_setting(embedding_dim: int) -> MagicMock:
    indexing_setting = MagicMock()
    indexing_setting.final_embedding_dim = embedding_dim
    indexing_setting.vector_quantization = VectorQuantization.NONE
    return indexing_setting


@pytest.fixture
def mock_opensearch_index() -> Iterator[MagicMock]:
    """Replaces the OpenSearch index class so no client is built."""
    with (
        patch(f"{_FACTORY}.OpenSearchDocumentIndex") as index_cls,
        patch(f"{_FACTORY}.get_current_tenant_id", return_value="tenant_a"),
        patch(f"{_FACTORY}.MULTI_TENANT", False),
        patch(f"{_FACTORY}.DISABLE_VECTOR_DB", False),
    ):
        # One distinct instance per construction, so primary != secondary.
        index_cls.side_effect = lambda **_kwargs: MagicMock()
        yield index_cls


def test_disable_vector_db_returns_disabled_index() -> None:
    with patch(f"{_FACTORY}.DISABLE_VECTOR_DB", True):
        document_index = factory.get_default_document_index(
            _search_settings("primary_index"), None
        )

    assert isinstance(document_index, DisabledDocumentIndex)


def test_primary_only_builds_pair_without_secondary(
    mock_opensearch_index: MagicMock,
) -> None:
    primary_settings = _search_settings("primary_index")
    with patch(
        f"{_FACTORY}.IndexingSetting.from_db_model",
        return_value=_indexing_setting(768),
    ):
        document_index = factory.get_default_document_index(primary_settings, None)

    assert isinstance(document_index, OpenSearchIndexPair)
    assert document_index.secondary is None
    mock_opensearch_index.assert_called_once()
    kwargs = mock_opensearch_index.call_args.kwargs
    assert kwargs["index_name"] == "primary_index"
    assert kwargs["embedding_dim"] == 768
    assert kwargs["vector_quantization"] == VectorQuantization.NONE
    assert kwargs["tenant_state"].tenant_id == "tenant_a"
    assert kwargs["tenant_state"].multitenant is False


def test_secondary_settings_build_secondary_index(
    mock_opensearch_index: MagicMock,
) -> None:
    primary_settings = _search_settings("primary_index")
    secondary_settings = _search_settings("secondary_index")

    def _from_db_model(search_settings: MagicMock) -> MagicMock:
        return _indexing_setting(768 if search_settings is primary_settings else 1024)

    with patch(f"{_FACTORY}.IndexingSetting.from_db_model", side_effect=_from_db_model):
        document_index = factory.get_default_document_index(
            primary_settings, secondary_settings
        )

    assert isinstance(document_index, OpenSearchIndexPair)
    assert document_index.secondary is not None
    assert document_index.primary is not document_index.secondary
    index_names = [
        call.kwargs["index_name"] for call in mock_opensearch_index.call_args_list
    ]
    assert index_names == ["primary_index", "secondary_index"]
    embedding_dims = [
        call.kwargs["embedding_dim"] for call in mock_opensearch_index.call_args_list
    ]
    assert embedding_dims == [768, 1024]


@pytest.mark.parametrize("with_secondary", [False, True])
@pytest.mark.parametrize("backfill", [False, True])
def test_primary_backfill_flag_reaches_the_pair(
    mock_opensearch_index: MagicMock,  # noqa: ARG001
    with_secondary: bool,
    backfill: bool,
) -> None:
    """The INSTANT reindex-port flag must reach the pair on both the
    primary-only and the primary+secondary paths."""
    secondary_settings = _search_settings("secondary_index") if with_secondary else None
    with patch(
        f"{_FACTORY}.IndexingSetting.from_db_model",
        return_value=_indexing_setting(768),
    ):
        document_index = factory.get_default_document_index(
            _search_settings("primary_index"),
            secondary_settings,
            primary_backfill_in_progress=backfill,
        )

    assert isinstance(document_index, OpenSearchIndexPair)
    assert document_index._primary_backfill_in_progress is backfill


def test_primary_backfill_flag_is_keyword_only() -> None:
    """A positional third argument used to be the DB session. Keeping the flag
    keyword-only makes a stale positional call fail loudly instead of passing a
    truthy session as the flag."""
    # Typed as Any so the type checker lets the stale call through to runtime.
    get_default_document_index = cast(Any, factory.get_default_document_index)
    with pytest.raises(TypeError):
        get_default_document_index(_search_settings("primary_index"), None, True)
