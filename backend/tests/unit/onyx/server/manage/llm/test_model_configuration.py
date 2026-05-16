"""Tests for ModelConfigurationView.from_model and ModelConfigurationUpsertRequest.from_model.

These tests verify the flow plumbing:
- Stored flow takes precedence over the heuristic on the read path.
- Heuristic fires correctly when no flow is stored (legacy / static providers).
- ModelConfigurationUpsertRequest.from_model correctly derives supports_reasoning
  from the stored flow.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.db.enums import LLMModelFlowType
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationView

# ModelConfigurationView.from_model — dynamic provider branch


class TestModelConfigurationViewFromModelDynamic:
    """Tests for the dynamic/custom-config branch of ModelConfigurationView.from_model."""

    # In DYNAMIC_LLM_PROVIDERS
    DYNAMIC_PROVIDER = "lm_studio"

    def test_supports_reasoning_from_stored_flow(self) -> None:
        """Stored REASONING flow → supports_reasoning=True regardless of model name."""
        mc = _make_model_config(
            name="My Custom Bot",
            display_name="My Custom Bot",
            flow_types=[
                LLMModelFlowType.CHAT,
                LLMModelFlowType.REASONING,
            ],
        )

        view = ModelConfigurationView.from_model(mc, self.DYNAMIC_PROVIDER)

        assert view.supports_reasoning is True

    def test_supports_reasoning_falls_back_to_name_heuristic(self) -> None:
        """No stored flow but name matches heuristic → supports_reasoning=True."""
        mc = _make_model_config(
            name="deepseek-r1-8b",
            display_name="DeepSeek R1 8B",
            flow_types=[LLMModelFlowType.CHAT],
        )

        view = ModelConfigurationView.from_model(mc, self.DYNAMIC_PROVIDER)

        assert view.supports_reasoning is True

    def test_supports_reasoning_false_when_no_flow_and_no_name_match(self) -> None:
        """No stored flow and generic name → supports_reasoning=False."""
        mc = _make_model_config(
            name="llama-3-8b",
            display_name="Llama 3 8B",
            flow_types=[LLMModelFlowType.CHAT],
        )

        view = ModelConfigurationView.from_model(mc, self.DYNAMIC_PROVIDER)

        assert view.supports_reasoning is False

    def test_stored_flow_wins_over_non_matching_name(self) -> None:
        """Stored REASONING flow wins even when name wouldn't match the heuristic."""
        mc = _make_model_config(
            name="friendly-chat-bot",
            display_name="Friendly Chat Bot",
            flow_types=[
                LLMModelFlowType.CHAT,
                LLMModelFlowType.REASONING,
            ],
        )

        view = ModelConfigurationView.from_model(mc, self.DYNAMIC_PROVIDER)

        assert view.supports_reasoning is True


# ModelConfigurationView.from_model — static provider branch


class TestModelConfigurationViewFromModelStatic:
    """Tests for the static provider branch of ModelConfigurationView.from_model."""

    # NOT in DYNAMIC_LLM_PROVIDERS
    STATIC_PROVIDER = "openai"

    def test_supports_reasoning_from_stored_flow(self) -> None:
        """Stored REASONING flow → True even when model_is_reasoning_model returns False."""
        mc = _make_model_config(
            name="o3",
            # No display_name forces static branch
            display_name=None,
            flow_types=[
                LLMModelFlowType.CHAT,
                LLMModelFlowType.REASONING,
            ],
        )

        view = self._patched_static_view(mc, model_is_reasoning=False)

        assert view.supports_reasoning is True

    def test_supports_reasoning_falls_back_to_litellm_heuristic(self) -> None:
        """No stored flow but model_is_reasoning_model returns True → True."""
        mc = _make_model_config(
            name="o3",
            display_name=None,
            flow_types=[LLMModelFlowType.CHAT],
        )

        view = self._patched_static_view(mc, model_is_reasoning=True)

        assert view.supports_reasoning is True

    def test_supports_reasoning_false_when_no_flow_and_heuristic_returns_false(
        self,
    ) -> None:
        """No stored flow and model_is_reasoning_model returns False → False."""
        mc = _make_model_config(
            name="gpt-4o",
            display_name=None,
            flow_types=[LLMModelFlowType.CHAT],
        )

        view = self._patched_static_view(mc, model_is_reasoning=False)

        assert view.supports_reasoning is False

    def _patched_static_view(
        self,
        mc: MagicMock,
        model_is_reasoning: bool = False,
    ) -> ModelConfigurationView:
        """Call from_model with the LiteLLM-touching helpers patched out."""
        with (
            patch(
                "onyx.server.manage.llm.models.model_is_reasoning_model",
                return_value=model_is_reasoning,
            ),
            patch(
                "onyx.server.manage.llm.models.get_max_input_tokens",
                return_value=128000,
            ),
            patch(
                "onyx.server.manage.llm.models.litellm_thinks_model_supports_image_input",
                return_value=False,
            ),
            patch(
                "onyx.llm.model_name_parser.parse_litellm_model_name",
            ) as mock_parse,
        ):
            mock_parsed = MagicMock()
            mock_parsed.display_name = mc.name
            mock_parsed.provider_display_name = self.STATIC_PROVIDER
            mock_parsed.vendor = None
            mock_parsed.version = None
            mock_parsed.region = None
            mock_parse.return_value = mock_parsed

            return ModelConfigurationView.from_model(mc, self.STATIC_PROVIDER)


# ModelConfigurationUpsertRequest.from_model


class TestModelConfigurationUpsertRequestFromModel:
    """Tests for ModelConfigurationUpsertRequest.from_model."""

    def test_supports_reasoning_true_when_reasoning_flow_present(self) -> None:
        """REASONING flow row present → supports_reasoning=True in upsert request."""
        mc = _make_model_config(
            flow_types=[
                LLMModelFlowType.CHAT,
                LLMModelFlowType.REASONING,
            ],
        )

        req = ModelConfigurationUpsertRequest.from_model(mc)

        assert req.supports_reasoning is True

    def test_supports_reasoning_false_when_reasoning_flow_absent(self) -> None:
        """No REASONING flow row → supports_reasoning=False in upsert request."""
        mc = _make_model_config(
            flow_types=[LLMModelFlowType.CHAT],
        )

        req = ModelConfigurationUpsertRequest.from_model(mc)

        assert req.supports_reasoning is False


def _make_model_config(
    name: str = "some-model",
    display_name: str | None = "Some Model",
    flow_types: list[LLMModelFlowType] | None = None,
    max_input_tokens: int | None = None,
    is_visible: bool = True,
    supports_image_input: bool | None = None,
) -> MagicMock:
    """Build a minimal mock ModelConfiguration DB row."""
    mc = MagicMock()
    mc.name = name
    mc.display_name = display_name
    mc.max_input_tokens = max_input_tokens
    mc.is_visible = is_visible
    mc.supports_image_input = supports_image_input
    mc.llm_model_flow_types = (
        flow_types if flow_types is not None else [LLMModelFlowType.CHAT]
    )
    return mc
