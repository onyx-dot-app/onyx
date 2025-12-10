import json
import os
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from random import randint

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
            langfuse_context.update_current_observation(
                level="ERROR",
                status_message=f"Max retries of function {func} exceeded"
            )
            raise Exception(f"Max retries of function {func} exceeded")
        return wrapper
    return decorator



class GigachatModelServer(LLM):

    def get_token(self) -> str:

        now = datetime.now()
        if self._token and self._expires_at > now + timedelta(minutes=GIGACHAT_TOKEN_DELTA):
            return self._token

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
            self._token = res_body["access_token"]
            self._expires_at = datetime.fromtimestamp(res_body["expires_at"] / 1000)

            return self._token
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
        custom_config: str | None = None,
        timeout: int = GIGACHAT_TIMEOUT,
        max_output_tokens: int = GIGACHAT_MAX_OUTPUT_TOKENS,
        model: str | None = None,
        user_email: str | None = None,
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
        self._expires_at: datetime = datetime.min
        self._model = model
        self._scope = custom_config['scope']
        self._user_email = user_email

    @observe(as_type="generation")
    def _execute(
        self,
        input: LanguageModelInput, 
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None
    ) -> AIMessage:
        # Check langfuse_context availability
        try:
            current_trace = langfuse_context.get_current_trace()
        except Exception as e:
            logger.warning(
                f"[GigachatModelServer._execute] Error accessing langfuse_context: {e}"
            )
        
        token = self.get_token()

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
            "repetition_penalty": 1,
            "profanity_check": False,
        })

        @retry(10, 10)
        def get_answer() -> tuple[str, dict]:
            try:
                response = requests.request("POST", self._endpoint, headers=headers, data=data, verify=False)

                response_content_request = json.loads(response.text)

                usage_data = response_content_request.get("usage", {})
                prompt_tokens = usage_data.get("prompt_tokens", 0)
                completion_tokens = usage_data.get("completion_tokens", 0)
                total_tokens = usage_data.get("total_tokens", prompt_tokens + completion_tokens)

                response_content = response_content_request["choices"][0]["message"]["content"]

                return response_content, {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "response": response_content_request
                }
            except Timeout as error:
                raise Timeout(f"Model inference to {self._endpoint} timed out") from error

        response_content, metrics = get_answer()
        model_config = self.config

        usage = None
        if metrics["prompt_tokens"] > 0 or metrics["completion_tokens"] > 0:
            usage = {
                "prompt_tokens": metrics["prompt_tokens"],
                "completion_tokens": metrics["completion_tokens"],
                "total_tokens": metrics["total_tokens"],
            }

        user_email_str = str(self._user_email) if self._user_email else None
        
        langfuse_context.update_current_trace(
            name=f"{model_config.model_provider}",
            input=input,
            output=response_content,
            user_id=user_email_str,
            tags=[f"{model_config.model_provider}"],
            metadata={
                "model_provider": model_config.model_provider,
                "model_name": model_config.model_name,
                "endpoint": self._endpoint,
                "repetition_penalty": 1,
                "profanity_check": False,
            },
        )

        langfuse_context.update_current_observation(
            input=input,
            output=metrics["response"],
            user_id=user_email_str,
            model=self._model,
            model_parameters={
                "stream": False,
                "repetition_penalty": 1,
                "temperature": model_config.temperature,
            },
            tags=[f"{model_config.model_provider}"],
            usage=usage,
            metadata={
                "model_provider": model_config.model_provider,
                "model_name": model_config.model_name,
                "endpoint": self._endpoint,
                "repetition_penalty": 1,
                "profanity_check": False,
            },
        )

        return AIMessage(content=response_content)

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
