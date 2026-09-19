"""Tests for the Cheaper Inference model fetcher.

Verifies the mapping from the gateway's OpenAI-shaped /v1/models response to
Onyx model configs: context length, embedding filtering, and sort order.
"""

from typing import cast
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.manage.llm.api import get_cheaperinference_available_models
from onyx.server.manage.llm.models import (
    CheaperInferenceFinalModelResponse,
    CheaperInferenceModelsRequest,
)

# Trimmed /v1/models payload. The gateway lists chat models plus an embedding
# entry, which must be dropped.
_SAMPLE = {
    "object": "list",
    "data": [
        {
            "id": "gpt-5-mini",
            "name": "GPT-5 Mini",
            "context_length": 400000,
        },
        {
            "id": "claude-opus-5",
            "context_length": 1000000,
        },
        {
            # no context length reported -> stays None
            "id": "glm-5.3-flash",
            "name": "GLM 5.3 Flash",
        },
        {
            # no id -> skipped
            "name": "Broken Entry",
            "context_length": 1000,
        },
        {
            "id": "text-embedding-3-small",
            "name": "Text Embedding 3 Small",
            "context_length": 8191,
        },
    ],
}


def _fetch() -> list[CheaperInferenceFinalModelResponse]:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="k"),
        patch(
            "onyx.server.manage.llm.api._get_cheaperinference_models_response",
            return_value=_SAMPLE,
        ),
    ):
        return get_cheaperinference_available_models(
            request=CheaperInferenceModelsRequest(
                api_base="https://api.cheaperinference.com/v1",
                api_key="k",
                provider_id=None,  # skip DB sync
            ),
            _=cast(User, None),
            db_session=cast(Session, None),
        )


def test_embedding_and_idless_entries_are_dropped() -> None:
    names = [m.name for m in _fetch()]
    assert "text-embedding-3-small" not in names
    assert names == ["claude-opus-5", "glm-5.3-flash", "gpt-5-mini"]


def test_context_length_mapped() -> None:
    by_name = {m.name: m for m in _fetch()}
    assert by_name["gpt-5-mini"].max_input_tokens == 400000
    assert by_name["claude-opus-5"].max_input_tokens == 1000000
    assert by_name["glm-5.3-flash"].max_input_tokens is None


def test_display_name_falls_back_to_model_id() -> None:
    by_name = {m.name: m for m in _fetch()}
    assert by_name["gpt-5-mini"].display_name == "GPT-5 Mini"
    # No `name` in the payload -> the id is used.
    assert by_name["claude-opus-5"].display_name == "claude-opus-5"
