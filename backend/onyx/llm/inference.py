"""Typed Pydantic AI inference for single-purpose application operations."""

import asyncio

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import WrapModelRequestHandler
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.usage import UsageLimits

from onyx.llm.interfaces import LLM
from onyx.llm.models import ReasoningEffort
from onyx.llm.request_context import set_llm_request_params
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode
from onyx.tracing.llm_utils import llm_generation_span, record_native_llm_response


def run_inference[OutputT](
    *,
    llm: LLM,
    messages: list[ModelMessage],
    output_type: type[OutputT],
    flow: LLMFlow,
    reasoning_effort: ReasoningEffort = ReasoningEffort.OFF,
    max_tokens: int | None = None,
    content_mode: TraceContentMode | None = None,
    total_timeout_override: float | None = None,
) -> OutputT:
    """Validate output through the agent and account for every model request."""

    hooks = Hooks()

    @hooks.on.model_request
    async def account_request(
        _ctx: RunContext[None],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        with llm_generation_span(
            llm=llm,
            flow=flow,
            input_messages=request_context.messages,
            content_mode=content_mode,
        ) as span:
            response = await handler(request_context)
            record_native_llm_response(span, response)
            await asyncio.to_thread(llm.record_usage, response.usage)
            return response

    agent = Agent[None, OutputT](
        llm.model,
        name=flow.value,
        capabilities=[hooks],
        output_type=output_type,
        model_settings=llm.model_settings(
            reasoning_effort=reasoning_effort, max_tokens=max_tokens
        ),
        retries=1,
    )
    set_llm_request_params({})

    async def run() -> OutputT:
        async with agent, asyncio.timeout(total_timeout_override):
            result = await agent.run(
                message_history=messages, usage_limits=UsageLimits(request_limit=2)
            )
            return result.output

    with asyncio.Runner() as runner:
        return runner.run(run())
