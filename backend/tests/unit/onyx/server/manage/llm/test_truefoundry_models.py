"""Tests for the TrueFoundry model fetcher.

The gateway's /models listing lives on the bare base (no `/v1`). Ids pass
through unchanged, non-chat ids are dropped, and capabilities come from the
LiteLLM catalog since the listing carries no metadata.
"""

from typing import cast
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.api import get_truefoundry_available_models
from onyx.server.manage.llm.models import (
    OpenAICompatibleFinalModelResponse,
    OpenAICompatibleModelsRequest,
)

_SAMPLE = {
    "object": "list",
    "data": [
        {"id": "openai-main/gpt-4o-mini", "object": "model", "owned_by": "openai-main"},
        {"id": "anthropic-main/claude-sonnet-4-5", "object": "model"},
        {"id": "openai-main/text-embedding-3-small", "object": "model"},
        {"id": "", "object": "model"},
    ],
}


def _fetch(
    payload: dict = _SAMPLE,
    api_base: str = "https://gateway.truefoundry.ai/",
) -> tuple[list[OpenAICompatibleFinalModelResponse], str]:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="k"),
        patch(
            "onyx.server.manage.llm.api._get_openai_compatible_models_response",
            return_value=payload,
        ) as mock_fetch,
        patch(
            "onyx.server.manage.llm.api.catalog_model_supports_image_input",
            side_effect=lambda model_id, _provider: "gpt-4o" in model_id,
        ),
        patch(
            "onyx.server.manage.llm.api.model_is_reasoning_model",
            side_effect=lambda model_id, _provider: "claude" in model_id,
        ),
    ):
        results = get_truefoundry_available_models(
            request=OpenAICompatibleModelsRequest(
                api_base=api_base, api_key="k", provider_id=None
            ),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
        return results, mock_fetch.call_args.kwargs["url"]


def test_models_url_is_the_bare_base_without_v1() -> None:
    _, url = _fetch()
    assert url == "https://gateway.truefoundry.ai/models"


def test_self_hosted_base_keeps_its_path() -> None:
    _, url = _fetch(api_base="https://acme.truefoundry.cloud/api/llm")
    assert url == "https://acme.truefoundry.cloud/api/llm/models"


def test_namespaced_ids_pass_through_and_non_chat_ids_are_dropped() -> None:
    results, _ = _fetch()
    assert [m.name for m in results] == [
        "anthropic-main/claude-sonnet-4-5",
        "openai-main/gpt-4o-mini",
    ]
    assert all(m.display_name == m.name for m in results)


def test_capabilities_come_from_the_catalog() -> None:
    by_name = {m.name: m for m in _fetch()[0]}
    assert by_name["openai-main/gpt-4o-mini"].supports_image_input is True
    assert by_name["openai-main/gpt-4o-mini"].supports_reasoning is False
    assert by_name["anthropic-main/claude-sonnet-4-5"].supports_reasoning is True
    # The listing carries no context length, so it resolves from the catalog later.
    assert all(m.max_input_tokens is None for m in by_name.values())


def test_empty_listing_raises() -> None:
    with pytest.raises(OnyxError):
        _fetch({"object": "list", "data": []})


def test_listing_without_chat_models_raises() -> None:
    with pytest.raises(OnyxError):
        _fetch({"data": [{"id": "openai-main/text-embedding-3-small"}]})
