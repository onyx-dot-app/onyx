"""A computed context limit must never be persisted as if it were an admin override.

`ModelConfigurationView.from_model` serves `stored or get_max_input_tokens(...)`, and the
admin UI round-trips whatever it fetched back into the next save. Persisting that resolved
number pins the model to whatever LiteLLM knew at the time, because
`get_max_input_tokens_from_llm_provider` always prefers the stored value.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.model_configs import (
    GEN_AI_MODEL_FALLBACK_MAX_TOKENS,
    GEN_AI_NUM_RESERVED_OUTPUT_TOKENS,
)
from onyx.db.llm import (
    fetch_existing_llm_provider,
    remove_llm_provider,
    upsert_llm_provider,
)
from onyx.db.models import ModelConfiguration
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_capabilities import get_max_input_tokens
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)

# A deployment name LiteLLM does not know, so the lookup lands on the fallback.
_UNKNOWN_MODEL = "gpt-5.6-not-a-real-deployment"
_FALLBACK_RESOLVED = (
    GEN_AI_MODEL_FALLBACK_MAX_TOKENS - GEN_AI_NUM_RESERVED_OUTPUT_TOKENS
)


def _upsert(
    db_session: Session,
    provider_name: str,
    provider: str,
    model_name: str,
    max_input_tokens: int | None,
    provider_id: int | None = None,
) -> int:
    """Returns the provider id. Pass it back in to update rather than insert —
    without an id `upsert_llm_provider` always creates a new provider row."""
    view = upsert_llm_provider(
        LLMProviderUpsertRequest(
            id=provider_id,
            name=provider_name,
            provider=provider,
            api_key="sk-test-key-00000000000000000000000000000000000",
            api_key_changed=True,
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=model_name,
                    is_visible=True,
                    max_input_tokens=max_input_tokens,
                )
            ],
        ),
        db_session=db_session,
    )
    return view.id


def _stored(db_session: Session, provider_name: str, model_name: str) -> int | None:
    provider = fetch_existing_llm_provider(name=provider_name, db_session=db_session)
    assert provider is not None
    row = (
        db_session.query(ModelConfiguration)
        .filter(
            ModelConfiguration.llm_provider_id == provider.id,
            ModelConfiguration.name == model_name,
        )
        .one()
    )
    return row.max_input_tokens


@pytest.fixture
def provider_name(db_session: Session) -> Generator[str, None, None]:
    """Unique per test: these run against a shared real database, so a fixed name
    lets parallel runs and stale rows from a failed run interfere."""
    name = f"test-context-limits-{uuid.uuid4().hex[:12]}"
    yield name
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)
        db_session.commit()


def test_resolved_value_round_tripped_by_the_ui_is_not_persisted(
    db_session: Session, provider_name: str
) -> None:
    """The admin UI echoes back the value it was served; that must not become an override."""
    model = "gpt-4o-mini"
    resolved = get_max_input_tokens(
        model_name=model, model_provider=LlmProviderNames.OPENAI
    )

    _upsert(db_session, provider_name, LlmProviderNames.OPENAI, model, resolved)

    assert _stored(db_session, provider_name, model) is None


def test_admin_supplied_override_is_persisted(
    db_session: Session, provider_name: str
) -> None:
    """A value the admin actually chose differs from the lookup and must survive."""
    model = "gpt-4o-mini"
    resolved = get_max_input_tokens(
        model_name=model, model_provider=LlmProviderNames.OPENAI
    )
    override = resolved // 2
    assert override != resolved

    _upsert(db_session, provider_name, LlmProviderNames.OPENAI, model, override)

    assert _stored(db_session, provider_name, model) == override


def test_unknown_model_does_not_freeze_the_fallback(
    db_session: Session, provider_name: str
) -> None:
    """The regression: a deployment name LiteLLM does not know yet.

    The UI is served the fallback and sends it back. Persisting it pins the model to
    ~31k forever, so Deep Research (which requires 50k) stays broken even after LiteLLM
    learns the real context window.
    """
    assert (
        get_max_input_tokens(
            model_name=_UNKNOWN_MODEL, model_provider=LlmProviderNames.AZURE
        )
        == _FALLBACK_RESOLVED
    )

    _upsert(
        db_session,
        provider_name,
        LlmProviderNames.AZURE,
        _UNKNOWN_MODEL,
        _FALLBACK_RESOLVED,
    )

    assert _stored(db_session, provider_name, _UNKNOWN_MODEL) is None


def test_dynamic_provider_value_is_persisted(
    db_session: Session, provider_name: str
) -> None:
    """Dynamic providers report real limits from their own APIs, and Ollama feeds num_ctx
    from the stored value, so those are kept even when they match the LiteLLM lookup."""
    model = "llama3.2"
    resolved = get_max_input_tokens(
        model_name=model, model_provider=LlmProviderNames.OLLAMA_CHAT
    )

    _upsert(db_session, provider_name, LlmProviderNames.OLLAMA_CHAT, model, resolved)

    assert _stored(db_session, provider_name, model) == resolved


def test_stored_override_is_not_nulled_by_a_save_matching_the_lookup(
    db_session: Session, provider_name: str
) -> None:
    """Numeric equality cannot tell a deliberate pin from a UI echo.

    So the guard only declines to *create* an override, and a model that already
    carries one is left alone. The load-bearing assertion is that the row is
    still non-null: without the guard, a save whose value matches the live lookup
    nulls it, and the model silently follows LiteLLM from then on.
    """
    model = "gpt-4o-mini"
    resolved = get_max_input_tokens(
        model_name=model, model_provider=LlmProviderNames.OPENAI
    )
    pinned = resolved // 2

    provider_id = _upsert(
        db_session, provider_name, LlmProviderNames.OPENAI, model, pinned
    )
    assert _stored(db_session, provider_name, model) == pinned

    _upsert(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        model,
        resolved,
        provider_id=provider_id,
    )

    stored = _stored(db_session, provider_name, model)
    # The override survives as an override. This is what the guard buys.
    assert stored is not None
    # And the submitted value is honoured — an admin editing the field means it.
    assert stored == resolved


def test_ui_echo_of_a_stored_override_preserves_it(
    db_session: Session, provider_name: str
) -> None:
    """The realistic round trip for a pinned model.

    The API serves `stored or resolved`, so for a pinned model the UI is served
    the pin and echoes the pin. It must come back unchanged.
    """
    model = "gpt-4o-mini"
    resolved = get_max_input_tokens(
        model_name=model, model_provider=LlmProviderNames.OPENAI
    )
    pinned = resolved // 2

    provider_id = _upsert(
        db_session, provider_name, LlmProviderNames.OPENAI, model, pinned
    )
    _upsert(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        model,
        pinned,
        provider_id=provider_id,
    )

    assert _stored(db_session, provider_name, model) == pinned


@pytest.mark.parametrize(
    "provider",
    [
        LlmProviderNames.NEBIUS_TOKENFACTORY,
        LlmProviderNames.PORTKEY,
        LlmProviderNames.VERCEL_AI_GATEWAY,
    ],
)
def test_source_api_providers_keep_their_reported_limit(
    db_session: Session, provider_name: str, provider: str
) -> None:
    """These providers read a context limit from their own APIs and persist it.

    None of them is a dynamic provider, so exempting only DYNAMIC_LLM_PROVIDERS
    would let a matching LiteLLM value discard an authoritative source-API limit.
    """
    model = "unknown-model-from-source-api"
    resolved = get_max_input_tokens(model_name=model, model_provider=provider)

    _upsert(db_session, provider_name, provider, model, resolved)

    assert _stored(db_session, provider_name, model) == resolved
