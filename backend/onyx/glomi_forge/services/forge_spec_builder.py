"""Turn natural-language delivery requests into structured ForgeSpec objects."""

from typing import Any

from onyx.db.enums import ForgeArtifactType
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
from onyx.llm.interfaces import LLM
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response

_SYSTEM_PROMPT = (
    "你是交付需求规格化助手。把用户的中文交付需求转成 JSON ForgeSpec。"
    "只输出 JSON。字段包括 title, goal, target_audience, requirements, "
    "constraints, visual_style, acceptance_criteria。"
)

_STRUCTURED_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "forge_spec",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "goal": {"type": "string"},
                "target_audience": {"type": ["string", "null"]},
                "requirements": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "visual_style": {"type": "array", "items": {"type": "string"}},
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["title", "goal"],
            "additionalProperties": False,
        },
    },
}


class ForgeSpecBuilder:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def build(
        self,
        nl_request: str,
        artifact_type: ForgeArtifactType,
    ) -> ForgeSpec:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            UserMessage(
                content=(
                    f"交付物类型: {artifact_type.value}\n"
                    f"用户需求: {nl_request}"
                )
            ),
        ]

        if hasattr(self.llm, "config"):
            with llm_generation_span(
                llm=self.llm,
                flow=LLMFlow.FORGE_SPEC_GENERATION,
                input_messages=messages,
            ) as span_generation:
                response = self.llm.invoke(
                    messages,
                    structured_response_format=_STRUCTURED_RESPONSE_FORMAT,
                    reasoning_effort=ReasoningEffort.OFF,
                )
                record_llm_response(span_generation, response)
        else:
            response = self.llm.invoke(
                messages,
                structured_response_format=_STRUCTURED_RESPONSE_FORMAT,
                reasoning_effort=ReasoningEffort.OFF,
            )

        content = response.choice.message.content
        if content is None:
            raise ValueError("ForgeSpecBuilder received empty LLM content")
        return ForgeSpec.model_validate_json(content)
