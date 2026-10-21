import pytest

from onyx.db.enums import LLMModelFlowType
from onyx.db.models import LLMModelFlow, ModelConfiguration
from onyx.llm.model_catalog import model_supports_chat, model_supports_decisions
from onyx.llm.well_known_providers.llm_provider_options import fetch_models_for_provider
from onyx.server.manage.llm.models import ModelConfigurationView, OpenRouterModelDetails


@pytest.mark.parametrize(
    "provider,model,chat,decisions",
    [
        ("typesafe", "jev-latest", False, True),
        ("openai", "gpt-6-luna", True, True),
        ("openai", "openai/gpt-6-luna", True, True),
        ("openai", "gpt-5-mini", True, False),
        ("azure", "gpt-6-luna", True, False),
        ("openrouter", "openai/gpt-6-luna", True, False),
        ("typesafe", "unknown", False, False),
        ("openai", "unknown", True, False),
        ("ollama", "instructor-chat", True, False),
        ("openai", "my-embedding-team-chat", True, False),
    ],
)
def test_catalog_capabilities_are_independent_and_provider_scoped(
    provider: str, model: str, chat: bool, decisions: bool
) -> None:
    assert model_supports_chat(provider, model) is chat
    assert model_supports_decisions(provider, model) is decisions


def test_direct_decision_models_are_discoverable() -> None:
    assert fetch_models_for_provider("typesafe") == ["jev-latest", "jev-preview"]


@pytest.mark.parametrize(
    "modalities,chat,decisions",
    [
        (["text"], True, False),
        (["decisions"], False, True),
        (["text", "decisions"], True, True),
        (["embeddings"], False, False),
        ([], False, False),
        ("decisions", False, False),
    ],
)
def test_openrouter_capabilities_use_output_modalities(
    modalities: list[str] | str, chat: bool, decisions: bool
) -> None:
    model = OpenRouterModelDetails(
        id="test/model",
        name="Test model",
        architecture={"output_modalities": modalities},
    )
    assert model.supports_chat is chat
    assert model.supports_decisions is decisions


def test_openrouter_legacy_metadata_does_not_grant_decisions() -> None:
    model = OpenRouterModelDetails(id="test/model", name="Test model")
    assert model.supports_chat is True
    assert model.supports_decisions is False


@pytest.mark.parametrize(
    "flows,chat,decisions",
    [
        ([LLMModelFlowType.CHAT], True, False),
        ([LLMModelFlowType.DECISION], False, True),
        ([LLMModelFlowType.CHAT, LLMModelFlowType.DECISION], True, True),
    ],
)
def test_model_view_preserves_persisted_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    flows: list[LLMModelFlowType],
    chat: bool,
    decisions: bool,
) -> None:
    monkeypatch.setattr(
        "onyx.server.manage.llm.models.catalog_model_supports_image_input",
        lambda *_: False,
    )
    monkeypatch.setattr(
        "onyx.server.manage.llm.models.model_is_reasoning_model", lambda *_: False
    )
    model = ModelConfiguration(
        id=1,
        name="test/model",
        display_name="Test model",
        is_visible=True,
        is_router=False,
        llm_model_flows=[LLMModelFlow(llm_model_flow_type=flow) for flow in flows],
    )
    view = ModelConfigurationView.from_model(model, "openrouter")
    assert view.supports_chat is chat
    assert view.supports_decisions is decisions
