import os
from collections.abc import Iterator, Mapping
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import update_default_provider, upsert_llm_provider
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)


def ensure_default_llm_provider(db_session: Session) -> None:
    """Ensure a default LLM provider exists for tests that exercise chat flows."""

    llm_provider_request = LLMProviderUpsertRequest(
        name="test-provider",
        provider=LlmProviderNames.OPENAI,
        api_key=os.environ.get("OPENAI_API_KEY", "test"),
        is_public=True,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name="gpt-5-mini",
                is_visible=True,
            )
        ],
        groups=[],
    )
    provider = upsert_llm_provider(
        llm_provider_upsert_request=llm_provider_request,
        db_session=db_session,
    )
    update_default_provider(provider.id, "gpt-5-mini", db_session)


@pytest.fixture
def mock_nlp_embeddings_post() -> Iterator[None]:
    """Patch model-server embedding HTTP calls used by NLP components."""

    def _mock_post(
        url: str,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,  # noqa: ARG001
        **kwargs: Any,  # noqa: ARG001
    ) -> MagicMock:
        resp = MagicMock()
        if "encoder/bi-encoder-embed" in url:
            num_texts = len(json.get("texts", [])) if json else 1
            resp.status_code = 200
            resp.json.return_value = {"embeddings": [[0.0] * 768] * num_texts}
            resp.raise_for_status = MagicMock()
            return resp
        resp.status_code = 200
        resp.json.return_value = {}
        resp.raise_for_status = MagicMock()
        return resp

    with patch(
        "onyx.natural_language_processing.search_nlp_models.requests.post",
        side_effect=_mock_post,
    ):
        yield


@pytest.fixture
def mock_gpu_status() -> Iterator[None]:
    """Avoid hitting model server for GPU status checks."""
    with patch(
        "onyx.utils.gpu_utils._get_gpu_status_from_model_server", return_value=False
    ):
        yield


@pytest.fixture
def mock_document_index() -> Iterator[None]:
    index = MagicMock()
    index.id_based_retrieval.return_value = []
    with patch(
        "onyx.tools.tool_constructor.get_default_document_index", return_value=index
    ):
        yield


@pytest.fixture
def mock_file_store() -> Iterator[None]:
    """Mock the file store to avoid S3/storage dependencies in tests."""

    def _mock_save_file(*args: Any, **kwargs: Any) -> str:  # noqa: ARG001
        return "123"

    mock_store = MagicMock()
    mock_store.save_file.side_effect = _mock_save_file
    mock_store.initialize.return_value = None

    with patch(
        "onyx.file_store.utils.get_default_file_store",
        return_value=mock_store,
    ):
        yield


@pytest.fixture
def mock_external_deps(
    mock_nlp_embeddings_post: None,  # noqa: ARG001
    mock_gpu_status: None,  # noqa: ARG001
    mock_document_index: None,  # noqa: ARG001
    mock_file_store: None,  # noqa: ARG001
) -> Iterator[None]:
    """Convenience fixture to enable all common external dependency mocks."""
    yield
