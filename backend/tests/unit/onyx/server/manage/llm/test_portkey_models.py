"""Tests for the Portkey model fetcher.

Verifies the mapping from Portkey's OpenAI-shaped /v1/models response to Onyx
model configs: embedding models dropped, context length mapped, id-less entries
skipped, and results sorted by name.
"""

from typing import cast
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.manage.llm.api import get_portkey_available_models
from onyx.server.manage.llm.models import PortkeyModelsRequest

# Trimmed OpenAI-shaped /v1/models payload with a chat model, another chat model,
# an embedding model (must be dropped), and an id-less entry (must be skipped).
_SAMPLE = {
    "object": "list",
    "data": [
        {"id": "gpt-4o", "name": "GPT-4o", "context_length": 128000},
        {"id": "claude-sonnet-5", "name": "Claude Sonnet 5", "context_length": 200000},
        {"id": "text-embedding-3-large", "name": "Embedding", "context_length": 8191},
        {"id": "", "name": "no id"},
    ],
}


def _fetch(api_base: str = "https://api.portkey.ai/v1") -> dict:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="pk-key"),
        patch(
            "onyx.server.manage.llm.api._get_portkey_models_response",
            return_value=_SAMPLE,
        ),
    ):
        results = get_portkey_available_models(
            request=PortkeyModelsRequest(
                api_base=api_base,
                api_key="pk-key",
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
    assert set(by_name) == {"gpt-4o", "claude-sonnet-5"}


def test_context_length_mapped() -> None:
    by_name = _fetch()
    assert by_name["gpt-4o"].max_input_tokens == 128000
    assert by_name["claude-sonnet-5"].max_input_tokens == 200000


def test_display_name_from_payload() -> None:
    assert _fetch()["gpt-4o"].display_name == "GPT-4o"


def test_results_sorted_by_name() -> None:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="pk-key"),
        patch(
            "onyx.server.manage.llm.api._get_portkey_models_response",
            return_value=_SAMPLE,
        ),
    ):
        results = get_portkey_available_models(
            request=PortkeyModelsRequest(api_base="https://api.portkey.ai/v1"),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    assert [r.name for r in results] == ["claude-sonnet-5", "gpt-4o"]


def test_messages_mode_bare_base_still_fetches() -> None:
    # Messages mode passes the bare host; the fetcher still resolves /v1/models.
    by_name = _fetch(api_base="https://api.portkey.ai")
    assert set(by_name) == {"gpt-4o", "claude-sonnet-5"}
