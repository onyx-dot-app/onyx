"""Pydantic AI models behind Onyx's synchronous LLM interface.

Credentials belong to each model instance. Provider calls never change process
configuration, so requests from different tenants can run concurrently.
"""

import copy
import json
from collections.abc import Callable, Generator
from typing import Any, cast

from pydantic_ai import messages as pm
from pydantic_ai.direct import StreamedResponseSync, model_request, model_request_stream
from pydantic_ai.models import Model, ModelRequestParameters, OutputObjectDefinition
from pydantic_ai.settings import ModelSettings, ThinkingLevel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage

from onyx.configs.app_configs import (
    MOCK_LLM_RESPONSE,
    SEND_USER_METADATA_TO_LLM_PROVIDER,
)
from onyx.configs.chat_configs import LLM_SOCKET_READ_TIMEOUT
from onyx.configs.model_configs import (
    ENABLE_PROMPT_CACHING,
    GEN_AI_NUM_RESERVED_OUTPUT_TOKENS,
    GEN_AI_TEMPERATURE,
    LLM_EXTRA_BODY,
)
from onyx.llm.api_surfaces import (
    OPENAI_COMPATIBLE_SURFACES,
    LlmApiSurface,
    resolve_api_surface,
)
from onyx.llm.constants import LlmProviderNames
from onyx.llm.custom_config_mapping import map_custom_config_to_model_kwargs
from onyx.llm.interfaces import LLM, LLMConfig, LLMUserIdentity
from onyx.llm.model_response import (
    ModelResponse,
    ModelResponseStream,
    StreamingChoice,
    Usage,
)
from onyx.llm.models import (
    ANTHROPIC_REASONING_EFFORT_BUDGET,
    LanguageModelInput,
    NamedToolChoice,
    ReasoningEffort,
    ToolChoice,
    ToolChoiceOptions,
    resolve_reasoning_effort,
)
from onyx.llm.pydantic_messages import (
    from_pydantic_event,
    from_pydantic_response,
    from_pydantic_usage,
    to_pydantic_messages,
)
from onyx.llm.request_context import get_llm_mock_response, set_llm_request_params
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        current = result.get(key)
        result[key] = (
            _merge_settings(current, value)
            if isinstance(current, dict) and isinstance(value, dict)
            else copy.deepcopy(value)
        )
    return result


