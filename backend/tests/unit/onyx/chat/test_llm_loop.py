"""Legacy tool extraction for providers without native tool calls."""

from onyx.chat.llm_loop import (
    _try_fallback_tool_extraction,
)
from onyx.chat.models import (
    LlmStepResult,
)
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallKickoff


class TestFallbackToolExtraction:
    def _tool_defs(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "internal_search",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "queries": {
                                "type": "array",
                                "items": {"type": "string"},
                            }
                        },
                        "required": ["queries"],
                    },
                },
            }
        ]

    def test_noop_if_fallback_was_already_attempted(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=True,
            tool_defs=self._tool_defs(),
            turn_index=0,
        )

        assert result is llm_step_result
        assert attempted is False

    def test_extracts_from_answer_when_required_and_no_tool_calls(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=3,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {"queries": ["alpha"]}
        assert result.tool_calls[0].placement == Placement(turn_index=3)

    def test_falls_back_to_reasoning_when_answer_has_no_tool_calls(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning='{"name":"internal_search","arguments":{"queries":["beta"]}}',
            answer="I should search first.",
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=5,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {"queries": ["beta"]}
        assert result.tool_calls[0].placement == Placement(turn_index=5)

    def test_extracts_xml_style_invoke_from_answer_when_required(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer=(
                '<function_calls><invoke name="internal_search">'
                '<parameter name="queries" string="false">'
                '["Onyx documentation", "Onyx docs", "Onyx platform"]'
                "</parameter></invoke></function_calls>"
            ),
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=7,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {
            "queries": ["Onyx documentation", "Onyx docs", "Onyx platform"]
        }
        assert result.tool_calls[0].placement == Placement(turn_index=7)

    def test_extracts_xml_style_invoke_from_answer_when_auto(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            # Runtime-faithful shape: filtered answer is empty, raw answer has XML payload.
            answer=None,
            raw_answer=(
                '<function_calls><invoke name="internal_search">'
                '<parameter name="queries" string="false">'
                '["Onyx documentation", "Onyx docs", "Onyx internal docs"]'
                "</parameter></invoke></function_calls>"
            ),
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.AUTO,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=9,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {
            "queries": ["Onyx documentation", "Onyx docs", "Onyx internal docs"]
        }
        assert result.tool_calls[0].placement == Placement(turn_index=9)

    def test_extracts_from_raw_answer_when_filtered_answer_has_no_xml(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer="",
            raw_answer=(
                '<function_calls><invoke name="internal_search">'
                '<parameter name="queries" string="false">'
                '["Onyx documentation", "Onyx docs"]'
                "</parameter></invoke></function_calls>"
            ),
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.AUTO,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=10,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {
            "queries": ["Onyx documentation", "Onyx docs"]
        }
        assert result.tool_calls[0].placement == Placement(turn_index=10)

    def test_does_not_attempt_fallback_for_auto_without_tool_call_hints(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer="Here is a normal answer with no tool call payload.",
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.AUTO,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=2,
        )

        assert result is llm_step_result
        assert attempted is False

    def test_returns_unchanged_when_required_but_nothing_extractable(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning="Need more info.",
            answer="Let me think.",
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=1,
        )

        assert result is llm_step_result
        assert attempted is True
        assert result.tool_calls is None

    def test_noop_when_tool_calls_already_present(self) -> None:
        existing_call = ToolCallKickoff(
            tool_call_id="call_existing",
            tool_name="internal_search",
            tool_args={"queries": ["already-set"]},
            placement=Placement(turn_index=0),
        )
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
            tool_calls=[existing_call],
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=0,
        )

        assert result is llm_step_result
        assert attempted is False
