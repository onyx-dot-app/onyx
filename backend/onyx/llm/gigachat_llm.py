import json
import os
from collections.abc import Iterator
from datetime import datetime, timedelta

import requests
import uuid
from langchain.schema.language_model import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from requests import Timeout
from langfuse.decorators import observe, langfuse_context

from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.utils import convert_lm_input_to_basic_string
from onyx.utils.logger import setup_logger

from onyx.configs.model_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.model_configs import LANGFUSE_SECRET_KEY
from onyx.configs.model_configs import LANGFUSE_HOST

logger = setup_logger()

os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST

GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_TOKEN_DELTA = 5
GIGACHAT_MAX_OUTPUT_TOKENS = 1200
GIGACHAT_TIMEOUT = 120

_token: str | None = None
_expires_at: datetime = datetime.min


class GigachatModelServer(LLM):

    def get_token(self) -> str:
        global _token, _expires_at

        now = datetime.now()
        if _token and _expires_at > now + timedelta(minutes=GIGACHAT_TOKEN_DELTA):
            return _token

        rq_uid = str(uuid.uuid4())
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": rq_uid,
            "Authorization": f"Basic {self._api_key}"
        }

        payload = {
            "scope": self._scope
        }

        try:
            response = requests.post(GIGACHAT_AUTH_URL, headers=headers, data=payload, verify=False)
            if not response.ok:
                raise Exception(f"Can't get oauth token: {response.text}")

            res_body = response.json()
            _token = res_body["access_token"]
            _expires_at = datetime.fromtimestamp(res_body["expires_at"] / 1000)

            return _token
        except requests.RequestException as e:
            logger.error(f"Token request failed: {str(e)}")
            raise e

    @property
    def requires_api_key(self) -> bool:
        return True

    def __init__(
        self,
        api_key: str | None,
        endpoint: str | None,
        custom_config: dict[str, str] | None = None,
        timeout: int = GIGACHAT_TIMEOUT,
        max_output_tokens: int = GIGACHAT_MAX_OUTPUT_TOKENS,
        model: str | None = None
    ):
        if not endpoint:
            raise ValueError(
                "Cannot point Smartsearch to a custom LLM server without providing the "
                "endpoint for the model server."
            )

        if not api_key:
            raise ValueError(
                "Cannot point Smartsearch to a custom LLM server without providing the "
                "api_key for the model server."
            )
        self._endpoint = endpoint
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout
        self._api_key = api_key
        self._token = None
        self._expires_at = 0.0
        self._model = model
        self._scope = custom_config['scope']

    @observe(as_type="generation")
    def _execute(self, input: LanguageModelInput, tools: list[dict] | None = None,
                 tool_choice: ToolChoiceOptions | None = None) -> AIMessage:
        token = self.get_token()
        langfuse_context.update_current_observation(
            input=input,
            model=self._model,
            model_parameters={
                "stream": False,
                "repetition_penalty": 1
            },
        )

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}"
        }

        data = json.dumps({
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": convert_lm_input_to_basic_string(input)
                }
            ],
            "function_call": tool_choice,
            "functions": tools,
            "stream": False,
            "repetition_penalty": 1
        })
        logger.info(data)
        try:
            response = requests.request("POST", self._endpoint, headers=headers, data=data, verify=False)
            response_content = json.loads(response.text)
            logger.info(response_content)
            response_content = response_content["choices"][0]["message"]["content"]
            langfuse_context.update_current_observation(
                output=response_content
            )
            return AIMessage(content=response_content)
        except Timeout as error:
            langfuse_context.update_current_observation(
                level="ERROR",
                status_message=f"Model inference to {self._endpoint} timed out"
            )

            raise Timeout(f"Model inference to {self._endpoint} timed out") from error

    def log_model_configs(self) -> None:
        logger.debug(f"Custom model at: {self._endpoint}")

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="Gigachat",
            model_name=self._model,
            temperature=0,
            api_key=self._api_key,
        )

    def _invoke_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> BaseMessage:
        return self._execute(prompt)

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
