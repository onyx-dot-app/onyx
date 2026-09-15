"""A computed context limit must never be persisted as if it were an admin override.

`ModelConfigurationView.from_model` serves `stored or get_max_input_tokens(...)`, and the
admin UI round-trips whatever it fetched back into the next save. Persisting that resolved
number pins the model to whatever LiteLLM knew at the time, because
`get_max_input_tokens_from_llm_provider` always prefers the stored value.
"""

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

_PROVIDER_NAME = "test-context-limits"


def _upsert(
    db_session: Session,
    provider: str,
    model_name: str,
    max_input_tokens: int | None,
) -> None:
    upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=_PROVIDER_NAME,
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


def _stored(db_session: Session, model_name: str) -> int | None:
    provider = fetch_existing_llm_provider(name=_PROVIDER_NAME, db_session=db_session)
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


@pytest.fixture(autouse=True)
def cleanup_provider(db_session: Session) -> Generator[None, None, None]:
    yield
    provider = fetch_existing_llm_provider(name=_PROVIDER_NAME, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)
        db_session.commit()


def test_resolved_value_round_tripped_by_the_ui_is_not_persisted(
    db_session: Session,
) -> None:
    """The admin UI echoes back the value it was served; that must not become an override."""
    model = "gpt-4o-mini"
    resolved = get_max_input_tokens(
        model_name=model, model_provider=LlmProviderNames.OPENAI
    )

    _upsert(db_session, LlmProviderNames.OPENAI, model, resolved)

    assert _stored(db_session, model) is None


def test_admin_supplied_override_is_persisted(db_session: Session) -> None:
    """A value the admin actually chose differs from the lookup and must survive."""
    model = "gpt-4o-mini"
    resolved = get_max_input_tokens(
        model_name=model, model_provider=LlmProviderNames.OPENAI
    )
    override = resolved // 2
    assert override != resolved

    _upsert(db_session, LlmProviderNames.OPENAI, model, override)

    assert _stored(db_session, model) == override


def test_unknown_model_does_not_freeze_the_fallback(db_session: Session) -> None:
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

    _upsert(db_session, LlmProviderNames.AZURE, _UNKNOWN_MODEL, _FALLBACK_RESOLVED)

    assert _stored(db_session, _UNKNOWN_MODEL) is None


def test_dynamic_provider_value_is_persisted(db_session: Session) -> None:
    """Dynamic providers report real limits from their own APIs, and Ollama feeds num_ctx
    from the stored value, so those are kept even when they match the LiteLLM lookup."""
    model = "llama3.2"
    resolved = get_max_input_tokens(
        model_name=model, model_provider=LlmProviderNames.OLLAMA_CHAT
    )

    _upsert(db_session, LlmProviderNames.OLLAMA_CHAT, model, resolved)

    assert _stored(db_session, model) == resolved
