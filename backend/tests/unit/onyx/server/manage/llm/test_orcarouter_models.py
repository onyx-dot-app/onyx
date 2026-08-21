"""Tests for the OrcaRouter model fetcher.

Verifies the mapping from OrcaRouter's OpenAI-shaped /v1/models response to Onyx
model configs: embedding models dropped, context length mapped, id-less entries
skipped, and results sorted by name.
"""

from typing import cast
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.manage.llm.api import get_orcarouter_available_models
from onyx.server.manage.llm.models import OrcaRouterModelsRequest

# Trimmed OpenAI-shaped /v1/models payload with two chat models, an embedding
# model (must be dropped), and an id-less entry (must be skipped).
_SAMPLE = {
    "object": "list",
    "data": [
        {"id": "orcarouter/fusion", "name": "OrcaRouter Fusion", "context_length": 1000000},
        {"id": "orcarouter/fusion-mini", "name": "OrcaRouter Fusion Mini", "context_length": 200000},
        {"id": "text-embedding-3-large", "name": "Embedding", "context_length": 8191},
        {"id": "", "name": "no id"},
    ],
}


def _fetch(api_base: str = "https://api.orcarouter.ai/v1") -> dict:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="sk-orca-key"),
        patch(
            "onyx.server.manage.llm.api._get_orcarouter_models_response",
            return_value=_SAMPLE,
        ),
    ):
        results = get_orcarouter_available_models(
            request=OrcaRouterModelsRequest(
                api_base=api_base,
                api_key="sk-orca-key",
                provider_id=None,  # skip DB sync
            ),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    return {r.name: r for r in results}


def test_embedding_and_idless_entries_dropped() -> None:
    by_name = _fetch()
    assert "text-embedding-3-large" not in by_name
    # Only the two chat models remain (embedding + id-less entry dropped).
    assert set(by_name) == {"orcarouter/fusion", "orcarouter/fusion-mini"}


def test_context_length_mapped() -> None:
    by_name = _fetch()
    assert by_name["orcarouter/fusion"].max_input_tokens == 1000000
    assert by_name["orcarouter/fusion-mini"].max_input_tokens == 200000


def test_display_name_from_payload() -> None:
    assert _fetch()["orcarouter/fusion"].display_name == "OrcaRouter Fusion"


def test_results_sorted_by_name() -> None:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="sk-orca-key"),
        patch(
            "onyx.server.manage.llm.api._get_orcarouter_models_response",
            return_value=_SAMPLE,
        ),
    ):
        results = get_orcarouter_available_models(
            request=OrcaRouterModelsRequest(api_base="https://api.orcarouter.ai/v1"),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    assert [r.name for r in results] == [
        "orcarouter/fusion",
        "orcarouter/fusion-mini",
    ]


def test_bare_base_still_fetches() -> None:
    # A base without /v1 still resolves /v1/models.
    by_name = _fetch(api_base="https://api.orcarouter.ai")
    assert set(by_name) == {"orcarouter/fusion", "orcarouter/fusion-mini"}
