"""External dependency unit tests for the OpenAI/Anthropic available-models endpoints.

These tests hit the real OpenAI and Anthropic ``/v1/models`` endpoints, exercising
the ``/admin/llm/openai/available-models`` and ``/admin/llm/anthropic/available-models``
admin handlers end-to-end (minus auth — handlers are invoked directly with a mocked
user since auth is a separate concern already covered elsewhere).

OpenAI tests resolve their key via the shared ``@pytest.mark.secrets``
infrastructure (env var / ``.vscode/.env`` locally, AWS Secrets Manager in CI).
Anthropic has no ``TestSecret`` member yet, so its live tests are gated on the
``ANTHROPIC_API_KEY`` env var and skip when absent; migrate them to
``@pytest.mark.secrets`` if that secret is ever added.
"""

import os
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
from onyx.server.manage.llm.utils import extract_base_model_name
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.nightly

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
    "realtime",
    "transcribe",
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


# --------------------------- OpenAI ---------------------------------


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_openai_happy_path(
    db_session: Session, test_secrets: dict[TestSecret, str]
) -> None:
    """Hit the real OpenAI /v1/models endpoint and verify the result shape."""
    request = OpenAIModelsRequest(api_key=test_secrets[TestSecret.OPENAI_API_KEY])

    results = get_openai_available_models(request, MagicMock(), db_session)

    assert len(results) > 0, "Expected at least one model from OpenAI"
    assert any(r.name.startswith("gpt-") for r in results), (
        "Expected at least one gpt- model"
    )

    names = [r.name for r in results]
    assert names == sorted(names, key=str.lower), "Results should be sorted by name"

    name_set = set(names)
    for r in results:
        lower = r.name.lower()
        for excluded in _OPENAI_EXCLUDED_SUBSTRINGS:
            assert excluded not in lower, (
                f"Excluded category '{excluded}' leaked through for model {r.name}"
            )
        # Dated snapshots are only kept when no undated base model exists.
        base = extract_base_model_name(r.name)
        assert not (base and base in name_set), (
            f"Dated duplicate leaked through: {r.name}"
        )
        assert r.display_name, "display_name should be non-empty"
        assert r.max_input_tokens is None, (
            "OpenAI handler should leave max_input_tokens=None and rely on "
            "runtime litellm fallback"
        )

    assert any(r.supports_reasoning for r in results), (
        "Expected at least one reasoning-capable model (o-series / gpt-5)"
    )


def test_openai_auth_failure(db_session: Session) -> None:
    """Bogus key should raise OnyxError(VALIDATION_ERROR)."""
    request = OpenAIModelsRequest(api_key=_BOGUS_OPENAI_KEY)

    with pytest.raises(OnyxError) as exc_info:
        get_openai_available_models(request, MagicMock(), db_session)

    assert exc_info.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    assert "OpenAI" in exc_info.value.detail


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_openai_db_sync_when_provider_id_provided(
    db_session: Session,
    openai_provider_name: str,
    test_secrets: dict[TestSecret, str],
) -> None:
    """When provider_id is given, fetched models should be persisted to the DB."""
    real_key = test_secrets[TestSecret.OPENAI_API_KEY]
    provider = _make_openai_provider(db_session, openai_provider_name, real_key)

    request = OpenAIModelsRequest(api_key=real_key, provider_id=provider.id)
    results = get_openai_available_models(request, MagicMock(), db_session)
    assert len(results) > 0

    db_session.expire_all()
    persisted = fetch_existing_llm_provider(
        name=openai_provider_name, db_session=db_session
    )
    assert persisted is not None

    persisted_names = {mc.name for mc in persisted.model_configurations}
    fetched_names = {r.name for r in results}
    # All fetched names should be persisted; the original gpt-4o should still
    # exist (sync is additive — it does not drop pre-existing entries).
    assert fetched_names.issubset(persisted_names)
    assert "gpt-4o" in persisted_names


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_openai_masked_api_key_resolves(
    db_session: Session,
    openai_provider_name: str,
    test_secrets: dict[TestSecret, str],
) -> None:
    """Submitting the masked form of a stored key should still succeed."""
    real_key = test_secrets[TestSecret.OPENAI_API_KEY]
    provider = _make_openai_provider(db_session, openai_provider_name, real_key)

    masked = _mask_string(real_key)
    assert masked != real_key, "Mask should differ from raw key"

    request = OpenAIModelsRequest(api_key=masked, provider_id=provider.id)
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
    assert any(r.name.startswith("claude-") for r in results), (
        "Expected at least one claude- model"
    )

    for r in results:
        lower = r.name.lower()
        assert "claude-2" not in lower and "claude-instant" not in lower, (
            f"Obsolete model leaked through: {r.name}"
        )
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
