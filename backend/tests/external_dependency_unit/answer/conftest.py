import os
from collections.abc import Iterator
from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest


# Counter for generating unique file IDs in mock file store
_mock_file_id_counter = 0


def ensure_default_llm_provider(db_session: Session) -> None:
    """Ensure a default LLM provider exists for tests that exercise chat flows."""

    try:
        llm_provider_request = LLMProviderUpsertRequest(
            name="test-provider",
            provider=LlmProviderNames.OPENAI,
            api_key=os.environ.get("OPENAI_API_KEY", "test"),
            is_public=True,
            default_model_name="gpt-4o-mini",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="gpt-4o-mini",
                    is_visible=True,
                )
            ],
            groups=[],
        )
        provider = upsert_llm_provider(
            llm_provider_upsert_request=llm_provider_request,
            db_session=db_session,
        )
        update_default_provider(provider.id, db_session)
    except Exception as exc:  # pragma: no cover - only hits on duplicate setup issues
        # Rollback to clear the pending transaction state
        db_session.rollback()
        print(f"Note: Could not create LLM provider: {exc}")


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
def mock_vespa_query() -> Iterator[None]:
    """Stub Vespa query to a safe empty response to avoid CI flakiness."""
    with patch("onyx.document_index.vespa.index.query_vespa", return_value=[]):
        yield


@pytest.fixture
def mock_file_store() -> Iterator[None]:
    """Mock the file store to avoid S3/storage dependencies in tests."""
    global _mock_file_id_counter

    def _mock_save_file(*args: Any, **kwargs: Any) -> str:  # noqa: ARG001
        global _mock_file_id_counter
        _mock_file_id_counter += 1
        # Return a predictable file ID for tests
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
    mock_vespa_query: None,  # noqa: ARG001
    mock_file_store: None,  # noqa: ARG001
) -> Iterator[None]:
    """Convenience fixture to enable all common external dependency mocks."""
    yield
