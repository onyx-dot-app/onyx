# Shared LLM streaming events

`LLM.stream` emits ordered generation events. Apply them with
`apply_generation_event` to build an `AssistantMessage`.

Tool calls use three events, each identified by `content_index`:

| Event | Content |
| --- | --- |
| `ToolCallStartEvent` | The call ID and tool name. |
| `ToolCallDeltaEvent` | Only the new argument text, in `arguments_delta`. |
| `ToolCallEndEvent` | The complete `ToolCall`, including parsed arguments or an argument error. |

During streaming, unfinished argument text accumulates in `ToolCall.raw_arguments`.
Parsed `arguments` become available at completion. Do not execute incomplete calls.
Consumers that display arguments during streaming can decode the raw fragments.

The accumulator parses arguments at completion instead of reparsing and copying
all accumulated arguments for each fragment. Delta events contain strings, so
listeners can share them when they have no mutable request metadata.

Text and thinking events carry content indices. Thinking events can also contain
provider replay blocks. Lifecycle events carry status and usage; they do not
contain message snapshots. A successful generation ends with `GenerationDoneEvent`.

This contract applies to `LLM.stream`. The lower-level `stream_raw` method keeps
its provider chunk format. Existing chat and gateway consumers of raw chunks
continue to accumulate those chunks separately.
