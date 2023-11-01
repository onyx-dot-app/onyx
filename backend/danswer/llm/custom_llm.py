import json
from collections.abc import Iterator

import requests
from langchain.schema.language_model import LanguageModelInput
from requests import Timeout

from danswer.configs.model_configs import GEN_AI_API_ENDPOINT
from danswer.configs.model_configs import GEN_AI_MAX_OUTPUT_TOKENS
from danswer.llm.interfaces import LLM
from danswer.llm.utils import convert_lm_input_to_basic_string


class CustomModelServer(LLM):
    """This class is to provide an example for how to use Danswer
    with any LLM, even servers with custom API definitions.
    To use with your own model server, simply implement the functions
    below to fit your model server expectation

    The implementation below works against the custom FastAPI server from the blog:
    https://medium.com/@yuhongsun96/how-to-augment-llms-with-private-data-29349bd8ae9f
    """

    def __init__(
        self,
        # Not used here but you probably want a model server that isn't completely open
        api_key: str | None,
        timeout: int,
        endpoint: str | None = GEN_AI_API_ENDPOINT,
        max_output_tokens: int = GEN_AI_MAX_OUTPUT_TOKENS,
    ):
        if not endpoint:
            raise ValueError(
                "Cannot point Danswer to a custom LLM server without providing the "
                "endpoint for the model server."
            )

        self._endpoint = endpoint
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout

    def _execute(self, input: LanguageModelInput) -> str:
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
        return json.loads(response.content).get("generated_text", "")

    def invoke(self, prompt: LanguageModelInput) -> str:
        return self._execute(prompt)

    def stream(self, prompt: LanguageModelInput) -> Iterator[str]:
        yield self._execute(prompt)
