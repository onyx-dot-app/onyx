"""External dependency tests for the vector quantization a new deployment starts
with.

Startup sets 7-bit only when no index exists for the search settings and the
deployment shows no earlier use. An existing index sets the quantization it was
built with. The deployment checks are patched because the
test database is shared; the OpenSearch checks run against the real cluster.
"""

import uuid
from collections.abc import Generator
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexModelStatus, VectorQuantization
from onyx.db.models import SearchSettings
from onyx.document_index.opensearch import new_deployment
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.schema import CONTENT_VECTOR_FIELD_NAME

_USE_CHECKS: tuple[str, ...] = (
    "check_docs_exist",
    "check_connectors_exist",
    "check_user_files_exist",
)


@pytest.fixture
def index_name() -> Generator[str, None, None]:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    name = f"test_new_deployment_quantization_{uuid.uuid4().hex[:8]}"
    yield name
    with OpenSearchIndexClient(index_name=name) as client:
        if client.index_exists():
            client.delete_index()


def _set_default(
    db_session: Session,
    index_name: str,
    used_by: str | None = None,
    search_settings: SearchSettings | None = None,
) -> VectorQuantization:
    """Runs the startup rule and returns the result.

    used_by names one sign of earlier use to report; None reports a new deployment.
    Without search_settings, the rule runs on unsaved search settings.
    """
    if search_settings is None:
        search_settings = SearchSettings(
            index_name=index_name, vector_quantization=VectorQuantization.NONE
        )
    with (
        patch.object(
            new_deployment, "get_secondary_search_settings", return_value=None
        ),
        patch.object(
            new_deployment, "check_docs_exist", return_value=used_by == _USE_CHECKS[0]
        ),
        patch.object(
            new_deployment,
            "check_connectors_exist",
            return_value=used_by == _USE_CHECKS[1],
        ),
        patch.object(
            new_deployment,
            "check_user_files_exist",
            return_value=used_by == _USE_CHECKS[2],
        ),
    ):
        new_deployment.set_new_deployment_vector_quantization(
            db_session, search_settings
        )
    return search_settings.vector_quantization


def test_new_deployment_gets_7_bit(db_session: Session, index_name: str) -> None:
    assert _set_default(db_session, index_name) == VectorQuantization.SCALAR_7_BIT


def test_new_deployment_saves_7_bit(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    index_name: str,
) -> None:
    # A PAST row, so the test does not change the shared database's present settings.
    search_settings = SearchSettings(
        model_name="test-model",
        model_dim=384,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        index_name=index_name,
        status=IndexModelStatus.PAST,
        vector_quantization=VectorQuantization.NONE,
    )
    db_session.add(search_settings)
    db_session.commit()
    try:
        _set_default(db_session, index_name, search_settings=search_settings)

        with get_session_with_current_tenant() as fresh_session:
            saved = fresh_session.get(SearchSettings, search_settings.id)
            assert saved is not None
            assert saved.vector_quantization == VectorQuantization.SCALAR_7_BIT
    finally:
        db_session.delete(search_settings)
        db_session.commit()


def test_existing_float_index_keeps_none(db_session: Session, index_name: str) -> None:
    with OpenSearchIndexClient(index_name=index_name) as client:
        client.create_index(mappings={}, settings={})

    assert _set_default(db_session, index_name) == VectorQuantization.NONE


def test_existing_7_bit_index_sets_7_bit(db_session: Session, index_name: str) -> None:
    # Postgres was reset and OpenSearch kept the 7-bit index.
    mappings = {
        "properties": {
            CONTENT_VECTOR_FIELD_NAME: {
                "type": "knn_vector",
                "dimension": 4,
                "method": {
                    "name": "hnsw",
                    "engine": "lucene",
                    "space_type": "cosinesimil",
                    "parameters": {
                        "encoder": {"name": "sq", "parameters": {"bits": 7}}
                    },
                },
            }
        }
    }
    with OpenSearchIndexClient(index_name=index_name) as client:
        client.create_index(mappings=mappings, settings={"index": {"knn": True}})

    assert _set_default(db_session, index_name) == VectorQuantization.SCALAR_7_BIT


@pytest.mark.parametrize("used_by", _USE_CHECKS)
def test_earlier_use_keeps_its_quantization(
    db_session: Session, index_name: str, used_by: str
) -> None:
    assert _set_default(db_session, index_name, used_by) == VectorQuantization.NONE
