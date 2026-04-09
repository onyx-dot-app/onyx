"""Tests that exercise the full Ollama model fetch → DB sync → ModelConfigurationView
pipeline against a real Ollama server.

These are external-dependency unit tests: they require a running Ollama server
(default http://localhost:11434) but do NOT need the Onyx backend containers.

The goal is to catch regressions where upstream changes in litellm's model map
(e.g. supports_reasoning becoming None) or Ollama's API (e.g. capabilities
changing shape) would cause Pydantic validation failures when constructing
ModelConfigurationView objects.
"""

import os
from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import upsert_llm_provider
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.api import get_ollama_available_models
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationView
from onyx.server.manage.llm.models import OllamaModelsRequest
from onyx.server.manage.llm.utils import filter_model_configurations

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")


def _ollama_is_reachable() -> bool:
    try:
        resp = httpx.get(f"{OLLAMA_API_BASE}/api/tags", timeout=3.0)
        models = resp.json().get("models", [])
        return resp.status_code == 200 and len(models) > 0
    except Exception:
        return False


skip_if_no_ollama = pytest.mark.skipif(
    not _ollama_is_reachable(),
    reason=f"Ollama server not reachable at {OLLAMA_API_BASE}",
)


@pytest.fixture
def provider_name() -> str:
    return f"test-ollama-{uuid4().hex[:8]}"


@pytest.fixture
def ollama_provider(
    db_session: Session,
    provider_name: str,
) -> Generator[str, None, None]:
    """Create an Ollama provider in the DB, yield its name, then clean up."""
    upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=provider_name,
            provider=LlmProviderNames.OLLAMA_CHAT,
            api_base=OLLAMA_API_BASE,
            api_key=None,
            api_key_changed=False,
            model_configurations=[],
        ),
        db_session=db_session,
    )
    yield provider_name

    # Cleanup
    provider = fetch_existing_llm_provider(name=provider_name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)


@skip_if_no_ollama
class TestOllamaModelFetchPipeline:
    """End-to-end: Ollama fetch → DB sync → ModelConfigurationView construction.

    Catches regressions like:
    - litellm model map returning None for supports_reasoning
    - Ollama API changing capabilities shape
    - Pydantic validation failures in ModelConfigurationView.from_model
    """

    def test_fetch_models_returns_valid_responses(self, db_session: Session) -> None:
        """Fetching models from Ollama should produce valid response objects."""
        request = OllamaModelsRequest(api_base=OLLAMA_API_BASE)
        results = get_ollama_available_models(request, MagicMock(), db_session)

        assert len(results) > 0
        for model in results:
            assert isinstance(model.name, str) and model.name
            assert isinstance(model.display_name, str) and model.display_name
            assert isinstance(model.supports_image_input, bool)

    def test_synced_models_produce_valid_configuration_views(
        self,
        db_session: Session,
        ollama_provider: str,
    ) -> None:
        """Models fetched from Ollama and synced to DB must survive
        ModelConfigurationView.from_model without Pydantic errors.

        This is the path that broke when litellm started returning
        supports_reasoning=None for certain models.
        """
        # Step 1: Fetch from Ollama and sync to DB
        request = OllamaModelsRequest(
            api_base=OLLAMA_API_BASE,
            provider_name=ollama_provider,
        )
        fetched = get_ollama_available_models(request, MagicMock(), db_session)
        assert len(fetched) > 0

        # Step 2: Read back from DB and convert to ModelConfigurationView
        # This is the path that constructs supports_reasoning via litellm
        provider = fetch_existing_llm_provider(
            name=ollama_provider, db_session=db_session
        )
        assert provider is not None
        assert len(provider.model_configurations) > 0

        # Step 3: This must not raise a Pydantic ValidationError
        views = filter_model_configurations(
            provider.model_configurations,
            provider.provider,
        )

        assert len(views) > 0
        for view in views:
            assert isinstance(view, ModelConfigurationView)
            # supports_reasoning must be a bool, never None
            assert isinstance(view.supports_reasoning, bool)
            assert isinstance(view.supports_image_input, bool)
            assert isinstance(view.name, str) and view.name

    def test_each_model_view_has_bool_reasoning(
        self,
        db_session: Session,
        ollama_provider: str,
    ) -> None:
        """Every model from Ollama must have supports_reasoning as a strict bool.

        Exercises ModelConfigurationView.from_model individually so that a failure
        points to the exact model that breaks.
        """
        request = OllamaModelsRequest(
            api_base=OLLAMA_API_BASE,
            provider_name=ollama_provider,
        )
        get_ollama_available_models(request, MagicMock(), db_session)

        provider = fetch_existing_llm_provider(
            name=ollama_provider, db_session=db_session
        )
        assert provider is not None

        for mc in provider.model_configurations:
            view = ModelConfigurationView.from_model(mc, provider.provider)
            assert (
                view.supports_reasoning is not None
            ), f"supports_reasoning is None for model {mc.name}"
            assert isinstance(view.supports_reasoning, bool), (
                f"supports_reasoning is {type(view.supports_reasoning).__name__} "
                f"(value={view.supports_reasoning!r}) for model {mc.name}"
            )
