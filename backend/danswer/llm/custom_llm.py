import json
import re
from collections.abc import Iterator

import requests
from langchain.schema.language_model import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from requests import Timeout

from danswer.configs.model_configs import GEN_AI_API_VERSION
from danswer.configs.model_configs import GEN_AI_CLIENT_ID
from danswer.configs.model_configs import GEN_AI_CLIENT_SECRET
from danswer.configs.model_configs import GEN_AI_IDENTITY_ENDPOINT
from danswer.configs.model_configs import GEN_AI_MAX_OUTPUT_TOKENS
from danswer.llm.interfaces import LLM
from danswer.llm.interfaces import LLMConfig
from danswer.llm.interfaces import ToolChoiceOptions
from danswer.llm.utils import convert_lm_input_to_prompt
from danswer.utils.logger import setup_logger


logger = setup_logger()


class CustomModelServer(LLM):
    """This class is to provide an example for how to use Danswer
    with any LLM, even servers with custom API definitions.
    To use with your own model server, simply implement the functions
    below to fit your model server expectation

    The implementation below works against the custom FastAPI server from the blog:
    https://medium.com/@yuhongsun96/how-to-augment-llms-with-private-data-29349bd8ae9f
    """

    @property
    def requires_api_key(self) -> bool:
        return False

    def _get_token(self) -> str:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
        }

        response = requests.post(self._identity_url, headers=headers, data=data)
        if response.status_code == 200:
            response_json = response.json()
            access_token = response_json.get("access_token")
            if access_token:
                return access_token
            else:
                raise ValueError("Failed to get access token from the model server")
        else:
            print(
                f"Access token request failed with status code: {response.status_code}"
            )
            raise ValueError("Failed to get access token from the model server")

    def __init__(
        self,
        # Not used here but you probably want a model server that isn't completely open
        api_key: str | None,
        timeout: int,
        endpoint: str
        | None = "https://alpha.uipath.com/llmgateway_/openai/deployments/gpt-4o-mini-2024-07-18/chat/completions?api-version=2024-06-01",
        identity_url: str | None = GEN_AI_IDENTITY_ENDPOINT,
        client_id: str | None = GEN_AI_CLIENT_ID,
        client_secret: str | None = GEN_AI_CLIENT_SECRET,
        max_output_tokens: int = int(GEN_AI_MAX_OUTPUT_TOKENS),
        api_version: str | None = GEN_AI_API_VERSION,
    ):
        if not endpoint:
            raise ValueError(
                "Cannot point Danswer to a custom LLM server without providing the "
                "endpoint for the model server."
            )

        if not identity_url:
            raise ValueError(
                "Cannot point Danswer to a custom LLM server without providing the "
                "identity endpoint for the model server."
            )

        if not client_id:
            raise ValueError(
                "Cannot point Danswer to a custom LLM server without providing the "
                "client_id for the model server."
            )

        if not client_secret:
            raise ValueError(
                "Cannot point Danswer to a custom LLM server without providing the "
                "client_secret for the model server."
            )

        # TODO: implement api versions for endpoints and add those to model
        # if not api_version:
        #     raise ValueError(
        #         "Cannot point Danswer to a custom LLM server without providing the "
        #         "api_version for the model server."
        #     )

        self._identity_url = identity_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._endpoint = endpoint
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout
        self.token = self._get_token()
        # TODO: Remove hard-coding
        self._model_provider = "custom"
        self._model_version = "gpt-4"
        self._temperature = 0.0
        self._api_key = api_key

        if max_output_tokens <= 0:
            self._max_output_tokens = 7000

    def _execute(self, input: LanguageModelInput) -> AIMessage:
        headers = {
            "Content-Type": "application/json",
            "X-UiPath-LlmGateway-RequestedFeature": "ChatWithAssistant",
            "X-UiPath-LlmGateway-RequestingFeature": "ChatWithAssistant",
            "X-UiPath-LlmGateway-RequestingProduct": "hackathon",
            "Authorization": "Bearer " + self.token,
        }

        # print(f"Input: {input}")
        chatPrompt = convert_lm_input_to_prompt(input)

        json_array = []
        messages = chatPrompt.to_messages()
        for msg in messages:
            mapped_type = self._map_type(msg.type)
            json_obj = {
                "role": mapped_type,
                "content": self._clean_json_string(msg.content),
            }
            json_array.append(json_obj)

        data = {"max_tokens": self._max_output_tokens, "messages": json_array}

        try:
            print(data)
            with open("requestdata.json", "w") as fp:
                json.dump(data, fp)

            # json_str = json.dumps(data, ensure_ascii=False, indent=4)
            # print(f"Request Data: {json_str}")
            # json_data = json.loads(json_str)
            response = requests.post(
                # self._endpoint, headers=headers, data=json_str, timeout=self._timeout
                self._endpoint,
                headers=headers,
                json=data,
                timeout=self._timeout,
            )
        except Timeout as error:
            raise Timeout(f"Model inference to {self._endpoint} timed out") from error

        response.raise_for_status()
        try:
            data = json.loads(response.content)
            print(data)
        except json.decoder.JSONDecodeError as e:
            print("Failed to parse JSON:", response.content)
            raise e

        message_content = "No response from LLM server"
        if data["choices"]:
            message_content = data["choices"][0]["message"]["content"]
        # print(message_content)
        return AIMessage(content=message_content)

    def _clean_json_string(self, input_string):
        input_string = re.sub(r'[\\]*"', '"', input_string)

        input_string = input_string.replace('"', "'")

        # Remove control characters (ASCII 0-31)
        input_string = re.sub(r"[^\x00-\x7F]+", "", input_string)
        input_string = re.sub(r"[\xa0]", "", input_string)

        # Escape backslashes
        input_string = input_string.replace("\\", "\\\\")

        return input_string

    # Convert from AI to LLMGateway types, Only basic, no chunks and no tool and function calls
    def _map_type(self, type_str) -> str:
        type_mapping = {
            "system": "system",
            "human": "user",
            "ai": "assistant",
        }
        return type_mapping.get(type_str.lower(), "user")

    def log_model_configs(self) -> None:
        logger.debug(f"Custom model at: {self._endpoint}")

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> BaseMessage:
        return self._execute(prompt)

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> Iterator[BaseMessage]:
        yield self._execute(prompt)

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider=self._model_provider,
            model_name=self._model_version,
            temperature=self._temperature,
            api_key=self._api_key,
        )
