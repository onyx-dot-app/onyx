"""Opt-in native Responses adapter retaining assistant phases for chat v2.

Internal retrieval still uses Onyx's existing LLM. This narrow adapter supports
plain OpenAI providers, preserves phase on replay, and never exposes reasoning.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import Field

from onyx.agents.v2.llm import (
    TaskCancelled,
    _parse_decision_response,
    build_decision_prompt,
)
from onyx.agents.v2.models import ModelDecision
from onyx.llm.interfaces import LLM, LLMConfig, LLMUserIdentity
from onyx.llm.model_response import (
    ChatCompletionMessageToolCall,
    Choice,
    FunctionCall,
    Message,
    ModelResponse,
    Usage,
)
from onyx.llm.models import (
    AssistantMessage,
    ChatCompletionMessage,
    LanguageModelInput,
    ReasoningEffort,
    SystemMessage,
    ToolChoice,
    UserMessage,
)
from onyx.tracing.llm_utils import record_llm_request_params


class PhasedMessage(AssistantMessage):
    phase: Literal["commentary", "final_answer"] | None = None


class PhasedResponse(ModelResponse):
    output_items: list[dict[str, Any]] = Field(default_factory=list)
    response_status: str = "completed"


def convert_response(raw) -> PhasedResponse:
    items = [
        item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
        for item in raw.output
    ]
    calls = [
        ChatCompletionMessageToolCall(
            id=i["call_id"],
            function=FunctionCall(name=i["name"], arguments=i["arguments"]),
        )
        for i in items
        if i.get("type") == "function_call"
    ]
    text = "\n".join(
        part["text"]
        for item in items
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    usage = raw.usage
    cached_tokens = 0
    if usage is not None and hasattr(usage, "input_tokens_details"):
        details = usage.input_tokens_details
        if details is not None and hasattr(details, "cached_tokens"):
            cached_tokens = details.cached_tokens or 0
    return PhasedResponse(
        id=raw.id,
        created=str(raw.created_at),
        output_items=items,
        response_status=raw.status,
        choice=Choice(
            finish_reason="length"
            if raw.status == "incomplete"
            else "tool_calls"
            if calls
            else "stop",
            message=Message(content=text, tool_calls=calls or None),
        ),
        usage=Usage(
            prompt_tokens=usage.input_tokens,
            completion_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cache_read_input_tokens=cached_tokens,
            cache_creation_input_tokens=0,
        )
        if usage
        else None,
    )


class NativeChannelLLM(LLM):
    def __init__(
        self,
        configured: LLM,
        client: Any = None,
        *,
        on_final_delta: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self._on_final_delta = on_final_delta
        self._cancelled = cancelled
        self.stream_metrics: list[dict[str, Any]] = []
        self._config = configured.config
        if (
            self._config.model_provider != "openai"
            or self._config.deployment_name
            or self._config.custom_config
            or self._config.model_name != "gpt-5.6-sol"
        ):
            raise ValueError(
                "Chat channels currently require a plain OpenAI Sol provider"
            )
        from openai import OpenAI

        self._client = client or OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.api_base or None,
            max_retries=0,
        )

    @property
    def config(self) -> LLMConfig:
        return self._config

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,  # noqa: ARG002
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.OFF,
        user_identity: LLMUserIdentity | None = None,  # noqa: ARG002
        total_timeout_override: float | None = None,
    ) -> ModelResponse:
        if reasoning_effort is not ReasoningEffort.OFF or structured_response_format:
            raise ValueError(
                "Chat channels currently support reasoning off and text output"
            )
        prompt_messages = prompt if isinstance(prompt, list) else [prompt]
        inputs: list[dict[str, Any]] = []
        for msg in prompt_messages:
            item = {"role": msg.role, "content": msg.content}
            phase = msg.phase if isinstance(msg, PhasedMessage) else None
            if msg.role == "assistant" and phase is not None:
                item["phase"] = phase
            inputs.append(item)
        params: dict[str, Any] = dict(
            model=self.config.model_name,
            input=inputs,
            reasoning={"effort": "none"},
            max_output_tokens=max_tokens,
            store=False,
            timeout=total_timeout_override or timeout_override or 120,
        )
        if tools:
            params["tools"] = [
                {"type": "function", **tool["function"]} for tool in tools
            ]
            params["tool_choice"] = "auto"
        record_llm_request_params(
            {
                "model_name": self.config.model_name,
                "model_provider": "openai",
                "reasoning_effort": "off",
                "sent_kwargs": {"reasoning": {"effort": "none"}, "store": False},
                "transport": "native_responses_phases",
            }
        )
        raw = (
            self._stream_response(params)
            if self._on_final_delta is not None
            else cast(Any, self._client.responses.create)(**params)
        )
        response = convert_response(raw)
        record_llm_request_params(
            {
                "model_name": self.config.model_name,
                "model_provider": "openai",
                "reasoning_effort": "off",
                "sent_kwargs": {"reasoning": {"effort": "none"}, "store": False},
                "transport": "native_responses_phases",
                "assistant_phases": [
                    item.get("phase")
                    for item in response.output_items
                    if item.get("type") == "message"
                ],
            }
        )
        return response

    def _stream_response(self, params: dict[str, Any]) -> Any:
        started = time.monotonic()
        metrics = {"stream": True, "first_final_delta_s": None}
        self.stream_metrics.append(metrics)
        phases: dict[int, str | None] = {}
        emitted_items: set[int] = set()
        terminal = None
        # The terminal response is authoritative for tool calls, phases and usage.
        # Only explicitly final assistant items can emit early user-facing text.
        on_final_delta = self._on_final_delta
        if on_final_delta is None:
            raise RuntimeError("Streaming requires a final-delta callback")
        with cast(Any, self._client.responses.create)(**params, stream=True) as stream:
            for event in stream:
                if self._cancelled():
                    raise TaskCancelled("Chat stream cancelled")
                if event.type == "response.output_item.added":
                    item = event.item
                    if item.type == "message" and item.role == "assistant":
                        phases[event.output_index] = (
                            item.phase if hasattr(item, "phase") else None
                        )
                elif event.type in (
                    "response.output_text.delta",
                    "response.refusal.delta",
                ):
                    if phases.get(event.output_index) == "final_answer" and event.delta:
                        if metrics["first_final_delta_s"] is None:
                            metrics["first_final_delta_s"] = time.monotonic() - started
                        if event.output_index not in emitted_items:
                            if emitted_items:
                                on_final_delta("\n")
                            emitted_items.add(event.output_index)
                        on_final_delta(event.delta)
                elif event.type in (
                    "response.completed",
                    "response.incomplete",
                    "response.failed",
                ):
                    terminal = event.response
                    break
                elif event.type == "error":
                    raise RuntimeError("The model stream returned an error")
        metrics["duration_s"] = time.monotonic() - started
        if terminal is None:
            raise RuntimeError("The model stream ended without a terminal response")
        if terminal.status == "failed":
            raise RuntimeError("The model response failed")
        return terminal


class ChannelDecisionModel:
    def __init__(
        self, llm: LLM, on_commentary: Callable[[PhasedMessage], None] | None = None
    ):
        self._llm = llm
        self._on_commentary = on_commentary
        self._history: list[PhasedMessage] = []
        self.messages: list[dict] = []
        self._commentary_only = 0

    def decide(
        self,
        *,
        task,
        context,
        tools,
        remaining_seconds,
        remaining_tokens,
        max_output_tokens,
    ):
        # Completed answers use the native final channel. Keep finish_task for
        # explicit non-success outcomes; don't let legacy state ask for it on
        # every successful turn.
        state = json.loads(context)
        state.setdefault("contracts", {})["finish"] = (
            "For a completed answer, emit phase final_answer. Use finish_task only "
            "for an explicit partial, blocked, needs_user_input or resource outcome."
        )
        context = json.dumps(state)
        tools = copy.deepcopy(tools)
        for tool in tools:
            if tool.get("function", {}).get("name") == "finish_task":
                outcomes = tool["function"]["parameters"]["properties"]["outcome"][
                    "enum"
                ]
                tool["function"]["parameters"]["properties"]["outcome"]["enum"] = [
                    x for x in outcomes if x != "completed"
                ]
                tool["function"]["description"] = (
                    "Report an explicit non-success outcome. Completed answers use phase final_answer."
                )
        prompt = cast(
            list[ChatCompletionMessage],
            build_decision_prompt(
                task=task,
                context=context,
                tools=tools,
                remaining_seconds=remaining_seconds,
                remaining_tokens=remaining_tokens,
                max_output_tokens=max_output_tokens,
            ),
        )
        system_message = cast(SystemMessage, prompt[0])
        user_message = cast(UserMessage, prompt[1])
        system_message.content = system_message.content.replace(
            "Normal final text ends the turn; finish_task is not required for a completed\nanswer.",
            "Use phase final_answer for the completed user-facing answer. A commentary\nmessage is an intermediate update and does not complete the task.",
        )
        system_message.content += (
            "\n\nAssistant output phases: use commentary only for a brief useful progress update; "
            "use final_answer for the self-contained answer or a necessary clarification question. "
            "Do not emit a progress update when you can answer directly. Tool calls remain separate actions. "
            "For completed tasks emit final_answer text; do not call finish_task for success. "
            "Prior commentary is replayed as assistant messages; the latest user state contains tool evidence.\n"
        )
        # Replaying only prior visible message items is intentional: the existing
        # harness supplies tool results in its bounded state, not native tool history.
        prompt = cast(
            LanguageModelInput,
            [system_message, *self._history, user_message],
        )
        response = self._llm.invoke(
            prompt=prompt,
            tools=tools,
            max_tokens=max_output_tokens,
            reasoning_effort=ReasoningEffort.OFF,
        )
        if not isinstance(response, PhasedResponse):
            raise TypeError("The channels adapter requires native response items")
        return self.parse(response)

    def parse(self, response: PhasedResponse) -> ModelDecision:
        final_text = []
        unknown_text = []
        commentary = []
        for item in response.output_items:
            if item.get("type") != "message" or item.get("role") != "assistant":
                continue
            text = "".join(
                p.get("text", p.get("refusal", ""))
                for p in item.get("content", [])
                if p.get("type") in ("output_text", "refusal")
            )
            phase = item.get("phase")
            if phase not in (None, "commentary", "final_answer"):
                return ModelDecision(
                    outcome="blocked", reason="Unsupported assistant output phase"
                )
            msg = PhasedMessage(content=text, phase=phase)
            self.messages.append({"id": item.get("id"), "phase": phase, "text": text})
            if phase == "commentary":
                commentary.append(msg)
            elif phase == "final_answer":
                final_text.append(text)
            else:
                unknown_text.append(text)
        calls = response.choice.message.tool_calls or []
        if final_text and calls:
            return ModelDecision(
                outcome="partial",
                answer="\n".join(final_text),
                reason="The model mixed a final answer with pending tool calls",
            )
        for msg in commentary:
            self._history.append(msg)
            if self._on_commentary and msg.content:
                self._on_commentary(msg)
        if response.response_status != "completed":
            return ModelDecision(
                outcome="partial",
                answer="\n".join(final_text),
                reason="The model response did not complete",
            )
        # Phase-less text retains an explicit compatibility policy. It cannot
        # override pending actions or a native final_answer item.
        selected_text = "\n".join(final_text or ([] if calls else unknown_text))
        if selected_text.strip() or calls:
            self._commentary_only = 0
            copy = response.model_copy(
                update={
                    "choice": response.choice.model_copy(
                        update={
                            "message": response.choice.message.model_copy(
                                update={"content": selected_text}
                            )
                        }
                    )
                }
            )
            result = _parse_decision_response(copy)
            return result.model_copy(update={"decision_mode": "native_phases"})
        if commentary:
            self._commentary_only += 1
            if self._commentary_only >= 3:
                return ModelDecision(
                    outcome="partial",
                    reason="The model returned repeated progress updates without actions or a final answer",
                )
            return ModelDecision(continue_turn=True, decision_mode="native_phases")
        return ModelDecision(
            outcome="partial", reason="The model returned no final answer or action"
        )