class PydanticAILLM(LLM):
    def __init__(
        self,
        api_key: str | None,
        model_provider: str,
        model_name: str,
        max_input_tokens: int,
        timeout: int | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        custom_llm_provider: str | None = None,
        temperature: float | None = None,
        custom_config: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict | None = LLM_EXTRA_BODY,
        model_kwargs: dict[str, Any] | None = None,
        reasoning_effort_default: ReasoningEffort | None = None,
        reasoning_effort_user_default: ReasoningEffort | None = None,
        reasoning_effort_max: ReasoningEffort | None = None,
    ) -> None:
        self._model_override: Model | None = None
        self._config = LLMConfig(
            model_provider=model_provider,
            model_name=model_name,
            max_input_tokens=max_input_tokens,
            api_key=api_key,
            api_base=api_base,
            api_version=api_version,
            deployment_name=deployment_name,
            temperature=GEN_AI_TEMPERATURE if temperature is None else temperature,
            custom_config=copy.deepcopy(custom_config),
            reasoning_effort_default=reasoning_effort_default,
            reasoning_effort_user_default=reasoning_effort_user_default,
            reasoning_effort_max=reasoning_effort_max,
        )
        self._timeout = timeout if timeout is not None else LLM_SOCKET_READ_TIMEOUT
        self._provider = custom_llm_provider or model_provider
        self._surface = resolve_api_surface(model_provider, custom_config)
        self._credentials = map_custom_config_to_model_kwargs(
            model_provider, custom_config, api_key, api_base
        ).model_kwargs
        self._kwargs = copy.deepcopy(model_kwargs or {})
        self._headers = {
            **(extra_headers or {}),
            **self._kwargs.pop("extra_headers", {}),
        }
        self._body = _merge_settings(
            extra_body or {}, self._kwargs.pop("extra_body", {})
        )

    @property
    def config(self) -> LLMConfig:
        return self._config

    @property
    def model(self) -> Model:
        from onyx.llm.provider_model import ProviderModel

        return self._model_override or ProviderModel(
            self._build_model(), self.config, model_factory=self._build_model
        )

    @model.setter
    def model(self, model: Model) -> None:
        self._model_override = model

    def _build_model(self, timeout: float | None = None) -> Model:
        """Construct a provider with explicit request-local credentials."""
        config = self.config
        provider = self._provider
        name = config.deployment_name or config.model_name
        credentials = self._credentials
        api_key = credentials.get("api_key", config.api_key)
        base = credentials.get("api_base", config.api_base)
        mock = get_llm_mock_response() or MOCK_LLM_RESPONSE
        if mock:
            from pydantic_ai.models.test import TestModel

            return TestModel(custom_output_text=mock, call_tools=[])
        if provider in (LlmProviderNames.BEDROCK, LlmProviderNames.BEDROCK_CONVERSE):
            from pydantic_ai.models.bedrock import BedrockConverseModel
            from pydantic_ai.providers.bedrock import BedrockProvider

            bedrock_provider = (
                BedrockProvider(
                    api_key=api_key,
                    base_url=base,
                    region_name=credentials.get("aws_region_name"),
                    aws_read_timeout=timeout or self._timeout,
                )
                if api_key
                else BedrockProvider(
                    base_url=base,
                    aws_access_key_id=credentials.get("aws_access_key_id"),
                    aws_secret_access_key=credentials.get("aws_secret_access_key"),
                    aws_session_token=credentials.get("aws_session_token"),
                    region_name=credentials.get("aws_region_name"),
                    aws_read_timeout=timeout or self._timeout,
                )
            )
            return BedrockConverseModel(name, provider=bedrock_provider)
        if provider in (LlmProviderNames.OLLAMA, LlmProviderNames.OLLAMA_CHAT):
            from onyx.llm.ollama_model import OllamaNativeModel

            return OllamaNativeModel(name, base or "http://localhost:11434", api_key)
        if provider == LlmProviderNames.OPENROUTER:
            from openai import AsyncOpenAI
            from pydantic_ai.models.openrouter import OpenRouterModel
            from pydantic_ai.providers.openrouter import OpenRouterProvider

            return OpenRouterModel(
                name,
                provider=OpenRouterProvider(
                    openai_client=AsyncOpenAI(
                        api_key=api_key or "not-needed",
                        base_url=base or "https://openrouter.ai/api/v1",
                    )
                ),
            )
        if provider == LlmProviderNames.VERTEX_AI:
            return self._build_vertex_model(name, base)
        if provider in ("google", "gemini"):
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider

            return GoogleModel(
                name, provider=GoogleProvider(api_key=api_key, base_url=base)
            )
        if (
            provider == LlmProviderNames.ANTHROPIC
            or self._surface == LlmApiSurface.ANTHROPIC_MESSAGES
        ):
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            return AnthropicModel(
                name,
                provider=AnthropicProvider(
                    api_key=api_key or "not-needed", base_url=base
                ),
            )
        if provider == LlmProviderNames.MISTRAL:
            from mistralai.client import Mistral
            from pydantic_ai.models.mistral import MistralModel
            from pydantic_ai.providers.mistral import MistralProvider

            return MistralModel(
                name,
                provider=MistralProvider(
                    mistral_client=Mistral(api_key=api_key, server_url=base)
                ),
            )
        if provider == "groq":
            from pydantic_ai.models.groq import GroqModel
            from pydantic_ai.providers.groq import GroqProvider

            return GroqModel(
                name, provider=GroqProvider(api_key=api_key, base_url=base)
            )
        if provider in ("cohere", "cohere_chat"):
            from cohere import AsyncClientV2
            from pydantic_ai.models.cohere import CohereModel
            from pydantic_ai.providers.cohere import CohereProvider

            cohere_provider = (
                CohereProvider(
                    cohere_client=AsyncClientV2(api_key=api_key, base_url=base)
                )
                if base
                else CohereProvider(api_key=api_key)
            )
            return CohereModel(name, provider=cohere_provider)
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        from onyx.llm.model_capabilities import is_true_openai_model
        from onyx.llm.provider_registry import (
            COMPATIBLE_NATIVE_PROVIDERS,
            OPENAI_COMPATIBLE_BASE_URLS,
        )

        if provider in COMPATIBLE_NATIVE_PROVIDERS:
            from openai import AsyncOpenAI
            from pydantic_ai.providers import Provider, infer_provider_class

            factory = cast(
                Callable[..., Provider[AsyncOpenAI]],
                infer_provider_class(COMPATIBLE_NATIVE_PROVIDERS[provider]),
            )
            native_provider = (
                factory(
                    openai_client=AsyncOpenAI(
                        api_key=api_key or "not-needed", base_url=base
                    )
                )
                if base
                else factory(api_key=api_key or "not-needed")
            )
            return OpenAIChatModel(name, provider=native_provider)
        responses = self._surface == LlmApiSurface.OPENAI_RESPONSES or (
            self._surface is None and is_true_openai_model(provider, config.model_name)
        )
        if provider == LlmProviderNames.AZURE:
            from openai import AsyncAzureOpenAI, AsyncOpenAI

            token = credentials.get("azure_ad_token")
            if responses:
                if not base:
                    raise ValueError("Azure requires an API base URL")
                azure_base = base.rstrip("/")
                if not azure_base.endswith("/openai/v1"):
                    azure_base += "/openai/v1"
                azure_client = AsyncOpenAI(
                    api_key=token or api_key, base_url=azure_base
                )
            else:
                azure_client = AsyncAzureOpenAI(
                    api_key=api_key,
                    azure_ad_token=token,
                    azure_endpoint=base,
                    api_version=config.api_version or "2024-10-21",
                )
            model_provider = OpenAIProvider(openai_client=azure_client)
        else:
            base = base or OPENAI_COMPATIBLE_BASE_URLS.get(provider)
            if base and (
                self._surface in OPENAI_COMPATIBLE_SURFACES
                or provider in ("lm_studio", "ollama", "ollama_chat")
            ):
                base = base.rstrip("/")
                if not base.endswith("/v1"):
                    base += "/v1"
            if provider != "openai" and not base:
                raise ValueError(
                    f"Provider {provider!r} requires an OpenAI-compatible API base URL"
                )
            model_provider = OpenAIProvider(
                api_key=api_key or "not-needed", base_url=base
            )
        return (
            OpenAIResponsesModel(
                name,
                provider=model_provider,
                profile=model_provider.model_profile(config.model_name),
            )
            if responses
            else OpenAIChatModel(
                name,
                provider=model_provider,
                profile=model_provider.model_profile(config.model_name),
            )
        )

    def _build_vertex_model(self, name: str, base: str | None) -> Model:
        credentials = self._credentials
        from google.auth.credentials import Credentials
        from google.oauth2 import service_account
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google_cloud import GoogleCloudProvider

        raw_credentials = credentials.get("vertex_credentials")
        google_credentials: Credentials | None = None
        if raw_credentials:
            if raw_credentials.lstrip().startswith("{"):
                google_credentials = (
                    service_account.Credentials.from_service_account_info(
                        json.loads(raw_credentials)
                    )
                )
            else:
                google_credentials = (
                    service_account.Credentials.from_service_account_file(
                        raw_credentials
                    )
                )
        project = credentials.get("vertex_project")
        location = credentials.get("vertex_location", "global")
        if "claude" in name.lower():
            from anthropic import NOT_GIVEN, AsyncAnthropicVertex
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            return AnthropicModel(
                name,
                provider=AnthropicProvider(
                    anthropic_client=AsyncAnthropicVertex(
                        project_id=project or NOT_GIVEN,
                        region=location,
                        credentials=google_credentials,
                    )
                ),
            )
        return GoogleModel(
            name,
            provider=GoogleCloudProvider(
                credentials=google_credentials,
                project=project,
                location=location,
                base_url=base,
            ),
        )

    def model_settings(
        self,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        max_tokens: int | None = None,
        user_identity: LLMUserIdentity | None = None,
        timeout_override: int | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> ModelSettings:
        config = self.config
        effort = resolve_reasoning_effort(
            reasoning_effort,
            default=config.reasoning_effort_default,
            user_default=config.reasoning_effort_user_default,
            maximum=config.reasoning_effort_max,
        )
        settings: dict[str, Any] = {
            "temperature": config.temperature,
            "timeout": timeout_override or self._timeout,
            "parallel_tool_calls": True,
            "extra_headers": dict(self._headers),
        }
        if max_tokens is not None:
            settings["max_tokens"] = max_tokens
        settings["thinking"] = (
            "medium"
            if effort == ReasoningEffort.AUTO
            else False
            if effort == ReasoningEffort.OFF
            else cast(ThinkingLevel, effort.value)
        )
        if tool_choice is not None:
            settings["tool_choice"] = (
                [tool_choice.name]
                if isinstance(tool_choice, NamedToolChoice)
                else tool_choice.value
            )
        if ENABLE_PROMPT_CACHING and (
            self.config.model_provider in ("anthropic", "vertex_ai")
            or self._surface == LlmApiSurface.ANTHROPIC_MESSAGES
        ):
            settings["anthropic_cache"] = True
            settings["anthropic_cache_instructions"] = True
        elif ENABLE_PROMPT_CACHING and self.config.model_provider in (
            "bedrock",
            "bedrock_converse",
        ):
            settings["bedrock_cache_instructions"] = True
        body = copy.deepcopy(self._body)
        aliases = {
            "store": "openai_store",
            "user": "openai_user",
            "reasoning_effort": "openai_reasoning_effort",
        }
        for key, value in self._kwargs.items():
            if key in aliases:
                body.pop(key, None)
                settings[aliases[key]] = value
            elif key in ModelSettings.__annotations__ or key.startswith(
                ("openai_", "anthropic_", "google_", "bedrock_")
            ):
                settings[key] = value
            else:
                body[key] = value
        if SEND_USER_METADATA_TO_LLM_PROVIDER and user_identity:
            if user_identity.user_id:
                settings["openai_user"] = user_identity.user_id[:64]
            if user_identity.session_id:
                body.setdefault("metadata", {})["session_id"] = user_identity.session_id
            if self.config.model_provider == LlmProviderNames.OPENROUTER:
                if user_identity.session_id:
                    body["session_id"] = user_identity.session_id
                if user_identity.user_id:
                    body["user"] = user_identity.user_id
        if body:
            settings["extra_body"] = body
        from pydantic_ai.profiles.openai import openai_model_profile

        if openai_model_profile(self.config.model_name.rsplit("/", 1)[-1]).get(
            "supports_thinking"
        ):
            settings["openai_reasoning_summary"] = "auto"
        self._apply_thinking_budget(settings, effort, max_tokens, tool_choice)
        if settings.get("thinking") and any(
            "claude" in name.lower()
            for name in (config.model_name, config.deployment_name or "")
        ):
            # Claude fixes temperature at 1 while thinking is enabled.
            settings.pop("temperature", None)
        return cast(ModelSettings, settings)

    def _apply_thinking_budget(
        self,
        settings: dict[str, Any],
        effort: ReasoningEffort,
        max_tokens: int | None,
        choice: ToolChoice | None,
    ) -> None:
        from onyx.llm.model_capabilities import (
            anthropic_supports_thinking,
            anthropic_uses_adaptive_thinking,
        )

        names = [self.config.model_name, self.config.deployment_name or ""]
        if self.config.model_provider == LlmProviderNames.OPENROUTER and any(
            "claude" in name.lower() for name in names
        ):
            if choice == ToolChoiceOptions.REQUIRED and settings.get("thinking"):
                settings["tool_choice"] = "auto"
            elif isinstance(choice, NamedToolChoice):
                settings["thinking"] = False
        if (
            self.config.model_provider in ("anthropic", "vertex_ai")
            or self._surface == LlmApiSurface.ANTHROPIC_MESSAGES
        ):
            from pydantic_ai.profiles.anthropic import (
                AnthropicModelProfile,
                anthropic_model_profile,
            )

            for name in names:
                profile = cast(
                    AnthropicModelProfile, anthropic_model_profile(name) or {}
                )
                if not profile.get("anthropic_supports_forced_tool_choice", True):
                    if choice == ToolChoiceOptions.REQUIRED or isinstance(
                        choice, NamedToolChoice
                    ):
                        settings["tool_choice"] = "auto"
        if not any(anthropic_supports_thinking(name) for name in names):
            return
        if any(anthropic_uses_adaptive_thinking(name) for name in names):
            return
        if choice == ToolChoiceOptions.REQUIRED:
            settings["tool_choice"] = "auto"
        budget = ANTHROPIC_REASONING_EFFORT_BUDGET.get(effort)
        if max_tokens is not None and budget is not None:
            budget = min(budget, max_tokens - max(1, GEN_AI_NUM_RESERVED_OUTPUT_TOKENS))
        if isinstance(choice, NamedToolChoice) or budget is None or budget < 1024:
            settings["thinking"] = False
            return
        thinking = {"type": "enabled", "budget_tokens": budget}
        if self.config.model_provider in ("bedrock", "bedrock_converse"):
            fields = dict(
                settings.get("bedrock_additional_model_requests_fields") or {}
            )
            fields["thinking"] = thinking
            settings["bedrock_additional_model_requests_fields"] = fields
        elif (
            self.config.model_provider in ("anthropic", "vertex_ai")
            or self._surface == LlmApiSurface.ANTHROPIC_MESSAGES
        ):
            settings["anthropic_thinking"] = thinking
        if max_tokens is None:
            settings["max_tokens"] = max(
                4096, budget + max(1, GEN_AI_NUM_RESERVED_OUTPUT_TOKENS)
            )

    def _request_parameters(
        self, tools: list[dict] | None, structured_response_format: dict | None
    ) -> ModelRequestParameters:
        parameters = ModelRequestParameters(
            function_tools=[
                ToolDefinition(
                    name=tool["function"]["name"],
                    description=tool["function"].get("description"),
                    parameters_json_schema=tool["function"].get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                )
                for tool in tools or []
            ]
        )
        if (
            structured_response_format
            and structured_response_format.get("type") == "json_object"
        ):
            parameters.output_mode = "prompted"
            parameters.output_object = OutputObjectDefinition(
                json_schema={"type": "object"}
            )
        elif structured_response_format:
            schema = structured_response_format.get(
                "json_schema", structured_response_format
            )
            parameters.output_mode = "native"
            parameters.output_object = OutputObjectDefinition(
                json_schema=schema.get("schema", schema),
                name=schema.get("name"),
                strict=schema.get("strict"),
            )
        return parameters

    def record_usage(self, usage: RequestUsage) -> None:
        self._track_llm_cost(from_pydantic_usage(usage))

    def _track_llm_cost(self, usage: Usage) -> None:
        from onyx.server.usage_limits import (
            is_onyx_managed_api_key,
            is_usage_limits_enabled,
        )

        if not is_usage_limits_enabled() or not is_onyx_managed_api_key(
            self.config.api_key
        ):
            return
        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.db.usage import UsageType, increment_usage
        from onyx.llm.cost import compute_cost_cents

        try:
            with get_session_with_current_tenant() as session:
                costs = compute_cost_cents(
                    model=self.config.model_name,
                    provider=self.config.model_provider,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cache_read_tokens=usage.cache_read_input_tokens,
                    cache_creation_tokens=usage.cache_creation_input_tokens,
                    db_session=session,
                )
                if sum(costs) > 0:
                    increment_usage(session, UsageType.LLM_COST, sum(costs))
                    session.commit()
        except Exception:
            logger.warning("Failed to track LLM cost", exc_info=True)

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        total_timeout_override: float | None = None,
        stream: bool = False,
    ) -> ModelResponse:
        import asyncio

        from pydantic_ai._utils import get_event_loop

        set_llm_request_params({})
        settings = self.model_settings(
            reasoning_effort, max_tokens, user_identity, timeout_override, tool_choice
        )
        parameters = self._request_parameters(tools, structured_response_format)
        model = self.model
        messages = to_pydantic_messages(prompt, model.system)

        async def request() -> pm.ModelResponse:
            async with model, asyncio.timeout(total_timeout_override):
                if stream:
                    async with model_request_stream(
                        model,
                        messages,
                        model_settings=settings,
                        model_request_parameters=parameters,
                    ) as result:
                        async for _ in result:
                            pass
                        return result.get()
                return await model_request(
                    model,
                    messages,
                    model_settings=settings,
                    model_request_parameters=parameters,
                )

        from onyx.llm.provider_model import translate_provider_errors

        with translate_provider_errors():
            value = get_event_loop().run_until_complete(request())
        result = from_pydantic_response(value)
        if result.usage:
            self._track_llm_cost(result.usage)
        return result

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Generator[ModelResponseStream, None, None]:
        set_llm_request_params({})
        from collections.abc import AsyncIterator
        from contextlib import asynccontextmanager

        from pydantic_ai.models import StreamedResponse

        model = self.model

        @asynccontextmanager
        async def request_stream() -> AsyncIterator[StreamedResponse]:
            async with model:
                async with model_request_stream(
                    model,
                    to_pydantic_messages(prompt, model.system),
                    model_settings=self.model_settings(
                        reasoning_effort,
                        max_tokens,
                        user_identity,
                        timeout_override,
                        tool_choice,
                    ),
                    model_request_parameters=self._request_parameters(
                        tools, structured_response_format
                    ),
                ) as response:
                    yield response

        with StreamedResponseSync(request_stream()) as stream:
            for event in stream:
                chunk = from_pydantic_event(event, stream.response)
                if chunk is not None:
                    yield chunk
            value = stream.response
            usage = from_pydantic_usage(stream.usage)
            self._track_llm_cost(usage)
            yield ModelResponseStream(
                id=value.provider_response_id or "",
                created=value.timestamp.isoformat(),
                choice=StreamingChoice(finish_reason=value.finish_reason),
                usage=usage,
            )
