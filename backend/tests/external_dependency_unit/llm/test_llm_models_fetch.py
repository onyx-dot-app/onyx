"""External dependency unit tests for the OpenAI/Anthropic available-models endpoints.

These tests hit the real OpenAI and Anthropic ``/v1/models`` endpoints, exercising
the new ``/admin/llm/openai/available-models`` and ``/admin/llm/anthropic/available-models``
admin handlers end-to-end (minus auth — handlers are invoked directly with a mocked user
since auth is a separate concern already covered elsewhere).

Required environment variables:
- ``OPENAI_API_KEY`` — required for OpenAI tests, otherwise skipped.
- ``ANTHROPIC_API_KEY`` — required for Anthropic tests, otherwise skipped.
"""

import os
import re
from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import upsert_llm_provider
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.api import _mask_string
from onyx.server.manage.llm.api import get_anthropic_available_models
from onyx.server.manage.llm.api import get_openai_available_models
from onyx.server.manage.llm.models import AnthropicModelsRequest
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.manage.llm.models import OpenAIModelsRequest

_OPENAI_KEY_AVAILABLE = bool(os.environ.get("OPENAI_API_KEY"))
_ANTHROPIC_KEY_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY"))

_BOGUS_OPENAI_KEY = "sk-not-a-real-openai-key-aaaaaaaaaaaaaaaaaaaaaaaa"
_BOGUS_ANTHROPIC_KEY = "sk-ant-not-a-real-key-aaaaaaaaaaaaaaaaaaaaaaaaaa"

# Categories that should never leak through the OpenAI filter.
_OPENAI_EXCLUDED_SUBSTRINGS = (
    "embed",
    "audio",
    "tts",
    "whisper",
    "dall-e",
    "moderation",
    "sora",
)


def _make_openai_provider(
    db_session: Session, name: str, api_key: str
) -> LLMProviderView:
    return upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=LlmProviderNames.OPENAI,
            api_key=api_key,
            api_key_changed=True,
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="gpt-4o", is_visible=True, supports_image_input=True
                )
            ],
        ),
        db_session=db_session,
    )


def _cleanup_provider(db_session: Session, name: str) -> None:
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)


@pytest.fixture
def openai_provider_name(db_session: Session) -> Generator[str, None, None]:
    name = f"test-openai-fetch-{uuid4().hex[:8]}"
    yield name
    db_session.rollback()
    _cleanup_provider(db_session, name)


@pytest.fixture
def anthropic_provider_name(db_session: Session) -> Generator[str, None, None]:
    name = f"test-anthropic-fetch-{uuid4().hex[:8]}"
    yield name
    db_session.rollback()
    _cleanup_provider(db_session, name)


# --------------------------- OpenAI ---------------------------------


@pytest.mark.skipif(
    not _OPENAI_KEY_AVAILABLE, reason="OPENAI_API_KEY not set in environment"
)
def test_openai_happy_path(db_session: Session) -> None:
    """Hit the real OpenAI /v1/models endpoint and verify the result shape."""
    request = OpenAIModelsRequest(api_key=os.environ["OPENAI_API_KEY"])

    results = get_openai_available_models(request, MagicMock(), db_session)

    assert len(results) > 0, "Expected at least one model from OpenAI"
    assert any(
        re.match(r"^gpt-", r.name) for r in results
    ), "Expected at least one ^gpt- model"

    names = [r.name for r in results]
    assert names == sorted(names, key=str.lower), "Results should be sorted by name"

    for r in results:
        lower = r.name.lower()
        for excluded in _OPENAI_EXCLUDED_SUBSTRINGS:
            assert (
                excluded not in lower
            ), f"Excluded category '{excluded}' leaked through for model {r.name}"
        # Date-stamped snapshots should be filtered out.
        assert not re.search(
            r"-\d{4}", r.name
        ), f"Date-stamped snapshot leaked through: {r.name}"
        assert r.display_name, "display_name should be non-empty"
        assert r.max_input_tokens is None, (
            "OpenAI handler should leave max_input_tokens=None and rely on "
            "runtime litellm fallback"
        )


