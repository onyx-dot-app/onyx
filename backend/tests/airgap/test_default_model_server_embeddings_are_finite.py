import json
import math
import urllib.request

from onyx.configs.model_configs import (
    ASYM_QUERY_PREFIX,
    DEFAULT_DOCUMENT_ENCODER_MODEL,
    DOC_EMBEDDING_DIM,
)
from shared_configs.configs import (
    DOC_EMBEDDING_CONTEXT_SIZE,
    MODEL_SERVER_HOST,
    MODEL_SERVER_PORT,
)
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import EmbedRequest, EmbedResponse

_EMBEDDING_ENDPOINT = (
    f"http://{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}/encoder/bi-encoder-embed"
)
_HTTP_POST_METHOD = "POST"
_JSON_HEADERS = {"Content-Type": "application/json"}
_SAMPLE_TEXT = "hello world"
_REQUEST_TIMEOUT_SECONDS = 120


def _embed_sample_text() -> EmbedResponse:
    embed_request = EmbedRequest(
        texts=[_SAMPLE_TEXT],
        model_name=DEFAULT_DOCUMENT_ENCODER_MODEL,
        max_context_length=DOC_EMBEDDING_CONTEXT_SIZE,
        normalize_embeddings=True,
        text_type=EmbedTextType.QUERY,
        manual_query_prefix=ASYM_QUERY_PREFIX,
    )
    request = urllib.request.Request(
        _EMBEDDING_ENDPOINT,
        data=json.dumps(embed_request.model_dump(mode="json")).encode(),
        headers=_JSON_HEADERS,
        method=_HTTP_POST_METHOD,
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        return EmbedResponse.model_validate_json(response.read())


def test_default_model_server_embeddings_are_finite() -> None:
    response = _embed_sample_text()

    assert len(response.embeddings) == 1
    assert len(response.embeddings[0]) == DOC_EMBEDDING_DIM
    assert all(math.isfinite(value) for value in response.embeddings[0])


if __name__ == "__main__":
    test_default_model_server_embeddings_are_finite()
