from types import SimpleNamespace

from onyx.db.enums import LLMModelFlowType
from onyx.server.query_and_chat.chat_backend import build_available_chat_models_response
from onyx.server.query_and_chat.models import AvailableChatModel
from onyx.server.query_and_chat.models import AvailableChatModelsResponse


def test_available_chat_model_response_serializes_capabilities() -> None:
    response = AvailableChatModelsResponse(
        models=[
            AvailableChatModel(
                provider_id=1,
                provider_name="Glomi Default",
                provider_type="openai_compatible",
                provider_display_name="Glomi",
                supplier_id="gpt",
                supplier_display_name="GPT",
                model_configuration_id=10,
                model_id="gpt-5.5",
                display_name="GPT-5.5",
                supports_image_input=True,
                supports_reasoning=True,
                roles=["balanced", "vision"],
                is_default=True,
                is_selected=True,
            )
        ]
    )

    dumped = response.model_dump()

    assert dumped["models"][0]["model_id"] == "gpt-5.5"
    assert dumped["models"][0]["supplier_id"] == "gpt"
    assert dumped["models"][0]["supplier_display_name"] == "GPT"
    assert dumped["models"][0]["supports_image_input"] is True
    assert dumped["models"][0]["roles"] == ["balanced", "vision"]


def test_available_chat_models_response_marks_default_and_selected() -> None:
    provider = SimpleNamespace(
        id=1,
        name="Glomi Default",
        provider="openai_compatible",
        model_configurations=[
            SimpleNamespace(
                id=10,
                name="gpt-5.5",
                is_visible=True,
                supports_image_input=True,
                llm_model_flow_types=[
                    LLMModelFlowType.CHAT,
                    LLMModelFlowType.VISION,
                    LLMModelFlowType.REASONING,
                ],
                display_name="GPT-5.5",
                custom_display_name=None,
            ),
            SimpleNamespace(
                id=12,
                name="hidden-model",
                is_visible=False,
                supports_image_input=False,
                llm_model_flow_types=[LLMModelFlowType.CHAT],
                display_name="Hidden Model",
                custom_display_name=None,
            ),
        ],
    )
    minimax_provider = SimpleNamespace(
        id=2,
        name="Glomi MiniMax",
        provider="openai_compatible",
        model_configurations=[
            SimpleNamespace(
                id=20,
                name="MiniMax-M3",
                is_visible=True,
                supports_image_input=True,
                llm_model_flow_types=[
                    LLMModelFlowType.CHAT,
                    LLMModelFlowType.VISION,
                    LLMModelFlowType.REASONING,
                ],
                display_name="MiniMax-M3",
                custom_display_name=None,
            ),
        ],
    )
    default_model = SimpleNamespace(llm_provider_id=1, name="gpt-5.5")
    user = SimpleNamespace(
        default_model="Glomi MiniMax__openai_compatible__MiniMax-M3"
    )

    response = build_available_chat_models_response(
        providers=[provider, minimax_provider],
        default_model=default_model,
        user=user,
    )

    assert [model.model_id for model in response.models] == [
        "gpt-5.5",
        "MiniMax-M3",
    ]
    gpt_model = response.models[0]
    minimax_model = response.models[1]
    assert gpt_model.is_default is True
    assert gpt_model.is_selected is False
    assert gpt_model.supplier_id == "gpt"
    assert gpt_model.supplier_display_name == "GPT"
    assert minimax_model.is_default is False
    assert minimax_model.is_selected is True
    assert minimax_model.supplier_id == "minimax"
    assert minimax_model.supplier_display_name == "MiniMax"
    assert "vision" in minimax_model.roles
