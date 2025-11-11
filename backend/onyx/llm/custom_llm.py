import json
from collections.abc import Iterator
from typing import TYPE_CHECKING

import requests
from langchain.schema.language_model import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from requests import Timeout

from onyx.configs.model_configs import GEN_AI_NUM_RESERVED_OUTPUT_TOKENS
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.utils import convert_lm_input_to_basic_string
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.llm.interfaces import LLMConfig
    from onyx.llm.model_response import ModelResponse


logger = setup_logger()


class CustomModelServer(LLM):
    """This class is to provide an example for how to use Onyx
    with any LLM, even servers with custom API definitions.
    To use with your own model server, simply implement the functions
    below to fit your model server expectation

    The implementation below works against the custom FastAPI server from the blog:
    https://medium.com/@yuhongsun96/how-to-augment-llms-with-private-data-29349bd8ae9f
    """

    @property
    def requires_api_key(self) -> bool:
        return False

    def __init__(
        self,
        # Not used here but you probably want a model server that isn't completely open
        api_key: str | None,
        timeout: int,
        endpoint: str,
        max_output_tokens: int = GEN_AI_NUM_RESERVED_OUTPUT_TOKENS,
    ):
        if not endpoint:
            raise ValueError(
                "Cannot point Onyx to a custom LLM server without providing the "
                "endpoint for the model server."
            )

        self._endpoint = endpoint
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout

    def _execute(self, input: LanguageModelInput) -> AIMessage:
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "inputs": convert_lm_input_to_basic_string(input),
            "parameters": {
                "temperature": 0.0,
                "max_tokens": self._max_output_tokens,
            },
        }
        try:
            response = requests.post(
                self._endpoint, headers=headers, json=data, timeout=self._timeout
            )
        except Timeout as error:
            raise Timeout(f"Model inference to {self._endpoint} timed out") from error

        response.raise_for_status()
        response_content = json.loads(response.content).get("generated_text", "")
        return AIMessage(content=response_content)

    @property
    def config(self) -> "LLMConfig":
        from onyx.llm.interfaces import LLMConfig

        return LLMConfig(
            model_provider="custom",
            model_name="custom-model",
            temperature=0.0,
            max_input_tokens=4096,
        )

    def log_model_configs(self) -> None:
        logger.debug(f"Custom model at: {self._endpoint}")

    def _invoke_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> "ModelResponse":
        from onyx.llm.model_response import Choice
        from onyx.llm.model_response import Message
        from onyx.llm.model_response import ModelResponse

        ai_message = self._execute(prompt)
        return ModelResponse(
            id="custom-model-response",
            created="0",
            choice=Choice(
                finish_reason="stop",
                index=0,
                message=Message(
                    content=(
                        ai_message.content
                        if isinstance(ai_message.content, str)
                        else str(ai_message.content)
                    ),
                    role="assistant",
                ),
            ),
        )

    def _stream_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[BaseMessage]:
        yield self._execute(prompt)
