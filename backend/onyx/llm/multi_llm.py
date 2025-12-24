import logging
import os
import traceback
from collections.abc import Iterator
from typing import Any
from typing import cast
from typing import TYPE_CHECKING
from typing import Union

from langchain_core.messages import BaseMessage

from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.configs.app_configs import SEND_USER_METADATA_TO_LLM_PROVIDER
from onyx.configs.chat_configs import QA_TIMEOUT
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.configs.model_configs import LITELLM_EXTRA_BODY
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ReasoningEffort
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.llm_provider_options import OLLAMA_PROVIDER_NAME
from onyx.llm.llm_provider_options import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.llm_provider_options import VERTEX_LOCATION_KWARG
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import CLAUDE_REASONING_BUDGET_TOKENS
from onyx.llm.models import OPENAI_REASONING_EFFORT
from onyx.llm.utils import model_is_reasoning_model
from onyx.server.utils import mask_string
from onyx.utils.logger import setup_logger
from onyx.utils.long_term_log import LongTermLogger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

if TYPE_CHECKING:
    from litellm import CustomStreamWrapper


_LLM_PROMPT_LONG_TERM_LOG_CATEGORY = "llm_prompt"
LEGACY_MAX_TOKENS_KWARG = "max_tokens"
STANDARD_MAX_TOKENS_KWARG = "max_completion_tokens"
MAX_LITELLM_USER_ID_LENGTH = 64


class LLMTimeoutError(Exception):
    """
    Exception raised when an LLM call times out.
    """


class LLMRateLimitError(Exception):
    """
    Exception raised when an LLM call is rate limited.
    """


def _prompt_to_dicts(prompt: LanguageModelInput) -> list[dict[str, Any]]:
    """Convert Pydantic message models to dictionaries for LiteLLM.

    LiteLLM expects messages to be dictionaries (with .get() method),
    not Pydantic models. This function serializes the messages.
    """
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    return [msg.model_dump(exclude_none=True) for msg in prompt]


def _normalize_litellm_responses_model(model: str) -> str:
    """
    LiteLLM supports hitting OpenAI's Responses API in a few different ways.

    For `litellm.responses(...)`, the model is typically specified as:
    - "openai/<model>" (e.g. "openai/gpt-5.2")

    For `litellm.completion(...)`, you may see models specified as:
    - "openai/responses/<model>" (e.g. "openai/responses/gpt-5.2")

    This helper normalizes "*/responses/*" -> "*/*" for use with `litellm.responses(...)`.
    """
    parts = model.split("/")
    # Common case: "openai/responses/gpt-5.2" -> "openai/gpt-5.2"
    if len(parts) >= 3 and parts[1] == "responses":
        return "/".join([parts[0], *parts[2:]])
    # Alternate: "<provider>/responses" -> "<provider>"
    if len(parts) == 2 and parts[1] == "responses":
        return parts[0]
    return model


