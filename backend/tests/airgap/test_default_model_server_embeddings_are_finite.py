import json
import math
import urllib.request

from shared_configs.configs import (
    DEFAULT_DOCUMENT_ENCODER_MODEL,
    DOC_EMBEDDING_CONTEXT_SIZE,
    MODEL_SERVER_HOST,
    MODEL_SERVER_PORT,
)
from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    bundled_local_model_names,
    get_local_model_spec,
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
# float32 on CPU gives norm 1.0. bf16 on a GPU normalizes in bf16: up to ~0.4% off.
_UNIT_NORM_TOLERANCE = 1e-2


def _default_model_spec() -> EmbeddingModelSpec:
    # Fresh installs use this model, so the image must bundle it.
    assert DEFAULT_DOCUMENT_ENCODER_MODEL in bundled_local_model_names()
    spec = get_local_model_spec(DEFAULT_DOCUMENT_ENCODER_MODEL)
    assert spec is not None
    return spec


def _embed_sample_text(
    spec: EmbeddingModelSpec, text_type: EmbedTextType
) -> EmbedResponse:
    embed_request = EmbedRequest(
        texts=[_SAMPLE_TEXT],
        model_name=spec.model_name,
        max_context_length=DOC_EMBEDDING_CONTEXT_SIZE,
        normalize_embeddings=spec.normalize,
        text_type=text_type,
        manual_query_prefix=spec.query_prefix,
        manual_passage_prefix=spec.passage_prefix,
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
    """The bundled default model embeds with no network access."""
    spec = _default_model_spec()
    for text_type in (EmbedTextType.QUERY, EmbedTextType.PASSAGE):
        response = _embed_sample_text(spec, text_type)

        assert len(response.embeddings) == 1
        embedding = response.embeddings[0]
        assert len(embedding) == spec.model_dim
        assert all(math.isfinite(value) for value in embedding)
        if spec.normalize:
            norm = math.sqrt(sum(value * value for value in embedding))
            assert abs(norm - 1.0) < _UNIT_NORM_TOLERANCE


if __name__ == "__main__":
    test_default_model_server_embeddings_are_finite()
