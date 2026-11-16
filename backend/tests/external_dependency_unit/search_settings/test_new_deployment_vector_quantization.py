"""External dependency tests for the vector quantization a new deployment starts
with.

Startup sets 7-bit only when no index exists for the search settings and the
deployment shows no earlier use. The deployment checks are patched because the
test database is shared; the OpenSearch checks run against the real cluster.
"""

import uuid
from collections.abc import Generator
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx import setup
from onyx.db.enums import VectorQuantization
from onyx.db.models import SearchSettings
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)

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
    db_session: Session, index_name: str, used_by: str | None = None
) -> VectorQuantization:
    """Runs the startup rule on unsaved search settings and returns the result.

    used_by names one sign of earlier use to report; None reports a new deployment.
    """
    search_settings = SearchSettings(
        index_name=index_name, vector_quantization=VectorQuantization.NONE
    )
    other_settings = [search_settings]
    if used_by == "other_search_settings":
        other_settings.append(SearchSettings())
    with (
        patch.object(setup, "get_all_search_settings", return_value=other_settings),
        patch.object(setup, "check_docs_exist", return_value=used_by == _USE_CHECKS[0]),
        patch.object(
            setup, "check_connectors_exist", return_value=used_by == _USE_CHECKS[1]
        ),
        patch.object(
            setup, "check_user_files_exist", return_value=used_by == _USE_CHECKS[2]
        ),
    ):
        setup.set_new_deployment_vector_quantization(db_session, search_settings)
    return search_settings.vector_quantization


def test_new_deployment_gets_7_bit(db_session: Session, index_name: str) -> None:
    assert _set_default(db_session, index_name) == VectorQuantization.SCALAR_7_BIT


def test_existing_index_keeps_its_quantization(
    db_session: Session, index_name: str
) -> None:
    with OpenSearchIndexClient(index_name=index_name) as client:
        client.create_index(mappings={}, settings={})

    assert _set_default(db_session, index_name) == VectorQuantization.NONE


@pytest.mark.parametrize("used_by", [*_USE_CHECKS, "other_search_settings"])
def test_earlier_use_keeps_its_quantization(
    db_session: Session, index_name: str, used_by: str
) -> None:
    assert _set_default(db_session, index_name, used_by) == VectorQuantization.NONE
