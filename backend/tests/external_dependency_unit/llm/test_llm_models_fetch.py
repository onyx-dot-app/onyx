"""External dependency unit tests for the dynamic available-models endpoints.

These tests hit real provider APIs, exercising the
``/admin/llm/{provider}/available-models`` admin handlers end-to-end (minus
auth — handlers are invoked directly with a mocked user since auth is a
separate concern already covered elsewhere). Their job is drift detection:
catching new model categories that leak through our filters, response-shape
changes, and pagination breakage that the mocked unit suite
(``tests/unit/onyx/server/manage/llm/test_fetch_models_api.py``) can't see.

Credentials per provider:

- **OpenAI / Bedrock**: keys resolve via the shared ``@pytest.mark.secrets``
  infrastructure (env var / ``.vscode/.env`` locally, AWS Secrets Manager in CI).
- **Anthropic**: no ``TestSecret`` member yet, so its live tests are gated on
  the ``ANTHROPIC_API_KEY`` env var and skip when absent; migrate them to
  ``@pytest.mark.secrets`` if that secret is ever added.
- **OpenRouter / OpenAI-compatible**: OpenRouter's ``/api/v1/models`` endpoint
  is public, so these run keyless. The generic OpenAI-compatible handler is
  pointed at OpenRouter as a stable, real OpenAI-compatible server.

Endpoints for self-hosted services (Ollama, LM Studio, Bifrost, LiteLLM proxy,
Nebius) have no hosted catalog to drift against and are covered by the mocked
unit suite only.
"""

import os
from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import (
    fetch_existing_llm_provider,
    remove_llm_provider,
    upsert_llm_provider,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.api import (
    _mask_string,
    get_anthropic_available_models,
    get_bedrock_available_models,
    get_openai_available_models,
    get_openai_compatible_server_available_models,
    get_openrouter_available_models,
)
from onyx.server.manage.llm.models import (
    AnthropicModelsRequest,
    BedrockModelsRequest,
    LLMProviderUpsertRequest,
    LLMProviderView,
    ModelConfigurationUpsertRequest,
    OpenAICompatibleModelsRequest,
    OpenAIModelsRequest,
    OpenRouterModelsRequest,
)
from onyx.server.manage.llm.utils import NON_LLM_PATTERNS, extract_base_model_name
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.nightly

_ANTHROPIC_KEY_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY"))

_BOGUS_OPENAI_KEY = "sk-not-a-real-openai-key-aaaaaaaaaaaaaaaaaaaaaaaa"
_BOGUS_ANTHROPIC_KEY = "sk-ant-not-a-real-key-aaaaaaaaaaaaaaaaaaaaaaaaaa"

_OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

# Same region as test_bedrock.py — where the test bearer token is provisioned.
_BEDROCK_REGION = "us-west-2"

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


# --------------------------- Bedrock ---------------------------------


def _make_bedrock_provider(
    db_session: Session, name: str, bearer_token: str
) -> LLMProviderView:
    return upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=LlmProviderNames.BEDROCK,
            custom_config={
                "AWS_REGION_NAME": _BEDROCK_REGION,
                "AWS_BEARER_TOKEN_BEDROCK": bearer_token,
            },
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="anthropic.claude-3-5-sonnet-20241022-v2:0",
                    is_visible=True,
                    supports_image_input=True,
                )
            ],
        ),
        db_session=db_session,
    )


@pytest.fixture
def bedrock_provider_name(db_session: Session) -> Generator[str, None, None]:
    name = f"test-bedrock-fetch-{uuid4().hex[:8]}"
    yield name
    db_session.rollback()
    _cleanup_provider(db_session, name)


@pytest.mark.secrets(TestSecret.BEDROCK_API_KEY)
def test_bedrock_happy_path(
    db_session: Session, test_secrets: dict[TestSecret, str]
) -> None:
    """List real Bedrock foundation models via bearer token and verify the shape."""
    request = BedrockModelsRequest(
        aws_region_name=_BEDROCK_REGION,
        aws_bearer_token_bedrock=test_secrets[TestSecret.BEDROCK_API_KEY],
    )

    results = get_bedrock_available_models(request, MagicMock(), db_session)

    assert len(results) > 0, "Expected at least one model from Bedrock"
    assert any("anthropic." in r.name for r in results), (
        f"Expected at least one Anthropic model in {_BEDROCK_REGION}"
    )

    names = [r.name for r in results]
    assert names == sorted(names, reverse=True), (
        "Bedrock results should be sorted descending by model id"
    )

    for r in results:
        lower = r.name.lower()
        for pattern in NON_LLM_PATTERNS:
            assert pattern not in lower, f"Non-LLM model leaked through: {r.name}"
        assert r.display_name, f"display_name should be non-empty for {r.name}"
        assert r.max_input_tokens > 0


