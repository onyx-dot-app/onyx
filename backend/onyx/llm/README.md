# Language model client

Application calls and agent loops use `LLM` for generation.
The factory selects a model and returns its configured client.
`client.config` describes the selected model, image support, and token limits.

This interface generates assistant messages from conversational input, including supported images and tool results.
Embeddings, reranking, image generation, and speech use operation-specific interfaces.

`GenerationRequest`, `GenerationContext`, and `GenerationEvent` describe one call.
`AgentEvent` describes execution across generations and tools.
A generation tool-call event contains the generated name and arguments. Agent tool events describe execution of that tool.

| Module | Responsibility |
| --- | --- |
| `interfaces.py` | `LLM`, configuration, and per-call execution policy. |
| `models.py` | Shared messages, requests, generation options, and stream events. |
| `factory.py` | Select a configured model and construct its client. |
| `multi_llm.py` | LiteLLM transport and shared generation implementation. |
| `litellm_models.py` | Provider request messages, responses, and stream chunks. |
| `litellm_conversion.py` | Convert between provider data and shared generation types. |
| `cancellation.py` | Cancellation signals, isolated execution, and interruptible streaming. |

## One generation

`invoke` returns a complete `AssistantMessage`.
The message contains text, tool calls, thinking, usage, and the stop reason.

```python
from onyx.llm.interfaces import LLM
from onyx.llm.models import UserMessage
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import GenerationOptions, GenerationRequest
from onyx.tracing.flows import LLMFlow


def summarize(client: LLM, text: str, flow: LLMFlow) -> str:
    response = client.invoke(
        GenerationRequest(
            system_prompt="Summarize the supplied text in one sentence.",
            messages=[UserMessage(content=text)],
            options=GenerationOptions(max_tokens=100),
        ),
        GenerationContext(flow=flow),
    )
    return response.text
```

`GenerationRequest` contains instructions, messages, tool definitions, and generation options.
`GenerationOptions` controls tool choice, reasoning effort, output limits, and structured output.
`GenerationContext` carries the tracing flow, privacy mode, user identity, cancellation, and transport timeouts.
Every application operation supplies a registered tracing flow.

`stall_timeout_s` bounds idle reads during streaming; it does not limit the complete generation.
`total_timeout_s` limits the complete generation, including retries.
`invoke` uses `LLM_INVOKE_TIMEOUT_S` when no total timeout is set and ignores the streaming idle timeout.
`stream` uses `LLM_SOCKET_READ_TIMEOUT` for idle reads and has no total timeout unless explicitly set.
Deadline expiry interrupts owned provider I/O and raises `LLMTimeoutError`.
A generation deadline does not cancel the parent agent's signal.

## Streaming and cancellation

Text and thinking deltas carry content indices; they have no separate start or end events.
Tool calls retain start, delta, and end events for incremental arguments and final validation.

`stream` yields indexed text and thinking deltas, plus snapshots of the tool call being updated.
Updates do not contain the accumulated assistant message. Thinking deltas retain provider replay blocks.
Start, completion, and error events carry isolated full-message snapshots.
Events describe text, thinking, tool arguments, completion, and errors.
A successful stream ends with `done`, which contains the completed assistant message.
A stream error raises after emitting its error event when generation has started.
Events also carry effective request settings for diagnostics. Presentation reads these settings from the event.
Close the stream when consumption stops early.

`apply_generation_event(message, event)` mutates the caller's assistant message in place.
This avoids copying accumulated output for each delta. It preserves message identity and application metadata.
It copies mutable event payloads and does not modify the event.

Only the message owner may apply updates. Synchronize readers and writers when the message is shared across threads.
The agent runtime applies updates under its state lock before notifying observers.
Use `message.model_copy(deep=True)` when exposing a snapshot that must remain unchanged as generation continues.

```python
from contextlib import closing

from onyx.llm.cancellation import CancellationSignal

signal = CancellationSignal()
with closing(client.stream(request, GenerationContext(flow=flow, cancellation=signal))) as events:
    for event in events:
        if event.type == "text_delta":
            print(event.text, end="")
```

The example uses an existing client, request, and registered flow.
Call `signal.cancel()` from the request's Stop handler to interrupt generation.
Cancellation raises `AgentCancelled`. The operation remains tracked until transport cleanup finishes.
Each generation owns its stream accumulator, parsing state, and deadline.

## Agent with tools

An agent adds history, tool execution, and iteration to the same client.
Tool definitions reach the model. Executable callbacks belong to the agent.

