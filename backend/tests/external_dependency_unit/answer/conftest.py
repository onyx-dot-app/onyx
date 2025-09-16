from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_nlp_embeddings_post():
    """Patch model-server embedding HTTP calls used by NLP components."""

    def _mock_post(
        url: str, json: dict | None = None, headers: dict | None = None, **kwargs
    ):
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
def mock_gpu_status():
    """Avoid hitting model server for GPU status checks."""
    with patch(
        "onyx.utils.gpu_utils._get_gpu_status_from_model_server", return_value=False
    ):
        yield


@pytest.fixture
def mock_vespa_query():
    """Stub Vespa query to a safe empty response to avoid CI flakiness."""
    with patch("onyx.document_index.vespa.index.query_vespa", return_value=[]):
        yield


@pytest.fixture
def mock_external_deps(mock_nlp_embeddings_post, mock_gpu_status, mock_vespa_query):
    """Convenience fixture to enable all common external dependency mocks."""
    yield
