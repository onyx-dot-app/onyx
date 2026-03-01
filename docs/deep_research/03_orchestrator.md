# Deep Research: Orchestrator Agent

The orchestrator is the top-level control agent in deep research. It does not perform research itself -- it delegates research tasks to research agents and decides when enough information has been gathered.

## Entry Point

**Function**: `run_deep_research_llm_loop()`
**File**: `backend/onyx/deep_research/dr_loop.py:188`

**Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `emitter` | `Emitter` | Streaming packet emitter |
| `state_container` | `ChatStateContainer` | Thread-safe state for the chat turn |
| `simple_chat_history` | `list[ChatMessageSimple]` | Existing conversation history |
| `tools` | `list[Tool]` | All available tools (filtered internally) |
| `custom_agent_prompt` | `str \| None` | Custom persona prompt (currently unused, `noqa: ARG001`) |
| `llm` | `LLM` | The LLM instance |
| `token_counter` | `Callable[[str], int]` | Token counting function |
| `db_session` | `Session` | SQLAlchemy session |
| `skip_clarification` | `bool` | Whether to skip Phase 1 |
| `user_identity` | `LLMUserIdentity \| None` | User identity for tracing |
| `chat_session_id` | `str \| None` | Chat session ID for tracing |
| `all_injected_file_metadata` | `dict[str, FileToolMetadata] \| None` | Injected file metadata |

## LLM Requirements

The orchestrator requires an LLM with at least 50,000 `max_input_tokens`. If this requirement is not met, a `RuntimeError` is raised at `dr_loop.py:215-218`.

## Tool Filtering

Before the orchestrator loop begins, the tool list is filtered to only allow:

```python
allowed_tool_names = {SearchTool.NAME, WebSearchTool.NAME, OpenURLTool.NAME}
```

**Reference**: `dr_loop.py:230`

These filtered tools are passed to the research agents, not the orchestrator itself. The orchestrator only uses mock tools (`research_agent`, `generate_report`, `think_tool`).

## Orchestrator Loop Mechanics

**Loop**: `dr_loop.py:426-764`

### Cycle Limits

| Model Type | Max Cycles | Constant |
|-----------|-----------|----------|
| Non-reasoning | 8 | `MAX_ORCHESTRATOR_CYCLES` (`dr_loop.py:95`) |
| Reasoning | 4 | `MAX_ORCHESTRATOR_CYCLES_REASONING` (`dr_loop.py:98`) |

### Prompt Selection

| Model Type | Prompt | Location |
|-----------|--------|----------|
| Non-reasoning | `ORCHESTRATOR_PROMPT` | `orchestration_layer.py:62` |
| Reasoning | `ORCHESTRATOR_PROMPT_REASONING` | `orchestration_layer.py:156` |

Both prompts are formatted with:
- `{current_datetime}` -- current date/time
- `{current_cycle_count}` -- current cycle number
- `{max_cycles}` -- maximum cycles allowed
- `{research_plan}` -- the plan generated in Phase 2
- `{internal_search_research_task_guidance}` -- guidance for internal vs. web search (if applicable)

### Per-Cycle Decision Tree

```
Orchestrator LLM call (tool_choice=REQUIRED)
    |
    +-- generate_report called?
    |       YES -> generate_final_report() -> break
    |
    +-- think_tool called?
    |       YES -> Save reasoning to history, continue loop
    |
    +-- research_agent called?
    |       YES -> Collect all research_agent calls
    |              If >1 call: emit TopLevelBranching packet
    |              run_research_agent_calls() in parallel
    |              Merge citations
    |              Append results to chat history
    |              Continue loop
    |
    +-- No tool calls?
            Cycle 0: RuntimeError
            Other cycles: Force generate_final_report() -> break
```

### Think Tool Processing (Non-Reasoning Models)

When a `think_tool` call is detected (`dr_loop.py:585-624`):

1. The reasoning text is available via `state_container.reasoning_tokens` (because the custom `create_think_tool_token_processor()` converts tool call arguments to reasoning content during streaming)
2. An assistant message with the tool call is appended to `simple_chat_history`
3. A tool response message (`"Acknowledged, please continue."`) is appended
4. The loop continues without incrementing the cycle count (thinking is "free")

### Research Agent Dispatch

When `research_agent` tool calls are detected (`dr_loop.py:626-763`):

1. Tool calls are collected into `research_agent_calls`
2. If multiple parallel calls, a `TopLevelBranching` packet is emitted (`dr_loop.py:661-673`)
3. `run_research_agent_calls()` is invoked (`research_agent.py:644`), which:
   - Runs agents in parallel threads
   - Returns `CombinedResearchAgentCallResult` with merged citations
4. Results are stored as `ToolCallInfo` entries via `state_container.add_tool_call()`
5. Intermediate reports are appended to `simple_chat_history` as `TOOL_CALL_RESPONSE` messages

### Timeout Handling

**Constant**: `DEEP_RESEARCH_FORCE_REPORT_SECONDS = 30 * 60` (30 minutes, `dr_loop.py:83`)

At the start of each cycle (`dr_loop.py:429-430`), elapsed time is checked. If exceeded, the system logs a warning and immediately calls `generate_final_report()`.

Note: The actual total runtime can exceed 30 minutes because a research cycle starting at minute 29 could run for up to another 30 minutes (the research agent has its own timeout).

## Turn Index Tracking

The orchestrator maintains `final_turn_index` to track the current position in the UI timeline:

- Base: `orchestrator_start_turn_index` (1, or 2 if plan generation had reasoning)
- Per cycle: `+cycle`
- Per reasoning step: `+reasoning_cycles`

This ensures packets are placed correctly in the frontend timeline.
