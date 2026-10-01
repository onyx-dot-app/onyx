"""Real-weights checks for the SELECTABLE self-hosted embedding models.

Opt in with ``ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS=true``. The first run
downloads about 3.2 GB of weights (granite 195 MB, voyage-4-nano 693 MB,
Nemotron 2.28 GB) plus nomic for the legacy check.

Two modes:
- In-process (default): each request goes through
  ``model_server.encoders.process_embed_request``, the same code that serves
  ``/encoder/bi-encoder-embed``. No running service is needed.
- HTTP: set ``ONYX_EMBEDDING_TEST_MODEL_SERVER_URL`` (e.g.
  ``http://localhost:9000``) to send each request through Onyx's
  ``EmbeddingModel`` to a running model server. The checks that need the
  loaded model object (bidirectional attention, default prompt) are skipped.

In-process mode hides CUDA and MPS by default, so the model server takes its
CPU path (fp32 for the new models). The golden scores are fp32 values. Set
``ONYX_EMBEDDING_TEST_DEVICE=auto`` to let torch pick the device instead.

Use ``-k granite``, ``-k voyage`` or ``-k nemotron`` to run one model.
"""

import asyncio
import os
from collections.abc import Generator
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlsplit

import numpy as np
import numpy.typing as npt
import pytest

from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE
from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    EmbeddingModelStatus,
    find_embedding_model_spec,
    get_local_model_spec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbedTextType
from tests.manual.gates import SELF_HOSTED_EMBEDDING_GATE, manual_suite

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

pytestmark = [*manual_suite(SELF_HOSTED_EMBEDDING_GATE), pytest.mark.slow]

FloatMatrix = npt.NDArray[np.float64]

MODEL_SERVER_URL_ENV = "ONYX_EMBEDDING_TEST_MODEL_SERVER_URL"
DEVICE_ENV = "ONYX_EMBEDDING_TEST_DEVICE"

MAX_CONTEXT_LENGTH = DOC_EMBEDDING_CONTEXT_SIZE

SELF_HOSTED_SPECS: tuple[EmbeddingModelSpec, ...] = tuple(
    spec for spec in selectable_embedding_model_specs() if spec.provider_type is None
)

NOMIC_MODEL_NAME = "nomic-ai/nomic-embed-text-v1"

# Golden fp32 cosine scores of RED_PLANET_QUERY against RED_PLANET_DOCS, with
# the registry prefixes applied. Measured with the verified reference loader
# (transformers 5.14.1, sentence-transformers 5.4.1, pinned revisions).
RED_PLANET_QUERY = "Which planet is known as the Red Planet?"
RED_PLANET_DOCS = (
    "Venus is often called Earth's twin because of its similar size and proximity.",
    "Mars, known for its reddish appearance, is often referred to as the Red Planet.",
    "Jupiter, the largest planet in our solar system, has a prominent red spot.",
    "Saturn, famous for its rings, is sometimes mistaken for the Red Planet.",
)
RED_PLANET_ANSWER_INDEX = 1
GOLDEN_RED_PLANET_SCORES: dict[str, tuple[float, float, float, float]] = {
    "ibm-granite/granite-embedding-97m-multilingual-r2": (
        0.8453,
        0.9388,
        0.9119,
        0.8907,
    ),
    "voyageai/voyage-4-nano": (0.4044, 0.6517, 0.5437, 0.5342),
    "nvidia/Nemotron-3-Embed-1B-BF16": (0.2481, 0.6449, 0.4405, 0.4168),
}
GOLDEN_TOLERANCE = 0.01

SAMPLE_TEXTS = [
    "Onyx connects to company documents, apps and people.",
    "The quarterly report is due on the first Monday of April.",
]
SHORT_TEXT = "Mars looks red because of iron oxide dust on its surface."
LONGER_TEXT = (
    "The rover team planned a long traverse across the crater floor. Engineers "
    "checked the wheels, the power budget and the communication windows before "
    "they sent the drive commands. Scientists picked three rock targets for the "
    "arm instruments and asked for images of the layered outcrops near the rim."
)
# Well past MAX_CONTEXT_LENGTH tokens for every tokenizer.
LONG_TEXT = "The committee reviewed the annual budget in detail. " * 300
# A different topic. It must not change the embedding once LONG_TEXT is cut.
UNRELATED_TAIL = " Penguins huddle together to survive the Antarctic winter." * 300
TOKENIZER_SAMPLE = (
    "Onyx connects to company documents. 東京駅で午後三時に会いましょう。 "
    "def add(a, b):\n    return a + b"
)

