from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.db.models import LLMProvider
from onyx.db.models import Persona
from onyx.llm.factory import _resolve_provider_and_model


def _provider(
    *,
    name: str,
    provider: str,
    model_name: str,
) -> LLMProvider:
    provider_model = MagicMock(spec=LLMProvider)
    provider_model.name = name
    provider_model.provider = provider
    model_config = MagicMock()
    model_config.name = model_name
    provider_model.model_configurations = [model_config]
    return cast(LLMProvider, provider_model)


def test_provider_type_override_resolves_matching_provider_model() -> None:
    provider = _provider(
        name="Qwen",
        provider="openai_compatible",
        model_name="qwen3-coder-plus",
    )
    persona = MagicMock(spec=Persona)
    persona.default_model_configuration_id = None

    with (
        patch("onyx.llm.factory.fetch_existing_llm_provider", return_value=None),
        patch("onyx.llm.factory.fetch_existing_llm_providers", return_value=[provider]),
    ):
        resolved = _resolve_provider_and_model(
            persona=persona,
            provider_name_override="openai_compatible",
            model_version_override="qwen3-coder-plus",
            db_session=cast(Session, MagicMock()),
        )

    assert resolved == (provider, "qwen3-coder-plus")


def test_provider_type_override_ignores_provider_without_requested_model() -> None:
    provider = _provider(
        name="Qwen",
        provider="openai_compatible",
        model_name="qwen-plus",
    )
    persona = MagicMock(spec=Persona)
    persona.default_model_configuration_id = None

    with (
        patch("onyx.llm.factory.fetch_existing_llm_provider", return_value=None),
        patch("onyx.llm.factory.fetch_existing_llm_providers", return_value=[provider]),
    ):
        resolved = _resolve_provider_and_model(
            persona=persona,
            provider_name_override="openai_compatible",
            model_version_override="qwen3-coder-plus",
            db_session=cast(Session, MagicMock()),
        )

    assert resolved is None
