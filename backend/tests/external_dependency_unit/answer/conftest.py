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
from onyx.server.manage.llm.models import LLMProviderUpsertRequest


def ensure_default_llm_provider(db_session: Session) -> None:
    """Ensure a default LLM provider exists for tests that exercise chat flows."""

    try:
        llm_provider_request = LLMProviderUpsertRequest(
            name="test-provider",
            provider="openai",
            api_key=os.environ.get("OPENAI_API_KEY", "test"),
            is_public=True,
            default_model_name="gpt-4.1",
            fast_default_model_name="gpt-4.1",
            groups=[],
        )
        provider = upsert_llm_provider(
            llm_provider_upsert_request=llm_provider_request,
            db_session=db_session,
        )
        update_default_provider(provider.id, db_session)
    except Exception as exc:  # pragma: no cover - only hits on duplicate setup issues
        print(f"Note: Could not create LLM provider: {exc}")


@pytest.fixture
def mock_nlp_embeddings_post() -> Iterator[None]:
    """Patch model-server embedding HTTP calls used by NLP components."""

    def _mock_post(
        url: str,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
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
def mock_external_deps(
    mock_nlp_embeddings_post: None,
    mock_gpu_status: None,
    mock_vespa_query: None,
) -> Iterator[None]:
    """Convenience fixture to enable all common external dependency mocks."""
    yield
