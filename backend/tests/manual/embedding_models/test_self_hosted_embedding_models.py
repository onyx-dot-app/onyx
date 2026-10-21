"""Real-weights checks for the SELECTABLE self-hosted embedding models.

Opt in with ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS=true. The first run downloads
about 3.2 GB of weights. Each request goes through the model server's
process_embed_request in this process. CUDA and MPS are hidden, so the models
run in fp32 on CPU, like the golden scores. Add -k voyage to run one model.
"""

import asyncio
import os
from collections.abc import Generator

import numpy as np
import numpy.typing as npt
import pytest

from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE
from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbedTextType

pytestmark = pytest.mark.skipif(
    os.environ.get("ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS") != "true",
    reason="Set ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS=true to run.",
)

SELF_HOSTED_SPECS = [
    spec for spec in selectable_embedding_model_specs() if spec.provider_type is None
]

RED_PLANET_QUERY = "Which planet is known as the Red Planet?"
RED_PLANET_DOCS = [
    "Venus is often called Earth's twin because of its similar size and proximity.",
    "Mars, known for its reddish appearance, is often referred to as the Red Planet.",
    "Jupiter, the largest planet in our solar system, has a prominent red spot.",
    "Saturn, famous for its rings, is sometimes mistaken for the Red Planet.",
]
# fp32 cosine scores of the query against each doc, with the registry prefixes,
# from the verified reference loader. The Onyx load matches them to 4 decimals
# on transformers 5.14.1 and sentence-transformers 5.6.0.
GOLDEN_SCORES: dict[str, list[float]] = {
    "ibm-granite/granite-embedding-97m-multilingual-r2": [
        0.8453,
        0.9388,
        0.9119,
        0.8907,
    ],
    "voyageai/voyage-4-nano": [0.4044, 0.6517, 0.5437, 0.5342],
    "nvidia/Nemotron-3-Embed-1B-BF16": [0.2481, 0.6449, 0.4405, 0.4168],
}
# Embedded in the same batch as the docs, so each doc gets about 50 pad tokens.
# If bidirectional attention ignores the padding mask, the scores move.
PADDING_TEXT = (
    "The rover team planned a long traverse across the crater floor. Engineers "
    "checked the wheels, the power budget and the communication windows before "
    "they sent the drive commands. Scientists picked three rock targets for the "
    "arm instruments and asked for images of the layered outcrops near the rim."
)


@pytest.fixture(scope="module", autouse=True)
def _cpu_only() -> Generator[None, None, None]:
    """Hide CUDA and MPS, so the model server takes its CPU (fp32) path."""
    import torch

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
        yield


def _embed(
    spec: EmbeddingModelSpec, texts: list[str], text_type: EmbedTextType
) -> npt.NDArray[np.float64]:
    from model_server.encoders import process_embed_request
    from shared_configs.model_server_models import EmbedRequest

    request = EmbedRequest(
        texts=texts,
        model_name=spec.model_name,
        max_context_length=DOC_EMBEDDING_CONTEXT_SIZE,
        normalize_embeddings=True,
        text_type=text_type,
        manual_query_prefix=spec.query_prefix,
        manual_passage_prefix=spec.passage_prefix,
    )
    response = asyncio.run(process_embed_request(request))
    return np.asarray(response.embeddings, dtype=np.float64)


def _short_name(spec: EmbeddingModelSpec) -> str:
    return spec.model_name.split("/")[-1]


@pytest.mark.parametrize("spec", SELF_HOSTED_SPECS, ids=_short_name)
def test_vectors_match_golden_scores(spec: EmbeddingModelSpec) -> None:
    query = _embed(spec, [RED_PLANET_QUERY], EmbedTextType.QUERY)
    docs = _embed(spec, [*RED_PLANET_DOCS, PADDING_TEXT], EmbedTextType.PASSAGE)
    for vectors in (query, docs):
        assert vectors.shape[1] == spec.model_dim
        assert np.isfinite(vectors).all()
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)
    scores = docs[: len(RED_PLANET_DOCS)] @ query[0]
    assert np.allclose(scores, GOLDEN_SCORES[spec.model_name], atol=0.01), (
        f"scores {np.round(scores, 4).tolist()}"
    )


@pytest.mark.parametrize("spec", SELF_HOSTED_SPECS, ids=_short_name)
def test_attention_is_bidirectional(spec: EmbeddingModelSpec) -> None:
    """A change to the last token must change the output of the first token.

    A causal model gives exactly 0. voyage-4-nano, the weakest, gave 0.0485.
    """
    from model_server.encoders import get_embedding_model

    model = get_embedding_model(spec.model_name, DOC_EMBEDDING_CONTEXT_SIZE)
    first_a, first_b = (
        model.encode(
            [f"{spec.passage_prefix}The quick brown fox jumps over the lazy {word}"],
            output_value="token_embeddings",
            convert_to_numpy=False,
        )[0]
        for word in ("dog", "cat")
    )
    # Each is a (tokens, hidden) matrix. One input has no padding, so row 0 is
    # the first real token. Only row 0 tells causal from bidirectional.
    assert first_a.dim() == 2 and first_b.dim() == 2
    change = (first_a[0] - first_b[0]).abs().max().item()
    assert change > 1e-3, f"Max change {change:.3g}: the attention is causal."
