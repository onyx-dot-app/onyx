# Language model client

Application calls and agent loops use `LLM` for generation.
The factory selects a model and returns its configured client.
`client.info` describes the selected model, image support, and token limits.

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

`timeout` controls provider request timeouts. `total_timeout` limits the complete generation, including retries.
Both invocation methods support a total timeout. Deadline expiry interrupts owned provider I/O and raises `LLMTimeoutError`.
A generation deadline does not cancel the parent agent's signal.

## Streaming and cancellation

`stream` yields `GenerationEvent` values with isolated assistant-message snapshots.
Events describe text, thinking, tool arguments, completion, and errors.
A successful stream ends with `done`, which contains the completed assistant message.
A stream error raises after emitting its error event when generation has started.
Events also carry effective request settings for diagnostics. Presentation reads these settings from the event.
Close the stream when consumption stops early.

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
Cancellation raises `AgentCancelled` and waits for owned transport cleanup.
Each generation owns its stream accumulator, parsing state, and deadline.

## Agent with tools

An agent adds history, tool execution, and iteration to the same client.
Tool definitions reach the model. Executable callbacks belong to the agent.

```python
from onyx.agents.runtime import Agent, AgentContext
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
        execute=lambda _id, arguments, _signal, _update: ToolResult(
            content=str(arguments["text"])
        ),
    )
    return Agent(
        client,
        context=AgentContext(tools=[echo], execution=GenerationContext(flow=flow)),
    )
```

Call `agent.run(messages=[UserMessage(content="Echo hello")], max_turns=2)` to generate, execute tools, and continue.
Call `agent.abort()` to cancel its active execution.
Tools receive the same cancellation signal and must cooperate with interruption.
See [Agent execution](../agents/README.md) for snapshots, child execution, and lifecycle behavior.

## Context hooks

A context hook prepares messages and generation settings for the next turn.
It receives an isolated copy of agent context.

```python
from onyx.agents.runtime import AgentHooks, AgentTurn


def prepare_turn(context: AgentContext, turn: AgentTurn) -> AgentContext:
    if turn.is_last:
        context.tools = []
        context.system_prompt = "Answer using the information already collected."
    context.options.max_tokens = 1000
    return context


hooks = AgentHooks(transform_context=prepare_turn)
```

Pass these hooks when constructing an agent.
Onyx feature hooks use `context/messages.py` for attachments, reminders, and cache hints.
`context/prompt.py` selects history and files within the input budget.
Chat citation mapping stays in `chat/citation_utils.py`.
The helper returns shared messages. Ordinary text calls can construct messages directly.

## Provider boundary

`LitellmLLM` implements the client contract.
`LLM` is an abstract base class. Provider implementations inherit it and implement its abstract members.
`LitellmLLM` serializes shared requests and normalizes responses.
Its `LitellmTransport` owns credentials, provider requests, retries, usage accounting, and connection cleanup.
The existing factory constructs both objects.
Native tool calls take precedence over compatible tool calls recovered from text.
Recovery applies to requests with tools and keeps its state within that generation.

Provider wire messages remain internal to adapters and protocol gateways.
API proxy endpoints use `LitellmTransport.invoke` and `stream` to preserve their external protocol.
They own their generation spans.
`LitellmLLM.stream` runs in an isolated context so interleaved streams retain their own cancellation and tracing state.
Application error handling uses `client.redact_error` to remove credential values from diagnostics.
Model information exposes descriptive settings; provider credentials stay with the configured adapter.

Prompt preparation selects content and attachments. Provider serialization applies wire encoding and provider cache controls.
Signed thinking blocks survive replay. Message copies preserve shared lazy file resources without loading attachment bytes.

## Provider credentials and timeouts

Provider calls pass supported settings directly to LiteLLM. Requests never change the process environment.

| Provider | Request-scoped settings |
| --- | --- |
| Bedrock | Region, access key, secret key, session token, and bearer token. |
| Azure | API key, API base, and Azure AD token. |
| Vertex AI | Service-account credentials, workload identity mode, project, and location. |
| Other providers | Provider-prefixed API key and API base settings. |

Unsupported custom settings fail during client construction. Configure environment-only settings in the deployment.
UI routing selections remain configuration metadata and do not become provider arguments.

Socket timeouts bound connection setup and idle reads. The network coordinator also bounds waits and resource cleanup.
These limits do not cap an agent's total execution time. A caller can supply a generation timeout when its operation requires one.

Each streamed generation owns its provider diagnostics. Retry attempts update that operation's diagnostics before emitting generation events.