```python
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool
from onyx.llm.models import ToolResult


def make_agent(client: LLM, flow: LLMFlow) -> Agent:
    echo = AgentTool(
        name="echo",
        description="Return the supplied text.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        execute=lambda invocation: ToolResult(
            content=str(invocation.arguments["text"])
        ),
    )
    return Agent(
        client,
        tools=[echo],
        execution=GenerationContext(flow=flow),
    )
```

Call `agent.start(background=False, messages=[UserMessage(content="Echo hello")], max_steps=2)` to generate, execute tools, and continue.
It returns a `Run` handle at completion or suspension. Call `run.result()` to wait for the final answer.
Use `agent.start(...)` to receive a `Run` handle; call `run.cancel()` to cancel that execution.
Tools receive the same cancellation signal and must cooperate with interruption.
See [Agent execution](../agents/README.md) for snapshots, child execution, and lifecycle behavior.

## Context hooks

A step hook prepares messages and generation settings for the next model call.
It receives an isolated `StepInput` and returns a `PreparedStep`.

```python
from onyx.agents.models import PreparedStep, StepInput
from onyx.llm.models import GenerationOptions


def prepare_step(state: StepInput) -> PreparedStep:
    return PreparedStep(
        tools=[] if state.step.is_last else [echo],
        options=GenerationOptions(max_tokens=1000),
    )


agent = Agent(client, prepare_step=prepare_step)
```

The example uses an existing client and executable `echo` tool.
Onyx feature hooks use `chat/llm_step.py` for attachments, reminders, and cache hints.
`chat/prompt_utils.py` assembles instructions and file context. Agent owns compaction and the input budget.
Chat citation mapping stays in `chat/citation_utils.py`.
The helper returns shared messages. Ordinary text calls can construct messages directly.

## Provider boundary

`LitellmLLM` implements the client contract.
`LLM` is an abstract base class. Provider implementations inherit it and implement its abstract members.
`LitellmLLM` serializes shared requests and normalizes responses.
It also owns credentials, provider requests, retries, usage accounting, and connection cleanup.
The factory constructs one configured `LitellmLLM`.
Complete responses convert directly into assistant messages.
Streaming uses one accumulator to filter text, parse tool arguments, and produce events.
Native tool calls take precedence over compatible tool calls recovered from text.
Recovery applies to requests with tools and keeps its state within that generation.

Provider wire messages remain internal to adapters and protocol gateways.
Typed request messages support gateway validation and provider cache controls before serialization to wire dictionaries.
API proxy endpoints use `LitellmLLM.invoke_raw` and `stream_raw` to preserve their external protocol.
They own their generation spans.
`LitellmLLM.stream` runs in an isolated context so interleaved streams retain their own cancellation and tracing state.
Application error handling uses `client.redact_error` to remove credential values from diagnostics.
`client.config` contains model settings, resolved capabilities, and provider credentials.
Tracing selects explicit descriptive fields from this configuration and does not serialize the complete configuration.

Prompt preparation selects content and attachments. Provider serialization applies wire encoding and provider cache controls.
Signed thinking blocks survive replay. Message copies preserve shared lazy file resources without loading attachment bytes.

## Provider credentials and timeouts

Provider calls pass supported settings directly to LiteLLM.
Environment-only custom settings retain the configured environment injection behavior.

| Provider | Request-scoped settings |
| --- | --- |
| Bedrock | Region, access key, secret key, session token, and bearer token. |
| Azure | API key, API base, and Azure AD token. |
| Vertex AI | Service-account credentials, workload identity mode, project, and location. |
| Other providers | Provider-prefixed API key and API base settings. |

When environment injection is enabled, calls temporarily apply environment-only settings under an exclusive lock.
Calls without injected settings share a read lock. Original environment values are restored afterward.
When injection is disabled, the adapter drops environment-only keys and logs a warning.
UI routing selections remain configuration metadata and do not become provider arguments.

Each generation owns a synchronous HTTP client. HTTPX connection tracing captures a duplicate socket before TLS setup.
Cancellation shuts down that socket to interrupt blocked reads. The generation thread closes the client and tracks cleanup completion.
Controlled stalled-response tests cover OpenAI chat, OpenAI Responses, Azure chat, Anthropic, and the Responses gateway.
They verify cancellation before response headers and between streamed chunks, plus isolation between simultaneous requests.
Azure client construction uses LiteLLM's authentication helper and retains API-key, AD-token, and token-refresh settings.

DNS lookup and TCP connection setup occur before socket capture. They remain subject to native connection timeouts.
Other provider paths require their own transport verification; these tests do not establish universal provider interruption.
Socket timeouts bound connection setup and idle reads. A generation deadline cancels that generation without cancelling its parent run.
These limits do not cap an agent's total execution time.

Each streamed generation owns its provider diagnostics. Retry attempts update that operation's diagnostics before emitting generation events.
