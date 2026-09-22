"""Request attribution and provider error handling for Pydantic AI models."""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from types import TracebackType
from typing import Any, cast

import httpx
import httpx2
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from onyx.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from onyx.llm.interfaces import LLMConfig
from onyx.llm.request_context import get_llm_request_params, set_llm_request_params
from onyx.tracing.llm_utils import record_llm_request_params


@contextmanager
def translate_provider_errors() -> Iterator[None]:
    import anthropic
    import groq
    import openai
    from botocore.exceptions import ConnectTimeoutError, ReadTimeoutError

    timeout_errors = (
        TimeoutError,
        httpx.TimeoutException,
        httpx2.TimeoutException,
        openai.APITimeoutError,
        anthropic.APITimeoutError,
        groq.APITimeoutError,
        ConnectTimeoutError,
        ReadTimeoutError,
    )

    try:
        yield
    except timeout_errors as error:
        raise LLMTimeoutError(str(error)) from error
    except ModelHTTPError as error:
        if error.status_code == 429:
            raise LLMRateLimitError(str(error)) from error
        raise
    except ModelAPIError as error:
        cause = error.__cause__
        if isinstance(cause, timeout_errors):
            raise LLMTimeoutError(str(error)) from error
        raise
    except (openai.RateLimitError, anthropic.RateLimitError) as error:
        raise LLMRateLimitError(str(error)) from error


def settings_after_rejection(
    settings: ModelSettings, error: ModelHTTPError
) -> ModelSettings | None:
    """Retry only rejected optional tuning, keeping tools and privacy policy."""
    if error.status_code != 400:
        return None
    message = str(error.body).lower()
    result = dict(settings)
    if (
        "set reasoning_effort to 'none'" in message
        and result.get("openai_reasoning_effort") != "none"
    ):
        result.pop("thinking", None)
        result["openai_reasoning_effort"] = "none"
    elif "temperature" in message:
        result.pop("temperature", None)
    elif any(
        word in message for word in ("reasoning", "thinking", "budget_tokens", "effort")
    ):
        for key in (
            "thinking",
            "openai_reasoning_effort",
            "openai_reasoning_summary",
            "anthropic_thinking",
            "anthropic_effort",
            "google_thinking_config",
            "openrouter_reasoning",
        ):
            result.pop(key, None)
        if isinstance(
            fields := result.get("bedrock_additional_model_requests_fields"), dict
        ):
            result["bedrock_additional_model_requests_fields"] = {
                key: value for key, value in fields.items() if key != "thinking"
            }
    else:
        return None
    return cast(ModelSettings, result) if result != settings else None


class ProviderModel(WrapperModel):
    def __init__(
        self,
        wrapped: Model,
        config: LLMConfig,
        model_factory: Callable[[float | None], Model] | None = None,
    ) -> None:
        super().__init__(wrapped)
        self.config = config
        self._model_factory = model_factory

    @asynccontextmanager
    async def _request_model(self, settings: ModelSettings) -> AsyncIterator[Model]:
        from pydantic_ai.models.bedrock import BedrockConverseModel

        timeout = settings.get("timeout")
        if (
            isinstance(self.wrapped, BedrockConverseModel)
            and isinstance(timeout, (int, float))
            and self._model_factory is not None
        ):
            native = self._model_factory(float(timeout))
            async with ProviderModel(native, self.config):
                yield native
        else:
            yield self.wrapped

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        try:
            return await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            # Providers do not own explicitly injected SDK clients.
            provider = self.wrapped.provider
            if provider is not None:
                from anthropic import AsyncAnthropic, AsyncAnthropicVertex
                from botocore.client import BaseClient
                from cohere import AsyncClientV2
                from google.genai import Client
                from mistralai.client import Mistral
                from openai import AsyncOpenAI

                client = provider.client
                if isinstance(
                    client, (AsyncOpenAI, AsyncAnthropic, AsyncAnthropicVertex)
                ):
                    await client.close()
                elif isinstance(client, BaseClient):
                    client.close()
                elif isinstance(client, Client):
                    await client.aio.aclose()
                elif isinstance(client, (Mistral, AsyncClientV2)):
                    await client.__aexit__(exc_type, exc_val, exc_tb)

    def _record(self, settings: ModelSettings, stream: bool) -> None:
        thinking = settings.get("thinking", True)
        params = {
            "model_name": self.config.model_name,
            "model_provider": self.config.model_provider,
            "reasoning_effort": "auto"
            if thinking is True
            else "off"
            if thinking is False
            else thinking,
            "max_tokens": settings.get("max_tokens"),
            "stream": stream,
            "sent_kwargs": {
                key: value
                for key, value in settings.items()
                if key
                in (
                    "temperature",
                    "thinking",
                    "openai_reasoning_effort",
                    "anthropic_thinking",
                    "anthropic_effort",
                    "google_thinking_config",
                )
            },
        }
        capture = get_llm_request_params()
        if capture is not None:
            capture.clear()
            capture.update(params)
            params = capture
        record_llm_request_params(params)
        set_llm_request_params(params)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        settings = model_settings or ModelSettings()
        for attempt in range(4):
            self._record(settings, False)
            try:
                with translate_provider_errors():
                    async with self._request_model(settings) as model:
                        return await model.request(
                            messages, settings, model_request_parameters
                        )
            except ModelHTTPError as error:
                replacement = settings_after_rejection(settings, error)
                if replacement is None or attempt == 3:
                    raise
                settings = replacement
        raise RuntimeError("Provider request exhausted retries")

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        settings = model_settings or ModelSettings()
        for attempt in range(4):
            self._record(settings, True)
            started = False
            try:
                with translate_provider_errors():
                    async with self._request_model(settings) as model:
                        async with model.request_stream(
                            messages, settings, model_request_parameters, run_context
                        ) as stream:
                            started = True
                            yield stream
                            return
            except ModelHTTPError as error:
                replacement = settings_after_rejection(settings, error)
                if started or replacement is None or attempt == 3:
                    raise
                settings = replacement