def test_openai_auth_failure(db_session: Session) -> None:
    """Bogus key should raise OnyxError(VALIDATION_ERROR)."""
    request = OpenAIModelsRequest(api_key=_BOGUS_OPENAI_KEY)

    with pytest.raises(OnyxError) as exc_info:
        get_openai_available_models(request, MagicMock(), db_session)

    assert exc_info.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    assert "OpenAI" in exc_info.value.detail


@pytest.mark.skipif(
    not _OPENAI_KEY_AVAILABLE, reason="OPENAI_API_KEY not set in environment"
)
def test_openai_db_sync_when_provider_name_provided(
    db_session: Session, openai_provider_name: str
) -> None:
    """When provider_name is given, fetched models should be persisted to the DB."""
    real_key = os.environ["OPENAI_API_KEY"]
    _make_openai_provider(db_session, openai_provider_name, real_key)

    request = OpenAIModelsRequest(api_key=real_key, provider_name=openai_provider_name)
    results = get_openai_available_models(request, MagicMock(), db_session)
    assert len(results) > 0

    db_session.expire_all()
    provider = fetch_existing_llm_provider(
        name=openai_provider_name, db_session=db_session
    )
    assert provider is not None

    persisted_names = {mc.name for mc in provider.model_configurations}
    fetched_names = {r.name for r in results}
    # All fetched names should be persisted; the original gpt-4o should still
    # exist (sync is additive — it does not drop pre-existing entries).
    assert fetched_names.issubset(persisted_names)
    assert "gpt-4o" in persisted_names


@pytest.mark.skipif(
    not _OPENAI_KEY_AVAILABLE, reason="OPENAI_API_KEY not set in environment"
)
def test_openai_masked_api_key_resolves(
    db_session: Session, openai_provider_name: str
) -> None:
    """Submitting the masked form of a stored key should still succeed."""
    real_key = os.environ["OPENAI_API_KEY"]
    _make_openai_provider(db_session, openai_provider_name, real_key)

    masked = _mask_string(real_key)
    assert masked != real_key, "Mask should differ from raw key"

    request = OpenAIModelsRequest(api_key=masked, provider_name=openai_provider_name)
    results = get_openai_available_models(request, MagicMock(), db_session)
    assert len(results) > 0


# --------------------------- Anthropic ------------------------------


@pytest.mark.skipif(
    not _ANTHROPIC_KEY_AVAILABLE, reason="ANTHROPIC_API_KEY not set in environment"
)
def test_anthropic_happy_path(db_session: Session) -> None:
    """Hit the real Anthropic /v1/models endpoint and verify the result shape."""
    request = AnthropicModelsRequest(api_key=os.environ["ANTHROPIC_API_KEY"])

    results = get_anthropic_available_models(request, MagicMock(), db_session)

    assert len(results) > 0, "Expected at least one model from Anthropic"
    assert any(
        re.match(r"^claude-", r.name) for r in results
    ), "Expected at least one ^claude- model"

    for r in results:
        assert r.display_name, f"display_name should be non-empty for {r.name}"
        assert r.max_input_tokens is None, (
            "Anthropic handler should leave max_input_tokens=None and rely on "
            "runtime litellm fallback"
        )

    names = [r.name for r in results]
    assert names == sorted(names, key=str.lower), "Results should be sorted by name"


def test_anthropic_auth_failure(db_session: Session) -> None:
    """Bogus key should raise OnyxError(VALIDATION_ERROR)."""
    request = AnthropicModelsRequest(api_key=_BOGUS_ANTHROPIC_KEY)

    with pytest.raises(OnyxError) as exc_info:
        get_anthropic_available_models(request, MagicMock(), db_session)

    assert exc_info.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    assert "Anthropic" in exc_info.value.detail