# Two vectors that must be equal differ only by float noise. The looser
# padded-batch and norm bounds also allow for bf16 when the device is "auto".
SAME_VECTOR_MIN_COSINE = 0.9999
DIFFERENT_VECTOR_MAX_COSINE = 0.9999
PADDED_BATCH_MIN_COSINE = 0.999
UNIT_NORM_TOLERANCE = 5e-3
# A causal model gives exactly 0.0 here. The weakest bidirectional model
# (voyage-4-nano) measured 0.0485 in fp32.
BIDIRECTIONAL_MIN_FIRST_TOKEN_CHANGE = 1e-3


def _spec_id(spec: EmbeddingModelSpec) -> str:
    return spec.model_name.split("/")[-1]


def _cosine(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _prefix_for(spec: EmbeddingModelSpec, text_type: EmbedTextType) -> str:
    if text_type == EmbedTextType.QUERY:
        return spec.query_prefix
    return spec.passage_prefix


class _Embedder(Protocol):
    in_process: bool

    def embed(
        self,
        model_name: str,
        texts: list[str],
        text_type: EmbedTextType,
        prefix: str | None,
        expected_dim: int | None = None,
    ) -> FloatMatrix: ...


class _InProcessEmbedder:
    """Calls the model server's request handler in this process."""

    in_process = True

    def embed(
        self,
        model_name: str,
        texts: list[str],
        text_type: EmbedTextType,
        prefix: str | None,
        expected_dim: int | None = None,
    ) -> FloatMatrix:
        from model_server.encoders import process_embed_request
        from shared_configs.model_server_models import EmbedRequest

        request = EmbedRequest(
            texts=texts,
            model_name=model_name,
            max_context_length=MAX_CONTEXT_LENGTH,
            normalize_embeddings=True,
            text_type=text_type,
            manual_query_prefix=prefix if text_type == EmbedTextType.QUERY else None,
            manual_passage_prefix=(
                prefix if text_type == EmbedTextType.PASSAGE else None
            ),
            provider_type=None,
            expected_dim=expected_dim,
        )
        response = asyncio.run(process_embed_request(request))
        return np.asarray(response.embeddings, dtype=np.float64)


class _HttpEmbedder:
    """Sends each request through Onyx's EmbeddingModel to a running model server."""

    in_process = False

    def __init__(self, url: str) -> None:
        parts = urlsplit(url)
        if not parts.scheme or not parts.hostname:
            raise ValueError(
                f"{MODEL_SERVER_URL_ENV} must look like http://host:port, got {url!r}"
            )
        self._host = f"{parts.scheme}://{parts.hostname}"
        self._port = parts.port or 9000

    def embed(
        self,
        model_name: str,
        texts: list[str],
        text_type: EmbedTextType,
        prefix: str | None,
        expected_dim: int | None = None,
    ) -> FloatMatrix:
        from onyx.natural_language_processing.search_nlp_models import EmbeddingModel

        model = EmbeddingModel(
            server_host=self._host,
            server_port=self._port,
            model_name=model_name,
            normalize=True,
            query_prefix=prefix if text_type == EmbedTextType.QUERY else None,
            passage_prefix=prefix if text_type == EmbedTextType.PASSAGE else None,
            api_key=None,
            api_url=None,
            provider_type=None,
            model_dim=expected_dim,
        )
        # One batch, so the padded-batch check really pads.
        vectors = model.encode(
            texts,
            text_type,
            local_embedding_batch_size=len(texts),
            max_seq_length=MAX_CONTEXT_LENGTH,
        )
        return np.asarray(vectors, dtype=np.float64)


def _hide_accelerators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make torch report no CUDA and no MPS, like a CPU-only container."""
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)


@pytest.fixture(scope="module")
def embedder() -> Generator[_Embedder, None, None]:
    url = os.environ.get(MODEL_SERVER_URL_ENV, "").strip()
    if url:
        yield _HttpEmbedder(url)
        return

    device = os.environ.get(DEVICE_ENV, "cpu").strip().lower()
    if device not in ("cpu", "auto"):
        pytest.fail(f"{DEVICE_ENV} must be 'cpu' or 'auto', got {device!r}")
    with pytest.MonkeyPatch.context() as monkeypatch:
        if device == "cpu":
            _hide_accelerators(monkeypatch)
        yield _InProcessEmbedder()


@pytest.fixture(params=SELF_HOSTED_SPECS, ids=_spec_id)
def spec(request: pytest.FixtureRequest) -> EmbeddingModelSpec:
    return cast(EmbeddingModelSpec, request.param)


def _loaded_model(embedder: _Embedder, model_name: str) -> "SentenceTransformer":
    """The SentenceTransformer that the model server loaded for ``model_name``.

    Only in-process mode has it. ``get_embedding_model`` is the model server's
    loader entry point (plan step B1.1); the embed call before it makes sure the
    real request path did the load.
    """
    if not embedder.in_process:
        pytest.skip("Needs the loaded model object; runs in in-process mode only.")
    embedder.embed(model_name, ["warm-up"], EmbedTextType.PASSAGE, None)

    from model_server.encoders import get_embedding_model

    return get_embedding_model(
        model_name=model_name, max_context_length=MAX_CONTEXT_LENGTH
    )


def _first_token_output(model: "SentenceTransformer", text: str) -> FloatMatrix:
    # A single input is never padded, so index 0 is the first real token.
    token_embeddings = model.encode(
        text, output_value="token_embeddings", convert_to_numpy=False
    )
    return np.asarray(token_embeddings[0].float().cpu().numpy(), dtype=np.float64)


def test_registry_gives_a_pinned_loader_spec(spec: EmbeddingModelSpec) -> None:
    assert get_local_model_spec(spec.model_name) == spec
    assert spec.hf_revision is not None and len(spec.hf_revision) == 40
    assert spec.model_name in GOLDEN_RED_PLANET_SCORES, (
        f"Add golden red-planet scores for {spec.model_name}."
    )


def test_vectors_have_registry_dim_and_unit_norm(
    spec: EmbeddingModelSpec, embedder: _Embedder
) -> None:
    for text_type in (EmbedTextType.QUERY, EmbedTextType.PASSAGE):
        vectors = embedder.embed(
            spec.model_name, SAMPLE_TEXTS, text_type, _prefix_for(spec, text_type)
        )
        assert vectors.shape == (len(SAMPLE_TEXTS), spec.model_dim), (
            f"{text_type.value}: got shape {vectors.shape}"
        )
        assert np.isfinite(vectors).all(), f"{text_type.value}: non-finite values"
        norms = np.linalg.norm(vectors, axis=1)
        assert np.allclose(norms, 1.0, atol=UNIT_NORM_TOLERANCE), (
            f"{text_type.value}: norms {norms.tolist()}"
        )


def test_prefix_is_applied(spec: EmbeddingModelSpec, embedder: _Embedder) -> None:
    checked = 0
    for text_type in (EmbedTextType.QUERY, EmbedTextType.PASSAGE):
        prefix = _prefix_for(spec, text_type)
        if not prefix:
            continue
        checked += 1
        with_prefix = embedder.embed(spec.model_name, [SHORT_TEXT], text_type, prefix)
        prefix_in_text = embedder.embed(
            spec.model_name, [prefix + SHORT_TEXT], text_type, None
        )
        bare = embedder.embed(spec.model_name, [SHORT_TEXT], text_type, None)

        same = _cosine(with_prefix[0], prefix_in_text[0])
        assert same >= SAME_VECTOR_MIN_COSINE, (
            f"{text_type.value}: the server did not prepend {prefix!r} "
            f"(cosine vs manual prefix {same:.6f})"
        )
        different = _cosine(with_prefix[0], bare[0])
        assert different < DIFFERENT_VECTOR_MAX_COSINE, (
            f"{text_type.value}: the prefix {prefix!r} had no effect "
            f"(cosine vs bare text {different:.6f})"
        )
    if checked == 0:
        pytest.skip(f"{spec.model_name} uses no prefixes.")


def test_query_and_passage_vectors(
    spec: EmbeddingModelSpec, embedder: _Embedder
) -> None:
    query = embedder.embed(
        spec.model_name, [SHORT_TEXT], EmbedTextType.QUERY, spec.query_prefix
    )
    passage = embedder.embed(
        spec.model_name, [SHORT_TEXT], EmbedTextType.PASSAGE, spec.passage_prefix
    )
    similarity = _cosine(query[0], passage[0])
    if spec.query_prefix == spec.passage_prefix:
        # granite: symmetric model, no prefixes.
        assert similarity >= SAME_VECTOR_MIN_COSINE, (
            f"QUERY and PASSAGE should be identical, cosine {similarity:.6f}"
        )
    else:
        assert similarity < DIFFERENT_VECTOR_MAX_COSINE, (
            f"QUERY and PASSAGE should differ, cosine {similarity:.6f}"
        )


def test_attention_is_bidirectional(
    spec: EmbeddingModelSpec, embedder: _Embedder
) -> None:
    model = _loaded_model(embedder, spec.model_name)
    assert model.default_prompt_name is None, (
        f"default_prompt_name={model.default_prompt_name!r} would add a second "
        "prompt on top of the Onyx prefix"
    )

    prefix = spec.passage_prefix
    first_a = _first_token_output(
        model, prefix + "The quick brown fox jumps over the lazy dog"
    )
    first_b = _first_token_output(
        model, prefix + "The quick brown fox jumps over the lazy cat"
    )
    change = float(np.max(np.abs(first_a - first_b)))
    assert change > BIDIRECTIONAL_MIN_FIRST_TOKEN_CHANGE, (
        f"Changing the last token did not change the first token's output "
        f"(max change {change:.3g}). The model runs with causal attention."
    )


def test_padded_batch_matches_single_inputs(
    spec: EmbeddingModelSpec, embedder: _Embedder
) -> None:
    prefix = spec.passage_prefix
    passage = EmbedTextType.PASSAGE
    short_alone = embedder.embed(spec.model_name, [SHORT_TEXT], passage, prefix)[0]
    longer_alone = embedder.embed(spec.model_name, [LONGER_TEXT], passage, prefix)[0]
    for texts in ([SHORT_TEXT, LONGER_TEXT], [LONGER_TEXT, SHORT_TEXT]):
        batch = embedder.embed(spec.model_name, texts, passage, prefix)
        short_in_batch = batch[texts.index(SHORT_TEXT)]
        longer_in_batch = batch[texts.index(LONGER_TEXT)]
        short_similarity = _cosine(short_alone, short_in_batch)
        longer_similarity = _cosine(longer_alone, longer_in_batch)
        assert short_similarity >= PADDED_BATCH_MIN_COSINE, (
            f"Padding changed the short input: cosine {short_similarity:.6f}"
        )
        assert longer_similarity >= PADDED_BATCH_MIN_COSINE, (
            f"Batching changed the longer input: cosine {longer_similarity:.6f}"
        )


def test_long_input_is_truncated(spec: EmbeddingModelSpec, embedder: _Embedder) -> None:
    prefix = spec.passage_prefix
    passage = EmbedTextType.PASSAGE
    long_vector = embedder.embed(spec.model_name, [LONG_TEXT], passage, prefix)
    longer_vector = embedder.embed(
        spec.model_name, [LONG_TEXT + UNRELATED_TAIL], passage, prefix
    )
    for vectors in (long_vector, longer_vector):
        assert vectors.shape == (1, spec.model_dim)
        assert np.isfinite(vectors).all()
    similarity = _cosine(long_vector[0], longer_vector[0])
    assert similarity >= SAME_VECTOR_MIN_COSINE, (
        f"Text past the context window changed the embedding (cosine "
        f"{similarity:.6f}); the input was not cut at {MAX_CONTEXT_LENGTH} tokens."
    )


def test_golden_red_planet_scores(
    spec: EmbeddingModelSpec, embedder: _Embedder
) -> None:
    golden = np.asarray(GOLDEN_RED_PLANET_SCORES[spec.model_name], dtype=np.float64)
    query = embedder.embed(
        spec.model_name, [RED_PLANET_QUERY], EmbedTextType.QUERY, spec.query_prefix
    )[0]
    docs = embedder.embed(
        spec.model_name,
        list(RED_PLANET_DOCS),
        EmbedTextType.PASSAGE,
        spec.passage_prefix,
    )
    scores = docs @ query / (np.linalg.norm(docs, axis=1) * np.linalg.norm(query))
    assert int(np.argmax(scores)) == RED_PLANET_ANSWER_INDEX, (
        f"The Mars passage did not rank first: {np.round(scores, 4).tolist()}"
    )
    assert np.allclose(scores, golden, atol=GOLDEN_TOLERANCE), (
        f"scores {np.round(scores, 4).tolist()} differ from the fp32 golden "
        f"{golden.tolist()} by more than {GOLDEN_TOLERANCE}"
    )


def test_api_tokenizer_is_the_model_tokenizer(spec: EmbeddingModelSpec) -> None:
    """The API server counts tokens with the model's own tokenizer, not nomic's."""
    from tokenizers import Tokenizer

    from onyx.natural_language_processing.utils import get_tokenizer

    api_ids = get_tokenizer(model_name=spec.model_name, provider_type=None).encode(
        TOKENIZER_SAMPLE
    )
    model_ids = (
        Tokenizer.from_pretrained(spec.model_name, revision=spec.hf_revision or "main")
        .encode(TOKENIZER_SAMPLE, add_special_tokens=False)
        .ids
    )
    nomic_ids = (
        Tokenizer.from_pretrained(NOMIC_MODEL_NAME)
        .encode(TOKENIZER_SAMPLE, add_special_tokens=False)
        .ids
    )
    assert api_ids == model_ids, "The API tokenizer is not the model's own tokenizer."
    assert api_ids != nomic_ids, "The API tokenizer fell back to the nomic tokenizer."


def test_legacy_nomic_model_still_loads(embedder: _Embedder) -> None:
    nomic = find_embedding_model_spec(None, NOMIC_MODEL_NAME)
    assert nomic is not None and nomic.status == EmbeddingModelStatus.LEGACY
    # Legacy names keep the legacy load path.
    assert get_local_model_spec(NOMIC_MODEL_NAME) is None

    for text_type in (EmbedTextType.QUERY, EmbedTextType.PASSAGE):
        vectors = embedder.embed(
            NOMIC_MODEL_NAME, SAMPLE_TEXTS, text_type, _prefix_for(nomic, text_type)
        )
        assert vectors.shape == (len(SAMPLE_TEXTS), 768)
        assert np.isfinite(vectors).all()
        assert np.allclose(
            np.linalg.norm(vectors, axis=1), 1.0, atol=UNIT_NORM_TOLERANCE
        )


def test_custom_voyage_model_added_before_the_registry_keeps_its_vectors(
    embedder: _Embedder,
) -> None:
    """Before the registry, an admin could add voyageai/voyage-4-nano with "Add
    Custom Model". The plain load gives 1024-dim vectors, so a working row
    stores 1024. The API sends the stored dim, and the model server keeps the
    plain load for it, so the existing index keeps working."""
    voyage = get_local_model_spec("voyageai/voyage-4-nano")
    assert voyage is not None and voyage.model_dim == 2048

    custom_vectors = embedder.embed(
        voyage.model_name,
        SAMPLE_TEXTS,
        EmbedTextType.PASSAGE,
        None,
        expected_dim=1024,
    )
    assert custom_vectors.shape == (len(SAMPLE_TEXTS), 1024)
    assert np.isfinite(custom_vectors).all()

    registry_vectors = embedder.embed(
        voyage.model_name,
        SAMPLE_TEXTS,
        EmbedTextType.PASSAGE,
        voyage.passage_prefix,
        expected_dim=voyage.model_dim,
    )
    assert registry_vectors.shape == (len(SAMPLE_TEXTS), voyage.model_dim)
