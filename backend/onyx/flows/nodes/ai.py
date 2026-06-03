"""AI node: ask a model something and get declared fields back.

The contract is the point of this node. A step that returns prose pushes the
parsing problem onto whatever runs next, and in an unattended flow that means
a downstream node silently working on the wrong string. Declaring fields lets
the engine check the shape once, at the boundary, and fail loudly there.

Output is coerced into the declared types rather than merely checked: models
readily answer ``"0.8"`` where a number was asked for, and failing a whole
overnight run over a pair of quotes helps nobody.
"""

from __future__ import annotations

import json
from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import ExpressionError, RunContext, render_text
from onyx.flows.models import AiNode, AiOutputField
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime
from onyx.llm.models import ReasoningEffort, UserMessage
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import parse_llm_json_response

logger = setup_logger()

# One retry, with the parse failure quoted back. A second miss is a prompt
# problem the author needs to see, not something to burn more tokens on.
MAX_PARSE_ATTEMPTS = 2

_TYPE_NAMES = {
    "text": "a string",
    "number": "a number",
    "boolean": "true or false",
    "list": "an array",
}


def execute_ai(node: AiNode, context: RunContext, runtime: NodeRuntime) -> NodeOutcome:
    """Render the prompt, call the model, return typed fields."""
    try:
        prompt = render_text(node.prompt, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

    if not node.output_fields:
        return NodeOutcome(output={"text": _ask(node, runtime, prompt)})

    instruction = _build_prompt(prompt, node.output_fields)
    last_problem = ""

    for attempt in range(1, MAX_PARSE_ATTEMPTS + 1):
        content = _ask(node, runtime, instruction)
        parsed = parse_llm_json_response(content)

        if parsed is None:
            last_problem = "the reply was not valid JSON"
        else:
            try:
                return NodeOutcome(output=_coerce(parsed, node.output_fields))
            except ValueError as exc:
                last_problem = str(exc)

        logger.warning(
            "flow ai node output rejected node=%s attempt=%d reason=%s",
            node.id,
            attempt,
            last_problem,
        )
        instruction = (
            f"{_build_prompt(prompt, node.output_fields)}\n\n"
            f"Your previous reply was rejected because {last_problem}. "
            "Reply with the JSON object only."
        )

    raise NodeExecutionError(
        FlowErrorClass.OUTPUT_MISMATCH,
        f"model did not return the requested fields ({last_problem})",
    )


def _ask(node: AiNode, runtime: NodeRuntime, prompt: str) -> str:
    try:
        response = runtime.llm().invoke(
            prompt=UserMessage(content=prompt),
            reasoning_effort=ReasoningEffort.OFF,
            timeout_override=int(node.timeout_seconds),
        )
    except Exception as exc:
        raise NodeExecutionError(
            FlowErrorClass.LLM_ERROR, f"{type(exc).__name__}: {exc}"
        ) from exc

    content = response.choice.message.content
    if not content:
        raise NodeExecutionError(FlowErrorClass.LLM_ERROR, "model returned nothing")
    return content if isinstance(content, str) else str(content)


def _build_prompt(prompt: str, fields: list[AiOutputField]) -> str:
    """Append the output contract to the author's prompt.

    Written as a worked example rather than a schema because it reads the same
    to every provider, and this node has to behave the same whichever model a
    tenant has configured.
    """
    lines = [
        f'  "{field.name}": {_TYPE_NAMES[field.type]}'
        + (f"  // {field.description}" if field.description else "")
        for field in fields
    ]
    return (
        f"{prompt}\n\n"
        "Reply with a single JSON object and nothing else — no explanation, "
        "no code fences. Use exactly these keys:\n"
        "{\n" + ",\n".join(lines) + "\n}"
    )


def _coerce(parsed: dict[str, Any], fields: list[AiOutputField]) -> dict[str, Any]:
    """Keep the declared fields, in declared order, at the declared types.

    Extra keys are dropped rather than rejected. Models like to add a
    ``"reasoning"`` nobody asked for, and that is not worth a retry.
    """
    result: dict[str, Any] = {}
    for field in fields:
        if field.name not in parsed:
            raise ValueError(f"'{field.name}' was missing")
        result[field.name] = _coerce_one(field, parsed[field.name])
    return result


def _coerce_one(field: AiOutputField, value: Any) -> Any:
    if field.type == "text":
        if isinstance(value, str):
            return value
        return value if value is None else json.dumps(value, default=str)

    if field.type == "number":
        if isinstance(value, bool):
            raise ValueError(f"'{field.name}' should be a number, got true/false")
        if isinstance(value, (int, float)):
            return value
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(f"'{field.name}' should be a number, got {value!r}")

    if field.type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes", "1"):
            return True
        if text in ("false", "no", "0"):
            return False
        raise ValueError(f"'{field.name}' should be true or false, got {value!r}")

    if isinstance(value, list):
        return value
    if value is None:
        return []
    # A single value where a list was asked for is a near miss worth keeping.
    return [value]
