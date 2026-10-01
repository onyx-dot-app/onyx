"""Live checks for the SELECTABLE cloud embedding models, through Onyx's client code.

Opt in with ``ONYX_RUN_CLOUD_EMBEDDING_TESTS=true``. Each case also needs its
provider env var (see ``provider_env.py``); a case without it is skipped.
These calls cost money (well under 0.10 USD for a full run).

Every call goes through ``EmbeddingModel.encode``, the same path that indexing
and query embedding use. Cloud models never touch the model server, so no Onyx
service has to run.
"""

import functools
from typing import cast

import numpy as np
import numpy.typing as npt
import pytest

from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbeddingProvider, EmbedTextType
from tests.manual.embedding_models.provider_env import (
    provider_api_key,
    provider_env_name,
)
from tests.manual.gates import CLOUD_EMBEDDING_GATE, manual_suite

pytestmark = manual_suite(CLOUD_EMBEDDING_GATE)

FloatMatrix = npt.NDArray[np.float64]

CLOUD_SPECS: tuple[EmbeddingModelSpec, ...] = tuple(
    spec
    for spec in selectable_embedding_model_specs()
    if spec.provider_type is not None
)

# More passages than one provider request takes (Cohere 96 texts per call;
# the Vertex single-content models take 1), so Onyx must split and re-join.
PASSAGE_COUNT_BY_PROVIDER: dict[EmbeddingProvider, int] = {
    EmbeddingProvider.COHERE: 130,
    EmbeddingProvider.OPENAI: 130,
    EmbeddingProvider.GOOGLE: 12,
}
# Also run with small outer batches, which uses Onyx's thread pool.
SMALL_API_BATCH_SIZE = 5
# Providers whose API takes an input type, so QUERY and PASSAGE must differ.
PROVIDERS_WITH_INPUT_TYPE = frozenset(
    {EmbeddingProvider.COHERE, EmbeddingProvider.GOOGLE}
)

ORDER_MIN_COSINE = 0.99
SAME_TEXT_MAX_COSINE_ACROSS_TYPES = 0.99999

TOPICAL_PASSAGES: dict[str, str] = {
    "pto": "Full-time employees accrue 1.5 days of paid time off per month, up to "
    "30 days per year. Unused vacation days roll over until the end of March.",
    "expenses": "Expense reports and receipts for reimbursement must be submitted "
    "in the finance portal within 30 days of the purchase date, otherwise they "
    "will be rejected.",
    "vpn": "To reach internal services from home, install the corporate VPN "
    "client, sign in with SSO, and approve the push notification on your phone.",
    "k8s": "Our Kubernetes clusters use the cluster autoscaler; worker nodes are "
    "added when pending pods cannot be scheduled because of CPU or memory "
    "pressure.",
    "retirement": "The company matches 401(k) retirement contributions dollar for "
    "dollar up to 4% of salary, vesting immediately.",
    "parking": "Visitors can park in lot B; badge holders may use the underground "
    "garage after 6pm.",
    "oncall": "The on-call engineer must acknowledge PagerDuty alerts within 5 "
    "minutes and open an incident channel for any SEV1.",
    "laptop": "Replacement laptops are issued every three years; request one "
    "through the IT helpdesk with your asset tag.",
}
QUERY_ANSWERS: dict[str, str] = {
    "How many vacation days do I get each year?": "pto",
    "deadline to hand in receipts to get my money back": "expenses",
    "how do I access internal tools while working remotely": "vpn",
    "how do we add more machines when pods can't be scheduled": "k8s",
    "does my employer match my retirement savings": "retirement",
    # German: "How do I connect to the company VPN from home?"
    "Wie verbinde ich mich von zu Hause mit dem Firmen-VPN?": "vpn",
}
QUERIES: tuple[str, ...] = tuple(QUERY_ANSWERS)


