import math
from typing import Any, Generator, cast

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

CALCULATOR_RESPONSE_ID = "calculator_response"


class CalculatorTool(Tool):
    _NAME = "run_calculator"
    _DISPLAY_NAME = "Calculator Tool"
    _DESCRIPTION = """
    Performs mathematical calculations. Use this tool when you need to:
    - Perform arithmetic operations (addition, subtraction, multiplication, division)
    - Calculate percentages
    - Handle basic mathematical functions (square root, power, etc.)
    """

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "The mathematical expression to evaluate",
                        }
                    },
                    "required": ["expression"],
                },
            },
        }

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        # Simple check if query contains numbers and mathematical operators
        if any(op in query for op in ["+", "-", "*", "/", "%", "^"]):
            return {"expression": query}
        return None

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        calculator_response = next(
            response for response in args if response.id == CALCULATOR_RESPONSE_ID
        )
        return str(calculator_response.response)

    def run(self, **kwargs: str) -> Generator[ToolResponse, None, None]:
        logger.info(f"Running calculator tool with expression: {kwargs['expression']}")
        expression = cast(str, kwargs["expression"])

        try:
            # Create a safe math environment with limited functions
            safe_dict = {
                "abs": abs,
                "round": round,
                "pow": pow,
                "sqrt": math.sqrt,
                "__builtins__": None,
            }

            # Replace '^' with '**' for power operations
            expression = expression.replace("^", "**")

            # Evaluate the expression in a safe environment
            result = eval(expression, {"__builtins__": {}}, safe_dict)

            logger.info(f"Calculator tool result: {result}")

            yield ToolResponse(id=CALCULATOR_RESPONSE_ID, response=result)
        except Exception as e:
            yield ToolResponse(
                id=CALCULATOR_RESPONSE_ID,
                response=f"Error calculating result: {str(e)}",
            )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        calculator_response = next(
            response for response in args if response.id == CALCULATOR_RESPONSE_ID
        )
        return {"result": calculator_response.response}

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        if using_tool_calling_llm:
            prompt_builder.append_message(tool_call_summary.tool_call_request)
            prompt_builder.append_message(tool_call_summary.tool_call_result)
        return prompt_builder
