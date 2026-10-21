"""Live checks for the SELECTABLE cloud embedding models.

Opt in with ONYX_RUN_CLOUD_EMBEDDING_TESTS=true. A model whose key env var is
unset (see provider_env.py) skips. A full run costs less than 0.10 USD. Calls
go through EmbeddingModel.encode, the path that indexing and queries use, so no
Onyx service has to run.
"""

import os

import numpy as np
import pytest

from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbedTextType
from tests.manual.embedding_models.provider_env import provider_api_key

pytestmark = pytest.mark.skipif(
    os.environ.get("ONYX_RUN_CLOUD_EMBEDDING_TESTS") != "true",
    reason="Set ONYX_RUN_CLOUD_EMBEDDING_TESTS=true to run.",
)

CLOUD_SPECS = [
    spec
    for spec in selectable_embedding_model_specs()
    if spec.provider_type is not None
]

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
# Filler first, so the topical passages come after the first provider request
# (Cohere takes 96 texts, Voyage 128, Gemini 2 one). If Onyx joins the provider
# responses in the wrong order, the ranking check fails.
PASSAGES = [
    f"Cafeteria note #{i}: the kitchen serves soup, salad and dessert number {i % 7}."
    for i in range(122)
] + list(TOPICAL_PASSAGES.values())


@pytest.mark.parametrize("spec", CLOUD_SPECS, ids=lambda spec: spec.model_name)
def test_embeds_in_order_with_registry_dim(spec: EmbeddingModelSpec) -> None:
    from onyx.natural_language_processing.search_nlp_models import EmbeddingModel

    provider = spec.provider_type
    assert provider is not None
    model = EmbeddingModel(
        # Not used: cloud models do not call the model server.
        server_host="localhost",
        server_port=9000,
        model_name=spec.model_name,
        normalize=spec.normalize,
        query_prefix=None,
        passage_prefix=None,
        api_key=provider_api_key(provider),
        api_url=None,
        provider_type=provider,
    )
    passages = np.asarray(model.encode(PASSAGES, EmbedTextType.PASSAGE))
    queries = np.asarray(model.encode(list(QUERY_ANSWERS), EmbedTextType.QUERY))
    for vectors, count in ((passages, len(PASSAGES)), (queries, len(QUERY_ANSWERS))):
        assert vectors.shape == (count, spec.model_dim)
        assert np.isfinite(vectors).all()
        assert (np.linalg.norm(vectors, axis=1) > 0).all()

    passages /= np.linalg.norm(passages, axis=1, keepdims=True)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    best = [PASSAGES[i] for i in (queries @ passages.T).argmax(axis=1)]
    assert best == [TOPICAL_PASSAGES[key] for key in QUERY_ANSWERS.values()]