def _litellm_completion_kwargs_to_responses_kwargs(
    completion_call_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert a `litellm.completion(...)` kwarg bundle (chat-completions style)
    into an equivalent `litellm.responses(...)` kwarg bundle (Responses API style).

    Notes / important differences:
    - `messages` -> `input` (+ optional `instructions` extracted from system messages)
    - `max_tokens` -> `max_output_tokens` (and should be omitted when unset)
    - `base_url` -> `api_base` (LiteLLM uses `api_base` for responses)
    - `reasoning_effort` -> `reasoning={"effort": ...}` for OpenAI Responses API
    """

    def _extract_str_content(content: Any) -> str | None:
        if content is None:
            return None
        if isinstance(content, str):
            return content
        # Best-effort fallback for non-string content formats (e.g. list-of-parts)
        try:
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        # common keys across tool/content formats
                        if isinstance(item.get("text"), str):
                            parts.append(item["text"])
                        elif isinstance(item.get("content"), str):
                            parts.append(item["content"])
                joined = "\n".join([p for p in parts if p])
                return joined or None
        except Exception:
            return None
        return str(content)

    def _messages_to_input_and_instructions(
        messages: list[dict[str, Any]] | None,
    ) -> tuple[Any, str | None]:
        if not messages:
            return "", None

        # If this already looks like Responses API input items, pass through as-is.
        # (e.g. [{"type":"message",...}, {"type":"function_call_output",...}])
        if isinstance(messages[0], dict) and "type" in messages[0]:
            return messages, None

        # Use LiteLLM's proven transformer to convert chat-completions-style messages into
        # Responses API `input` items + `instructions`. This avoids invalid payloads like
        # putting `tool_calls` on `input[i].tool_calls` (Responses API doesn't accept that).
        from litellm.completion_extras.litellm_responses_transformation.transformation import (
            LiteLLMResponsesTransformationHandler,
        )

        # Defensive: ensure message content is never `null` for roles that become "message" items.
        safe_messages: list[dict[str, Any]] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            content = m.get("content")
            if (
                content is None
                and role in ("user", "assistant")
                and not m.get("tool_calls")
            ):
                m = dict(m)
                m["content"] = ""
            safe_messages.append(m)

        handler = LiteLLMResponsesTransformationHandler()
        input_items, instructions = (
            handler.convert_chat_completion_messages_to_responses_api(safe_messages)
        )

        # Simple single-turn prompt -> allow passing a plain string
        if (
            isinstance(input_items, list)
            and len(input_items) == 1
            and isinstance(input_items[0], dict)
            and input_items[0].get("type") == "message"
            and input_items[0].get("role") == "user"
        ):
            content_list = input_items[0].get("content")
            if (
                isinstance(content_list, list)
                and len(content_list) == 1
                and isinstance(content_list[0], dict)
                and isinstance(content_list[0].get("text"), str)
                and content_list[0].get("type") in ("input_text", "text")
            ):
                return content_list[0]["text"], instructions

        return input_items, instructions

    def _convert_tools_to_responses_shape(tools: Any) -> Any:
        """
        OpenAI Chat Completions function tool schema (commonly used with LiteLLM):
          {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

        OpenAI Responses API function tool schema:
          {"type": "function", "name": ..., "description": ..., "parameters": ..., "strict": ...}

        This converts the former to the latter (best-effort) and leaves non-function
        tools (e.g. built-ins like web_search/file_search/mcp) unchanged.
        """
        if tools is None:
            return None
        if not isinstance(tools, list):
            return tools

        def _ensure_additional_properties_false(schema: Any) -> Any:
            """
            OpenAI strict function schemas require `additionalProperties: false` for
            JSON Schema objects. Apply this recursively to avoid API 400s like:
            "'additionalProperties' is required to be supplied and to be false."
            """
            if not isinstance(schema, dict):
                return schema

            schema_type = schema.get("type")
            if schema_type == "object":
                # Only set if missing; don't override existing explicit intent.
                schema.setdefault("additionalProperties", False)

                props = schema.get("properties")
                if isinstance(props, dict):
                    # OpenAI strict schema also requires `required` to exist and include
                    # *every* key in properties.
                    required = schema.get("required")
                    if not isinstance(required, list):
                        required = []
                    required_keys = set([k for k in required if isinstance(k, str)])
                    for k in props.keys():
                        if k not in required_keys:
                            required.append(k)
                            required_keys.add(k)
                    schema["required"] = required

                    for k, v in list(props.items()):
                        props[k] = _ensure_additional_properties_false(v)

                # Handle combinators commonly used in schemas
                for comb in ("allOf", "anyOf", "oneOf"):
                    if isinstance(schema.get(comb), list):
                        schema[comb] = [
                            _ensure_additional_properties_false(x) for x in schema[comb]
                        ]

            elif schema_type == "array":
                items = schema.get("items")
                if isinstance(items, dict):
                    schema["items"] = _ensure_additional_properties_false(items)

            return schema

        converted: list[Any] = []
        for tool in tools:
            if not isinstance(tool, dict):
                converted.append(tool)
                continue

            if tool.get("type") == "function" and isinstance(
                tool.get("function"), dict
            ):
                fn = tool["function"]
                strict = fn.get("strict", True)
                params = fn.get("parameters")
                if strict and isinstance(params, dict):
                    # Copy to avoid mutating the original tool definition
                    params = _ensure_additional_properties_false(dict(params))
                converted.append(
                    {
                        "type": "function",
                        "name": fn.get("name"),
                        "description": fn.get("description"),
                        "parameters": params,
                        # Responses API supports `strict`; default to True to enforce argument schema.
                        # This helps prevent invalid tool calls like `{}` when required fields exist.
                        "strict": strict,
                    }
                )
                continue

            # Already looks like Responses API function tool schema
            if (
                tool.get("type") == "function"
                and "name" in tool
                and "parameters" in tool
            ):
                strict = tool.get("strict", True)
                params = tool.get("parameters")
                if strict and isinstance(params, dict):
                    params = _ensure_additional_properties_false(dict(params))
                if "strict" not in tool:
                    converted.append({**tool, "strict": strict, "parameters": params})
                else:
                    converted.append({**tool, "parameters": params})
                continue

            converted.append(tool)

        return converted

    def _convert_tool_choice_to_responses_shape(tool_choice: Any) -> Any:
        """
        Responses API accepts:
        - "none" | "auto" | "required"
        - {"type": "function", "name": "..."} (and other tool-choice variants)
        """
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            return tool_choice
        if isinstance(tool_choice, dict):
            return tool_choice
        # Enum-like (e.g. ToolChoiceOptions.REQUIRED)
        value = getattr(tool_choice, "value", None)
        if isinstance(value, str):
            return value
        return tool_choice

    def _convert_response_format_to_responses_text(
        response_format: Any,
    ) -> dict[str, Any] | None:
        """
        Chat Completions uses `response_format` (e.g. {"type":"json_schema","json_schema":{...}}).
        Responses API uses `text={"format": ...}` where json_schema is *not* nested:
          {"type":"json_schema","name":...,"schema":...,"strict":...}
        """
        if response_format is None:
            return None
        if not isinstance(response_format, dict):
            return None

        converted_format: dict[str, Any] = dict(response_format)
        if converted_format.get("type") == "json_schema" and isinstance(
            converted_format.get("json_schema"), dict
        ):
            # Flatten: {"type":"json_schema","json_schema":{...}} -> {"type":"json_schema", ...}
            nested = converted_format.pop("json_schema")
            converted_format.update(nested)

        return {"format": converted_format}

    # --- Required base fields ---
    model = completion_call_kwargs.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("completion_call_kwargs must include a non-empty 'model' str")

    responses_kwargs: dict[str, Any] = {
        "model": _normalize_litellm_responses_model(model)
    }

    input_param, instructions = _messages_to_input_and_instructions(
        completion_call_kwargs.get("messages")
    )
    responses_kwargs["input"] = input_param
    if instructions:
        responses_kwargs["instructions"] = instructions

    # --- Direct mappings (same name on responses) ---
    for k in (
        "include",
        "metadata",
        "parallel_tool_calls",
        "previous_response_id",
        "store",
        "background",
        "stream",
        "temperature",
        "top_p",
        "truncation",
        "user",
        "timeout",
        # LiteLLM pass-throughs / wiring
        "custom_llm_provider",
        "allowed_openai_params",
        "api_key",
        "api_version",
        "mock_response",
        "extra_headers",
        "extra_query",
        "extra_body",
    ):
        if k in completion_call_kwargs:
            v = completion_call_kwargs.get(k)
            # Responses API prefers omitting unset optionals, not passing None.
            if v is not None:
                responses_kwargs[k] = v

    # Responses API `stream_options` is *not* the same as chat completions.
    # In particular, OpenAI Responses API does NOT support `stream_options.include_usage`.
    stream_options = completion_call_kwargs.get("stream_options")
    if isinstance(stream_options, dict):
        filtered_stream_options = dict(stream_options)
        filtered_stream_options.pop("include_usage", None)
        if filtered_stream_options:
            responses_kwargs["stream_options"] = filtered_stream_options

    # tools + tool_choice have different schema between chat-completions and responses
    if "tools" in completion_call_kwargs:
        converted_tools = _convert_tools_to_responses_shape(
            completion_call_kwargs.get("tools")
        )
        if converted_tools:
            responses_kwargs["tools"] = converted_tools
    if "tool_choice" in completion_call_kwargs:
        converted_tool_choice = _convert_tool_choice_to_responses_shape(
            completion_call_kwargs.get("tool_choice")
        )
        if converted_tool_choice is not None:
            responses_kwargs["tool_choice"] = converted_tool_choice

    # --- Renames / shape changes ---
    # base_url -> api_base (LiteLLM's Responses API path expects api_base in kwargs)
    if completion_call_kwargs.get("base_url") is not None:
        responses_kwargs["api_base"] = completion_call_kwargs["base_url"]
    elif completion_call_kwargs.get("api_base") is not None:
        responses_kwargs["api_base"] = completion_call_kwargs["api_base"]

    # max_tokens -> max_output_tokens (omit when unset)
    if completion_call_kwargs.get("max_tokens") is not None:
        responses_kwargs["max_output_tokens"] = completion_call_kwargs["max_tokens"]

    # reasoning_effort -> reasoning={"effort": ...}
    if completion_call_kwargs.get("reasoning") is not None:
        responses_kwargs["reasoning"] = completion_call_kwargs["reasoning"]
    elif completion_call_kwargs.get("reasoning_effort") is not None:
        # Request a reasoning summary so we can debug/stream `reasoning_content` in Onyx.
        # Without `summary`, OpenAI generally will not emit reasoning summary events.
        responses_kwargs["reasoning"] = {
            "effort": completion_call_kwargs["reasoning_effort"],
            "summary": "auto",
        }

    # response_format -> text.format
    text = _convert_response_format_to_responses_text(
        completion_call_kwargs.get("response_format")
    )
    if text is not None:
        responses_kwargs["text"] = text

    return responses_kwargs


def _prompt_as_json(prompt: LanguageModelInput) -> JSON_ro:
    return cast(JSON_ro, _prompt_to_dicts(prompt))


def _truncate_litellm_user_id(user_id: str) -> str:
    if len(user_id) <= MAX_LITELLM_USER_ID_LENGTH:
        return user_id
    logger.warning(
        "LLM user id exceeds %d chars (len=%d); truncating for provider compatibility.",
        MAX_LITELLM_USER_ID_LENGTH,
        len(user_id),
    )
    return user_id[:MAX_LITELLM_USER_ID_LENGTH]


def _onyx_model_response_from_litellm_responses_api_response(
    raw_response: Any,
) -> ModelResponse:
    """
    Convert an OpenAI Responses API response object (as returned by `litellm.responses(...)`)
    into the simplified Onyx `ModelResponse` shape.

    We intentionally normalize into the existing Onyx chat-completions-like schema so
    the rest of the app doesn't need to care which OpenAI API mode was used.
    """
    # LiteLLM returns a pydantic model for responses, but handle dicts defensively.
    if hasattr(raw_response, "model_dump"):
        data: dict[str, Any] = raw_response.model_dump()
    elif isinstance(raw_response, dict):
        data = raw_response
    else:
        raise ValueError(
            f"Unexpected responses API response type: {type(raw_response)}"
        )

    response_id = str(data.get("id", ""))
    created = str(data.get("created_at") or data.get("created") or "")

    output: list[dict[str, Any]] = data.get("output") or []
    assistant_text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")

        if item_type == "message" and item.get("role") == "assistant":
            content_list = item.get("content") or []
            if isinstance(content_list, list):
                for c in content_list:
                    if not isinstance(c, dict):
                        continue
                    c_type = c.get("type")
                    if c_type in ("output_text", "text"):
                        text = c.get("text")
                        if isinstance(text, str) and text:
                            assistant_text_parts.append(text)

        elif item_type == "reasoning":
            summary_list = item.get("summary") or []
            if isinstance(summary_list, list):
                for s in summary_list:
                    if (
                        isinstance(s, dict)
                        and isinstance(s.get("text"), str)
                        and s.get("text")
                    ):
                        reasoning_parts.append(s["text"])

        elif item_type == "function_call":
            call_id = item.get("call_id") or item.get("id") or ""
            name = item.get("name")
            arguments = item.get("arguments")
            tool_calls.append(
                {
                    "id": str(call_id),
                    "type": "function",
                    "function": {
                        "name": str(name) if name is not None else None,
                        "arguments": str(arguments) if arguments is not None else "",
                    },
                }
            )

    content = "\n".join([p for p in assistant_text_parts if p]) or None
    reasoning_content = "\n\n".join([p for p in reasoning_parts if p]) or None

    finish_reason = "tool_calls" if tool_calls else "stop"
    return ModelResponse(
        id=response_id,
        created=created,
        choice={
            "finish_reason": finish_reason,
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls or None,
                "reasoning_content": reasoning_content,
            },
        },
    )


class LitellmLLM(LLM):
    """Uses Litellm library to allow easy configuration to use a multitude of LLMs
    See https://python.langchain.com/docs/integrations/chat/litellm"""

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
        extra_body: dict | None = LITELLM_EXTRA_BODY,
        model_kwargs: dict[str, Any] | None = None,
        long_term_logger: LongTermLogger | None = None,
    ):
        self._timeout = timeout
        if timeout is None:
            if model_is_reasoning_model(model_name, model_provider):
                self._timeout = QA_TIMEOUT * 10  # Reasoning models are slow
            else:
                self._timeout = QA_TIMEOUT

        self._temperature = GEN_AI_TEMPERATURE if temperature is None else temperature

        self._model_provider = model_provider
        self._model_version = model_name
        self._api_key = api_key
        self._deployment_name = deployment_name
        self._api_base = api_base
        self._api_version = api_version
        self._custom_llm_provider = custom_llm_provider
        self._long_term_logger = long_term_logger
        self._max_input_tokens = max_input_tokens
        self._custom_config = custom_config

        # Create a dictionary for model-specific arguments if it's None
        model_kwargs = model_kwargs or {}

        # NOTE: have to set these as environment variables for Litellm since
        # not all are able to passed in but they always support them set as env
        # variables. We'll also try passing them in, since litellm just ignores
        # addtional kwargs (and some kwargs MUST be passed in rather than set as
        # env variables)
        if custom_config:
            # Specifically pass in "vertex_credentials" / "vertex_location" as a
            # model_kwarg to the completion call for vertex AI. More details here:
            # https://docs.litellm.ai/docs/providers/vertex
            for k, v in custom_config.items():
                if model_provider == "vertex_ai":
                    if k == VERTEX_CREDENTIALS_FILE_KWARG:
                        model_kwargs[k] = v
                        continue
                    elif k == VERTEX_LOCATION_KWARG:
                        model_kwargs[k] = v
                        continue

                # If there are any empty or null values,
                # they MUST NOT be set in the env
                if v is not None and v.strip():
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)
        # This is needed for Ollama to do proper function calling
        if model_provider == OLLAMA_PROVIDER_NAME and api_base is not None:
            os.environ["OLLAMA_API_BASE"] = api_base
        if extra_headers:
            model_kwargs.update({"extra_headers": extra_headers})
        if extra_body:
            model_kwargs.update({"extra_body": extra_body})

        self._model_kwargs = model_kwargs

    def _safe_model_config(self) -> dict:
        dump = self.config.model_dump()
        dump["api_key"] = mask_string(dump.get("api_key") or "")
        credentials_file = dump.get("credentials_file")
        if isinstance(credentials_file, str) and credentials_file:
            dump["credentials_file"] = mask_string(credentials_file)
        return dump

    def _record_call(
        self,
        prompt: LanguageModelInput,
    ) -> None:
        if self._long_term_logger:
            prompt_json = _prompt_as_json(prompt)
            self._long_term_logger.record(
                {
                    "prompt": prompt_json,
                    "model": cast(JSON_ro, self._safe_model_config()),
                },
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

    def _record_result(
        self,
        prompt: LanguageModelInput,
        model_output: BaseMessage,
    ) -> None:
        if self._long_term_logger:
            prompt_json = _prompt_as_json(prompt)
            tool_calls = (
                model_output.tool_calls if hasattr(model_output, "tool_calls") else []
            )
            self._long_term_logger.record(
                {
                    "prompt": prompt_json,
                    "content": model_output.content,
                    "tool_calls": cast(JSON_ro, tool_calls),
                    "model": cast(JSON_ro, self._safe_model_config()),
                },
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

    def _record_error(
        self,
        prompt: LanguageModelInput,
        error: Exception,
    ) -> None:
        if self._long_term_logger:
            prompt_json = _prompt_as_json(prompt)
            self._long_term_logger.record(
                {
                    "prompt": prompt_json,
                    "error": str(error),
                    "traceback": "".join(
                        traceback.format_exception(
                            type(error), error, error.__traceback__
                        )
                    ),
                    "model": cast(JSON_ro, self._safe_model_config()),
                },
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

    def _completion(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None,
        tool_choice: ToolChoiceOptions | None,
        stream: bool,
        parallel_tool_calls: bool,
        reasoning_effort: ReasoningEffort | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        user_identity: LLMUserIdentity | None = None,
    ) -> Union["ModelResponse", "CustomStreamWrapper"]:
        self._record_call(prompt)
        from onyx.llm.litellm_singleton import litellm
        from litellm.exceptions import Timeout, RateLimitError

        is_reasoning = model_is_reasoning_model(
            self.config.model_name, self.config.model_provider
        )

        # NOTE: OpenAI Responses API is disabled for parallel tool calls because LiteLLM's transformation layer
        # doesn't properly pass parallel_tool_calls to the API, causing the model to
        # always return sequential tool calls. For this reason parallel tool calls won't work with OpenAI models
        # if (
        #     is_true_openai_model(self.config.model_provider, self.config.model_name)
        #     or self.config.model_provider == AZURE_PROVIDER_NAME
        # ):
        #     model_provider = f"{self.config.model_provider}/responses"
        # else:
        #     model_provider = self.config.model_provider
        model_provider = self.config.model_provider

        completion_kwargs: dict[str, Any] = self._model_kwargs
        if SEND_USER_METADATA_TO_LLM_PROVIDER and user_identity:
            completion_kwargs = dict(self._model_kwargs)

            if user_identity.user_id:
                completion_kwargs["user"] = _truncate_litellm_user_id(
                    user_identity.user_id
                )

            if user_identity.session_id:
                existing_metadata = completion_kwargs.get("metadata")
                metadata: dict[str, Any] | None
                if existing_metadata is None:
                    metadata = {}
                elif isinstance(existing_metadata, dict):
                    metadata = dict(existing_metadata)
                else:
                    metadata = None

                if metadata is not None:
                    metadata["session_id"] = user_identity.session_id
                    completion_kwargs["metadata"] = metadata

        try:
            final_tool_choice = tool_choice if tools else None
            # Claude models will not use reasoning if tool_choice is required
            # Better to let it use reasoning
            if (
                "claude" in self.config.model_name.lower()
                and final_tool_choice == ToolChoiceOptions.REQUIRED
            ):
                final_tool_choice = ToolChoiceOptions.AUTO

            completion_call_kwargs: dict[str, Any] = {
                "mock_response": MOCK_LLM_RESPONSE,
                # model choice
                # model="openai/gpt-4",
                "model": f"{model_provider}/{self.config.deployment_name or self.config.model_name}",
                # NOTE: have to pass in None instead of empty string for these
                # otherwise litellm can have some issues with bedrock
                "api_key": self._api_key or None,
                "base_url": self._api_base or None,
                "api_version": self._api_version or None,
                "custom_llm_provider": self._custom_llm_provider or None,
                # actual input
                "messages": _prompt_to_dicts(prompt),
                "tools": tools,
                "tool_choice": final_tool_choice,
                # streaming choice
                "stream": stream,
                # model params
                "temperature": (1 if is_reasoning else self._temperature),
                "timeout": timeout_override or self._timeout,
                "max_tokens": max_tokens,
                **({"stream_options": {"include_usage": True}} if stream else {}),
                # NOTE: we can't pass parallel_tool_calls if tools are not specified
                # or else OpenAI throws an error
                **({"parallel_tool_calls": parallel_tool_calls} if tools else {}),
            }

            # Anthropic Claude uses `thinking` with budget_tokens for extended thinking
            # This applies to Claude models on any provider (anthropic, vertex_ai, bedrock)
            if (
                reasoning_effort
                and reasoning_effort != ReasoningEffort.OFF
                and is_reasoning
                and "claude" in self.config.model_name.lower()
                # For now, Claude models cannot support reasoning when a tool is required
                # Maybe this will change in the future.
                and tool_choice != ToolChoiceOptions.REQUIRED
            ):
                completion_call_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": CLAUDE_REASONING_BUDGET_TOKENS[reasoning_effort],
                }

            # OpenAI and other providers use reasoning_effort
            # (litellm maps this to thinking_level for Gemini 3 models)
            if is_reasoning and "claude" not in self.config.model_name.lower():
                completion_call_kwargs["reasoning_effort"] = OPENAI_REASONING_EFFORT[
                    reasoning_effort
                ]

            if structured_response_format:
                completion_call_kwargs["response_format"] = structured_response_format

            completion_call_kwargs.update(completion_kwargs)

            # Use OpenAI Responses API (via LiteLLM).
            # To switch back to chat completions, comment out the `litellm.responses(...)`
            # line and uncomment the `litellm.completion(...)` line below.
            responses_call_kwargs = _litellm_completion_kwargs_to_responses_kwargs(
                completion_call_kwargs
            )
            response = litellm.responses(**responses_call_kwargs)
            # response = litellm.completion(**completion_call_kwargs)
            return response
        except Exception as e:

            self._record_error(prompt, e)
            # for break pointing
            if isinstance(e, Timeout):
                raise LLMTimeoutError(e)

            elif isinstance(e, RateLimitError):
                raise LLMRateLimitError(e)

            raise e

    @property
    def config(self) -> LLMConfig:
        credentials_file: str | None = (
            self._custom_config.get(VERTEX_CREDENTIALS_FILE_KWARG, None)
            if self._custom_config
            else None
        )

        return LLMConfig(
            model_provider=self._model_provider,
            model_name=self._model_version,
            temperature=self._temperature,
            api_key=self._api_key,
            api_base=self._api_base,
            api_version=self._api_version,
            deployment_name=self._deployment_name,
            credentials_file=credentials_file,
            max_input_tokens=self._max_input_tokens,
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        from onyx.llm.model_response import from_litellm_model_response

        response = self._completion(
            prompt=prompt,
            tools=tools,
            tool_choice=tool_choice,
            stream=False,
            structured_response_format=structured_response_format,
            timeout_override=timeout_override,
            max_tokens=max_tokens,
            parallel_tool_calls=True,
            reasoning_effort=reasoning_effort,
            user_identity=user_identity,
        )

        # If we're using `litellm.responses(...)`, we get an OpenAI Responses API object
        # (not a chat-completions-like `ModelResponse`). Normalize it.
        if hasattr(response, "output") or (
            hasattr(response, "model_dump")
            and "output" in (response.model_dump() or {})
        ):
            return _onyx_model_response_from_litellm_responses_api_response(response)

        return from_litellm_model_response(cast(Any, response))

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        from litellm.completion_extras.litellm_responses_transformation.transformation import (
            OpenAiResponsesToChatCompletionStreamIterator,
        )
        from onyx.llm.model_response import from_litellm_model_response_stream

        response = self._completion(
            prompt=prompt,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            structured_response_format=structured_response_format,
            timeout_override=timeout_override,
            max_tokens=max_tokens,
            parallel_tool_calls=True,
            reasoning_effort=reasoning_effort,
            user_identity=user_identity,
        )

        # `litellm.responses(..., stream=True)` yields Responses API SSE event models.
        # Wrap/translate them into chat-completions-like streaming chunks.
        translated_iter = OpenAiResponsesToChatCompletionStreamIterator(
            streaming_response=response,
            sync_stream=True,
            json_mode=False,
        )

        for chunk in translated_iter:
            # NOTE: LiteLLM's `GenericStreamingChunk` is a TypedDict, which does not support
            # `isinstance` checks. Use duck-typing to detect chat-completions-like chunks.
            if hasattr(chunk, "choices"):
                # LiteLLM ModelResponseStream (pydantic model) shape
                yield from_litellm_model_response_stream(cast(Any, chunk))
                continue
            if isinstance(chunk, dict) and "choices" in chunk:
                # Defensive: in case LiteLLM returns dict-form chunks
                yield from_litellm_model_response_stream(cast(Any, chunk))
                continue
            # GenericStreamingChunk (dict with `text`/`tool_use`) -> convert to a chat-completions-like
            # ModelResponseStream so the rest of Onyx can continue to consume deltas.
            if isinstance(chunk, dict) and "text" in chunk and "is_finished" in chunk:
                from litellm.types.utils import Delta as LiteLLMDelta
                from litellm.types.utils import (
                    ModelResponseStream as LiteLLMModelResponseStream,
                )
                from litellm.types.utils import (
                    StreamingChoices as LiteLLMStreamingChoices,
                )

                text = chunk.get("text")
                tool_use = chunk.get("tool_use")

                tool_calls_payload: list[dict[str, Any]] = []
                if tool_use is not None:
                    if hasattr(tool_use, "model_dump"):
                        tool_use_dict = tool_use.model_dump()
                        if isinstance(tool_use_dict, dict):
                            tool_calls_payload.append(tool_use_dict)
                    elif isinstance(tool_use, dict):
                        tool_calls_payload.append(tool_use)

                delta = LiteLLMDelta(
                    content=text if isinstance(text, str) and text != "" else None,
                    tool_calls=tool_calls_payload or None,
                )
                finish_reason = (
                    chunk.get("finish_reason") if chunk.get("is_finished") else None
                )
                choice = LiteLLMStreamingChoices(
                    index=int(chunk.get("index", 0) or 0),
                    delta=delta,
                    finish_reason=finish_reason,
                )
                llm_chunk = LiteLLMModelResponseStream(
                    choices=[choice],
                    usage=chunk.get("usage"),
                )
                yield from_litellm_model_response_stream(llm_chunk)
                continue

            # Unknown event -> ignore (but optionally log for debugging).
            if logger.isEnabledFor(logging.DEBUG):
                try:
                    dumped = repr(chunk)
                    if len(dumped) > 4000:
                        dumped = dumped[:4000] + "...<truncated>"
                    logger.debug(
                        "Ignoring unrecognized LiteLLM stream chunk: %s", dumped
                    )
                except Exception:
                    pass
            continue
