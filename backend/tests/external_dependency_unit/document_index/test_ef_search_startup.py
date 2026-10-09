"""External dependency tests for indices created while ef_search was lower.

ef_search is a dynamic index setting, so startup must raise it in place on an
existing index instead of leaving the old value.
"""

import uuid
from typing import Any

import pytest

from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.constants import EF_SEARCH
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import DocumentSchema
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import EMBEDDING_DIM

_EF_SEARCH_SETTING = "index.knn.algo_param.ef_search"
# An older value that differs from EF_SEARCH under any configuration.
_OLD_EF_SEARCH: int = 100 if EF_SEARCH != 100 else 101


def _create_index(client: OpenSearchIndexClient, knn_settings: dict[str, Any]) -> None:
    """Creates the index the way older code did, with the given knn settings."""
    settings: dict[str, Any] = DocumentSchema.get_index_settings_based_on_environment()
    settings["index"] = {
        **{k: v for k, v in settings["index"].items() if not k.startswith("knn")},
        **knn_settings,
    }
    client.create_index(
        mappings=DocumentSchema.get_document_schema(
            vector_dimension=EMBEDDING_DIM, multitenant=False
        ),
        settings=settings,
    )


def _start_up(index_name: str) -> None:
    OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    ).verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)


def _ef_search(client: OpenSearchIndexClient) -> str | None:
    settings, _ = client.get_settings(flat_settings=True)
    return settings.get(_EF_SEARCH_SETTING)


@pytest.mark.parametrize(
    "old_knn_settings",
    [
        pytest.param(
            {"knn": True, "knn.algo_param.ef_search": _OLD_EF_SEARCH},
            id="ef_search_old",
        ),
        pytest.param({"knn": True}, id="ef_search_unset"),
    ],
)
def test_startup_applies_current_ef_search(
    tenant_context: None,  # noqa: ARG001
    old_knn_settings: dict[str, Any],
) -> None:
    """Startup on an existing index sets ef_search to EF_SEARCH."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name: str = f"test_ef_search_{uuid.uuid4().hex[:8]}"
    with OpenSearchIndexClient(index_name=index_name) as client:
        _create_index(client, old_knn_settings)
        try:
            assert _ef_search(client) != str(EF_SEARCH)
            _start_up(index_name)
            assert _ef_search(client) == str(EF_SEARCH)
        finally:
            client.delete_index()


def test_startup_leaves_current_ef_search_alone(
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An index already at EF_SEARCH gets no settings update."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    updates: list[dict[str, Any]] = []

    def _record(
        _self: OpenSearchIndexClient, settings: dict[str, Any], **_kwargs: Any
    ) -> None:
        updates.append(settings)

    monkeypatch.setattr(OpenSearchIndexClient, "update_settings", _record)
    index_name: str = f"test_ef_search_{uuid.uuid4().hex[:8]}"
    with OpenSearchIndexClient(index_name=index_name) as client:
        _create_index(client, {"knn": True, "knn.algo_param.ef_search": EF_SEARCH})
        try:
            _start_up(index_name)
            assert updates == []
        finally:
            client.delete_index()


def test_startup_survives_ef_search_update_failure(
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected ef_search update logs and does not fail startup."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    def _reject(
        _self: OpenSearchIndexClient, settings: dict[str, Any], **_kwargs: Any
    ) -> None:
        raise RuntimeError(f"rejected {settings}")

    monkeypatch.setattr(OpenSearchIndexClient, "update_settings", _reject)
    index_name: str = f"test_ef_search_{uuid.uuid4().hex[:8]}"
    with OpenSearchIndexClient(index_name=index_name) as client:
        _create_index(client, {"knn": True, "knn.algo_param.ef_search": _OLD_EF_SEARCH})
        try:
            _start_up(index_name)
            assert _ef_search(client) == str(_OLD_EF_SEARCH)
        finally:
            client.delete_index()
