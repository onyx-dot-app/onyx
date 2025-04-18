import json
import time
from collections.abc import Iterator
from random import randint

import requests
from langchain.schema.language_model import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from requests import Timeout

from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.utils import convert_lm_input_to_basic_string
from onyx.utils.logger import setup_logger

logger = setup_logger()

YANDEXGPT_MAX_OUTPUT_TOKENS = 2000
YANDEX_GPT_TEMPERATURE = 0.6
YANDEX_GPT_TIMEOUT = 120


def retry(max_retries, max_wait_time):
    def decorator(func):
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                logger.info(f"retry: {retries} start")
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    retries += 1
                    time.sleep(randint(1, max_wait_time))
                logger.info(f"retry: {retries} end")
            raise Exception(f"Max retries of function {func} exceeded")
        return wrapper
    return decorator


class YandexGPTModelServer(LLM):
    @property
    def requires_api_key(self) -> bool:
        return True

    def __init__(
            self,
            api_key: str | None,
            endpoint: str | None,
            custom_config: dict[str, str] | None = None,
            timeout: int = YANDEX_GPT_TIMEOUT,
            max_output_tokens: int = YANDEXGPT_MAX_OUTPUT_TOKENS,
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

        if not custom_config:
            raise ValueError(
                "Cannot point Smartsearch to a custom LLM server without providing the "
                "YANDEX_ID_KEY for the model server."
            )

        self._endpoint = endpoint
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout
        self._api_key = api_key
        self._id_key = custom_config.get("YANDEX_ID_KEY")
        self._token = None
        self._expires_at = 0.0

        if not self._id_key:
            raise ValueError(
                "Cannot point Smartsearch to a custom LLM server without providing the "
                "YANDEX_ID_KEY for the model server."
            )

    def _execute(self, input: LanguageModelInput) -> AIMessage:
        # redis_cache: RedisCache = litellm.cache.cache

        data = json.dumps({
            "modelUri": f"gpt://{self._id_key}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": YANDEX_GPT_TEMPERATURE,
                "maxTokens": YANDEXGPT_MAX_OUTPUT_TOKENS
            },
            "messages": [
                {
                    "role": "user",
                    "text": convert_lm_input_to_basic_string(input)
                }
            ]
        })
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {self._api_key}"
        }

        # cache_key = litellm.cache.get_cache_key(model="Gigachat", messages=input)
        # cache = redis_cache.get_cache(key=cache_key)
        #
        # if cache:
        #     return AIMessage(content=cache['response'])

        @retry(3, 3)
        def get_answer() -> str:
            try:
                response = requests.request("POST", self._endpoint, headers=headers, data=data, verify=False)
                logger.info(response.text)  # type: ignore
                response_content = json.loads(response.text)['result']['alternatives'][0]['message']['text']
                return response_content
            except Timeout as error:
                raise Timeout("Model inference to ... timed out") from error
            except (KeyError, IndexError) as error:
                logger.info(response.text)  # type: ignore
                logger.info(error)
                raise Exception("YGPT returned incorrect response")

        response_content = get_answer()
        # litellm.cache.add_cache(result=response_content, cache_key=cache_key)
        return AIMessage(content=response_content)

    def log_model_configs(self) -> None:
        logger.debug(f"Custom model at: {self._endpoint}")

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="YandexGPT Lite",
            model_name="YandexGPT Lite",
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
