# Deep Research: Execution Phases

All phases are orchestrated by `run_deep_research_llm_loop()` in `backend/onyx/deep_research/dr_loop.py:188`.

## Phase 1: Clarification (Optional)

**Location**: `dr_loop.py:236-299`

**Purpose**: Determine whether the user's query needs clarification before research begins.

**Skip conditions** (any of these bypasses this phase):
- `SKIP_DEEP_RESEARCH_CLARIFICATION` env var is `"true"` (see `backend/onyx/configs/chat_configs.py:64`)
- `skip_clarification=True` is passed (happens when the user already answered a prior clarification)
- The detection of `skip_clarification` is done via `is_last_assistant_message_clarification()` in `backend/onyx/chat/chat_utils.py`

**Flow**:

1. Construct system prompt using `CLARIFICATION_PROMPT` from `backend/onyx/prompts/deep_research/orchestration_layer.py:8`
2. Build truncated message history with `construct_message_history()`, limited to last `MAX_USER_MESSAGES_FOR_CONTEXT=5` user messages
3. Call `run_llm_step()` at `dr_loop.py:269` with:
   - Tool definitions: `get_clarification_tool_definitions()` which returns only `[GENERATE_PLAN_TOOL_DESCRIPTION]`
   - Tool choice: `AUTO` (LLM decides whether to call the tool or respond with text)
   - Placement: `turn_index=0`
4. **Decision point** (`dr_loop.py:286`):
   - If the LLM **did not** call the `generate_plan` tool -> the LLM's text response is a clarification question. Mark the turn as clarification via `state_container.set_is_clarification(True)`, emit `OverallStop`, and return early. The user must respond before research continues.
   - If the LLM **did** call `generate_plan` -> proceed to Phase 2.

**Packets emitted**: Standard `AgentResponseStart`/`AgentResponseDelta` (if clarification), or nothing visible (if proceeding).

## Phase 2: Research Plan Generation

**Location**: `dr_loop.py:302-384`

**Purpose**: Generate a numbered, 5-6 step research plan.

**Flow**:

1. Construct system prompt using `RESEARCH_PLAN_PROMPT` from `orchestration_layer.py:34`
2. Append `RESEARCH_PLAN_REMINDER` (`orchestration_layer.py:55`) as a user-type message to reinforce plan-only output
3. Build truncated history with `construct_message_history()`
4. Call `run_llm_step_pkt_generator()` at `dr_loop.py:330` -- this is the streaming generator variant
5. **Packet translation** (`dr_loop.py:346-364`):
   - `AgentResponseStart` -> `DeepResearchPlanStart`
   - `AgentResponseDelta` -> `DeepResearchPlanDelta` (carries `content` field with plan text chunks)
   - Other packets (e.g., `ReasoningStart`, `ReasoningDelta`) pass through unchanged
6. On `StopIteration`, emit a `SectionEnd` packet
7. Extract the full plan text from `llm_step_result.answer` (`dr_loop.py:381`)

**Output**: The plan is stored in the `research_plan` variable and used in Phase 3. If the plan is `None`, a `RuntimeError` is raised.

**Packets emitted**: `DeepResearchPlanStart`, `DeepResearchPlanDelta` (streamed), `SectionEnd`

## Phase 3: Research Execution

**Location**: `dr_loop.py:386-764`

**Purpose**: Iteratively dispatch research agents and accumulate findings.

This is the core of deep research. The orchestrator LLM runs in a loop, deciding on each cycle whether to:
- Dispatch research agent(s) via the `research_agent` mock tool
- Reason about findings via the `think_tool` mock tool
- Generate the final report via the `generate_report` mock tool

### Orchestrator Loop

**Loop bounds**: `dr_loop.py:426` -- iterates up to `MAX_ORCHESTRATOR_CYCLES` (8 for non-reasoning, 4 for reasoning models).

**Per-cycle flow**:

1. **Timeout/last-cycle check** (`dr_loop.py:429-456`): If elapsed time > `DEEP_RESEARCH_FORCE_REPORT_SECONDS` (30 min) or this is the last cycle, skip to `generate_final_report()`.

2. **First cycle reminder** (`dr_loop.py:458-465`): On cycle 1, append `FIRST_CYCLE_REMINDER` to encourage thorough research.

3. **Orchestrator LLM call** (`dr_loop.py:502-527`):
   - System prompt: `ORCHESTRATOR_PROMPT` or `ORCHESTRATOR_PROMPT_REASONING` (from `orchestration_layer.py:62` / `orchestration_layer.py:156`)
   - Tool definitions: `get_orchestrator_tools(include_think_tool=not is_reasoning_model)`
   - Tool choice: `REQUIRED` (model must call a tool)
   - Max tokens: 1024 (orchestrator output is just tool calls, never long)
   - Custom token processor: `create_think_tool_token_processor()` for non-reasoning models

4. **Tool call dispatch** (`dr_loop.py:562-764`):

   The result is checked via `check_special_tool_calls()` (`deep_research/utils.py:203`):

   - **`generate_report`** (`dr_loop.py:564-584`): Calls `generate_final_report()` and breaks the loop.
   - **`think_tool`** (`dr_loop.py:585-624`): Processes the reasoning, appends think_tool call + response to chat history, continues loop.
   - **`research_agent`** (`dr_loop.py:626-763`): Collects all `research_agent` tool calls, runs them in parallel via `run_research_agent_calls()`, merges results back into chat history with citations.

### Research Agent Execution (within Phase 3)

Each `research_agent` tool call triggers `run_research_agent_call()` in `backend/onyx/tools/fake_tools/research_agent.py:205`. Up to 3 run in parallel.

See [04_research_agent.md](./04_research_agent.md) for the full research agent lifecycle.

### Citation Merging

After parallel research agents complete, `collapse_citations()` renumbers citations and merges mappings. See [07_citation_system.md](./07_citation_system.md).

## Phase 4: Final Report Generation

**Location**: `dr_loop.py:101-184` (`generate_final_report()`)

**Purpose**: Produce a comprehensive, well-cited final answer using all research findings.

**Flow**:

1. Construct system prompt using `FINAL_REPORT_PROMPT` from `orchestration_layer.py:123`
2. Construct a reminder using `USER_FINAL_REPORT_QUERY` (`orchestration_layer.py:140`) that includes the original research plan
3. Build history via `construct_message_history()` -- this includes the full chat history with all intermediate reports and tool call responses
4. Initialize `DynamicCitationProcessor` and populate it with the accumulated `citation_mapping` from all research agents
5. Call `run_llm_step()` at `dr_loop.py:153` with:
   - No tool definitions (empty list)
   - Tool choice: `NONE`
   - Max tokens: `MAX_FINAL_REPORT_TOKENS = 20000`
   - Timeout: 300 seconds (5 min read timeout)
   - `is_deep_research=True`
6. Save citation mapping to `state_container` for DB persistence
7. If saved reasoning from a prior `think_tool` call exists, attach it via `state_container.set_reasoning_tokens()`

**Packets emitted**: `AgentResponseStart`, `AgentResponseDelta` (the final answer text, streamed)

## Overall Stop

After Phase 4 completes (or Phase 1 returns a clarification), the system emits:

```python
Packet(placement=Placement(turn_index=final_turn_index), obj=OverallStop(type="stop"))
```

This signals the frontend that the deep research session is complete (`dr_loop.py:765-770`).