@pytest.mark.secrets(TestSecret.BEDROCK_API_KEY)
def test_bedrock_db_sync_when_provider_id_provided(
    db_session: Session,
    bedrock_provider_name: str,
    test_secrets: dict[TestSecret, str],
) -> None:
    """When provider_id is given, fetched models should be persisted to the DB."""
    token = test_secrets[TestSecret.BEDROCK_API_KEY]
    provider = _make_bedrock_provider(db_session, bedrock_provider_name, token)

    request = BedrockModelsRequest(
        aws_region_name=_BEDROCK_REGION,
        aws_bearer_token_bedrock=token,
        provider_id=provider.id,
    )
    results = get_bedrock_available_models(request, MagicMock(), db_session)
    assert len(results) > 0

    db_session.expire_all()
    persisted = fetch_existing_llm_provider(
        name=bedrock_provider_name, db_session=db_session
    )
    assert persisted is not None

    persisted_names = {mc.name for mc in persisted.model_configurations}
    fetched_names = {r.name for r in results}
    # All fetched names should be persisted; the seed model should still
    # exist (sync is additive — it does not drop pre-existing entries).
    assert fetched_names.issubset(persisted_names)
    assert "anthropic.claude-3-5-sonnet-20241022-v2:0" in persisted_names


# --------------------------- OpenRouter ------------------------------


def test_openrouter_happy_path(db_session: Session) -> None:
    """Hit the real (public) OpenRouter /models endpoint and verify the shape.

    OpenRouter's models endpoint requires no auth; an empty api_key means the
    handler sends no Authorization header, so this runs keyless. If this ever
    starts failing with an auth error, OpenRouter has started enforcing keys —
    add an OPENROUTER_API_KEY TestSecret and gate the test on it.
    """
    request = OpenRouterModelsRequest(api_base=_OPENROUTER_API_BASE, api_key="")

    results = get_openrouter_available_models(request, MagicMock(), db_session)

    assert len(results) > 0, "Expected at least one model from OpenRouter"
    assert any(r.name.startswith("openai/") for r in results)
    assert any(r.name.startswith("anthropic/") for r in results)

    names = [r.name for r in results]
    assert names == sorted(names, key=str.lower), "Results should be sorted by name"

    for r in results:
        assert "embedding" not in r.name.lower(), (
            f"Embedding model leaked through: {r.name}"
        )
        assert r.display_name, f"display_name should be non-empty for {r.name}"
        assert r.max_input_tokens is None or r.max_input_tokens > 0, (
            "context_length of 0 should be normalized to None"
        )
        # Vendor prefixes are stripped from display names ("OpenAI: GPT-4o" → "GPT-4o")
        if r.name.startswith("openai/"):
            assert not r.display_name.lower().startswith("openai:"), (
                f"Vendor prefix not stripped from display name: {r.display_name}"
            )


# ----------------------- OpenAI-compatible ---------------------------


def test_openai_compatible_happy_path_against_openrouter(db_session: Session) -> None:
    """Run the generic OpenAI-compatible handler against a real live server.

    OpenRouter's public /api/v1/models endpoint doubles as a stable, real
    OpenAI-compatible server — this exercises URL construction (api_base
    already ending in /v1) and response parsing without needing any secret.
    """
    request = OpenAICompatibleModelsRequest(api_base=_OPENROUTER_API_BASE)

    results = get_openai_compatible_server_available_models(
        request, MagicMock(), db_session
    )

    assert len(results) > 0, "Expected at least one model"

    names = [r.name for r in results]
    assert names == sorted(names, key=str.lower), "Results should be sorted by name"

    for r in results:
        assert "embedding" not in r.name.lower(), (
            f"Embedding model leaked through: {r.name}"
        )
        assert r.display_name, f"display_name should be non-empty for {r.name}"

    assert any(r.max_input_tokens for r in results), (
        "OpenRouter reports context_length; expected it mapped to max_input_tokens"
    )
    assert any(r.supports_reasoning for r in results), (
        "Expected at least one reasoning-capable model (o-series / deepseek-r1)"
    )