def _corpus(total: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(ids, texts): the topical passages, then distinct filler up to ``total``."""
    ids = list(TOPICAL_PASSAGES)
    texts = [TOPICAL_PASSAGES[doc_id] for doc_id in ids]
    filler_index = 0
    while len(texts) < total:
        texts.append(
            f"Cafeteria note #{filler_index}: on day {filler_index} of the rotation "
            "the kitchen serves soup, salad and a seasonal dessert number "
            f"{filler_index % 7}."
        )
        ids.append(f"filler-{filler_index}")
        filler_index += 1
    return tuple(ids), tuple(texts)


def _spec_id(spec: EmbeddingModelSpec) -> str:
    provider = spec.provider_type.value if spec.provider_type else "self-hosted"
    return f"{provider}-{spec.model_name}"


def _provider(spec: EmbeddingModelSpec) -> EmbeddingProvider:
    if spec.provider_type is None:
        raise ValueError(f"{spec.model_name} is not a cloud model")
    return spec.provider_type


def _require_api_key(spec: EmbeddingModelSpec) -> str:
    provider = _provider(spec)
    api_key = provider_api_key(provider)
    if api_key is None:
        pytest.skip(f"{provider_env_name(provider)} is not set.")
    return api_key


def _row_cosines(a: FloatMatrix, b: FloatMatrix) -> npt.NDArray[np.float64]:
    return np.sum(a * b, axis=1) / (
        np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
    )


def _cosine_matrix(queries: FloatMatrix, passages: FloatMatrix) -> FloatMatrix:
    q = queries / np.linalg.norm(queries, axis=1, keepdims=True)
    p = passages / np.linalg.norm(passages, axis=1, keepdims=True)
    return q @ p.T


@functools.cache
def _encode(
    spec: EmbeddingModelSpec,
    texts: tuple[str, ...],
    text_type: EmbedTextType,
    api_batch_size: int | None = None,
    reduced_dimension: int | None = None,
) -> FloatMatrix:
    """Embed through ``EmbeddingModel.encode``. Cached, so tests share API calls."""
    from onyx.natural_language_processing.search_nlp_models import EmbeddingModel

    model = EmbeddingModel(
        # Not used for cloud providers; they bypass the model server.
        server_host="localhost",
        server_port=9000,
        model_name=spec.model_name,
        normalize=spec.normalize,
        query_prefix=None,
        passage_prefix=None,
        api_key=_require_api_key(spec),
        api_url=None,
        provider_type=_provider(spec),
        reduced_dimension=reduced_dimension,
    )
    if api_batch_size is None:
        vectors = model.encode(list(texts), text_type)
    else:
        vectors = model.encode(
            list(texts), text_type, api_embedding_batch_size=api_batch_size
        )
    result = np.asarray(vectors, dtype=np.float64)
    result.flags.writeable = False
    return result


def _assert_valid_vectors(
    vectors: FloatMatrix, count: int, dim: int, label: str
) -> None:
    assert vectors.shape == (count, dim), f"{label}: got shape {vectors.shape}"
    assert np.isfinite(vectors).all(), f"{label}: non-finite values"
    zero_rows = np.flatnonzero(np.linalg.norm(vectors, axis=1) == 0)
    assert zero_rows.size == 0, f"{label}: zero vectors at rows {zero_rows.tolist()}"


def _assert_ranking(
    queries: FloatMatrix, passages: FloatMatrix, passage_ids: tuple[str, ...]
) -> None:
    scores = _cosine_matrix(queries, passages)
    misses: list[str] = []
    for row, query in enumerate(QUERIES):
        best = int(np.argmax(scores[row]))
        expected = QUERY_ANSWERS[query]
        if passage_ids[best] != expected:
            misses.append(
                f"{query!r}: top-1 {passage_ids[best]} ({scores[row, best]:.3f}), "
                f"expected {expected} "
                f"({scores[row, passage_ids.index(expected)]:.3f})"
            )
    assert not misses, "Wrong top-1 passage:\n" + "\n".join(misses)


@pytest.fixture(params=CLOUD_SPECS, ids=_spec_id)
def cloud_spec(request: pytest.FixtureRequest) -> EmbeddingModelSpec:
    spec = cast(EmbeddingModelSpec, request.param)
    _require_api_key(spec)
    return spec


def test_vectors_have_registry_dim(cloud_spec: EmbeddingModelSpec) -> None:
    passage_count = PASSAGE_COUNT_BY_PROVIDER[_provider(cloud_spec)]
    _, passages = _corpus(passage_count)
    _assert_valid_vectors(
        _encode(cloud_spec, passages, EmbedTextType.PASSAGE),
        passage_count,
        cloud_spec.model_dim,
        "passages",
    )
    _assert_valid_vectors(
        _encode(cloud_spec, QUERIES, EmbedTextType.QUERY),
        len(QUERIES),
        cloud_spec.model_dim,
        "queries",
    )


def test_batches_above_provider_limit_keep_order(
    cloud_spec: EmbeddingModelSpec,
) -> None:
    passage_count = PASSAGE_COUNT_BY_PROVIDER[_provider(cloud_spec)]
    _, passages = _corpus(passage_count)
    default_batches = _encode(cloud_spec, passages, EmbedTextType.PASSAGE)
    small_batches = _encode(
        cloud_spec, passages, EmbedTextType.PASSAGE, SMALL_API_BATCH_SIZE
    )
    _assert_valid_vectors(
        small_batches, passage_count, cloud_spec.model_dim, "small batches"
    )
    similarities = _row_cosines(default_batches, small_batches)
    bad_rows = np.flatnonzero(similarities < ORDER_MIN_COSINE)
    assert bad_rows.size == 0, (
        "The same text got a different vector at the same position, so batching "
        f"changed the order. Rows: {bad_rows.tolist()}, cosines: "
        f"{np.round(similarities[bad_rows], 4).tolist()}"
    )


def test_semantic_ranking(cloud_spec: EmbeddingModelSpec) -> None:
    passage_count = PASSAGE_COUNT_BY_PROVIDER[_provider(cloud_spec)]
    passage_ids, passages = _corpus(passage_count)
    _assert_ranking(
        _encode(cloud_spec, QUERIES, EmbedTextType.QUERY),
        _encode(cloud_spec, passages, EmbedTextType.PASSAGE),
        passage_ids,
    )


@pytest.mark.parametrize(
    "spec",
    [spec for spec in CLOUD_SPECS if spec.provider_type in PROVIDERS_WITH_INPUT_TYPE],
    ids=_spec_id,
)
def test_query_differs_from_passage(spec: EmbeddingModelSpec) -> None:
    _require_api_key(spec)
    text = (QUERIES[0],)
    as_query = _encode(spec, text, EmbedTextType.QUERY)
    as_passage = _encode(spec, text, EmbedTextType.PASSAGE)
    similarity = float(_row_cosines(as_query, as_passage)[0])
    assert similarity < SAME_TEXT_MAX_COSINE_ACROSS_TYPES, (
        "QUERY and PASSAGE vectors of the same text are identical "
        f"(cosine {similarity:.6f}); the text type was not sent."
    )


def _reduced_dimension_cases() -> list[tuple[EmbeddingModelSpec, int]]:
    return [
        (spec, dim)
        for spec in CLOUD_SPECS
        if spec.supports_reduced_dimension
        for dim in (spec.model_dim // 4, spec.model_dim // 2)
    ]


@pytest.mark.parametrize(
    ("spec", "reduced_dimension"),
    _reduced_dimension_cases(),
    ids=[f"{_spec_id(spec)}-{dim}" for spec, dim in _reduced_dimension_cases()],
)
def test_reduced_dimension(spec: EmbeddingModelSpec, reduced_dimension: int) -> None:
    _require_api_key(spec)
    passage_ids = tuple(TOPICAL_PASSAGES)
    passages = tuple(TOPICAL_PASSAGES[doc_id] for doc_id in passage_ids)
    passage_vectors = _encode(
        spec, passages, EmbedTextType.PASSAGE, reduced_dimension=reduced_dimension
    )
    query_vectors = _encode(
        spec, QUERIES, EmbedTextType.QUERY, reduced_dimension=reduced_dimension
    )
    _assert_valid_vectors(passage_vectors, len(passages), reduced_dimension, "passages")
    _assert_valid_vectors(query_vectors, len(QUERIES), reduced_dimension, "queries")
    _assert_ranking(query_vectors, passage_vectors, passage_ids)
