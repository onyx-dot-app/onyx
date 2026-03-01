# Deep Research: Research Agent

The research agent is the workhorse of the deep research system. Each research agent receives a single research task and iteratively uses tools (search, URL reading) to gather information, then produces an intermediate report.

## Key Functions

| Function | File | Line | Purpose |
|----------|------|------|---------|
| `run_research_agent_call()` | `backend/onyx/tools/fake_tools/research_agent.py` | 205 | Single research agent execution |
| `run_research_agent_calls()` | `backend/onyx/tools/fake_tools/research_agent.py` | 644 | Parallel execution coordinator |
| `generate_intermediate_report()` | `backend/onyx/tools/fake_tools/research_agent.py` | 86 | Intermediate report generation |
| `_on_research_agent_timeout()` | `backend/onyx/tools/fake_tools/research_agent.py` | 620 | Timeout handler callback |

## Constants

| Constant | Value | Location | Purpose |
|----------|-------|----------|---------|
| `RESEARCH_AGENT_TIMEOUT_SECONDS` | 1800 (30 min) | `research_agent.py:78` | Per-agent timeout |
| `RESEARCH_AGENT_FORCE_REPORT_SECONDS` | 720 (12 min) | `research_agent.py:81` | Force report generation after this |
| `MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS` | 10000 | `research_agent.py:83` | Max tokens for intermediate report |
| `MAX_RESEARCH_CYCLES` | 8 | `prompts/deep_research/research_agent.py:5` | Max tool-calling cycles per agent |

## Single Agent Lifecycle (`run_research_agent_call`)

### Initialization (Lines 220-253)

1. Start timer for timeout tracking
2. Create `DynamicCitationProcessor` with `CitationMode.KEEP_MARKERS` -- this preserves original `[1]`, `[2]` markers in text while tracking which documents were cited
3. Extract `research_topic` from `tool_args["task"]`
4. Emit `ResearchAgentStart` packet with the research task text
5. Create initial message history with the research topic as a user message

### Research Loop (Lines 257-587)

The agent loops up to `MAX_RESEARCH_CYCLES` (8) times:

```
for each cycle:
    Check time limit (12 min) -> break if exceeded
    Check cycle limit -> break if last cycle

    Build system prompt with tool descriptions
    Call LLM with tool_choice=REQUIRED

    Check tool calls:
      generate_report -> generate_intermediate_report() -> return result
      think_tool -> append reasoning to history, continue
      real tools -> execute via run_tool_calls(), append results to history
```

### System Prompt Construction (Lines 272-312)

The system prompt is assembled dynamically:

1. **Base template**: `RESEARCH_AGENT_PROMPT` or `RESEARCH_AGENT_PROMPT_REASONING` from `prompts/deep_research/research_agent.py:8` / `research_agent.py:75`
2. **Tool descriptions**: Generated via `generate_tools_description(current_tools)` from `tools/utils.py`
3. **Conditional guidance injected**:
   - `INTERNAL_SEARCH_GUIDANCE` -- if `SearchTool` is available
   - `WEB_SEARCH_TOOL_DESCRIPTION` -- if `WebSearchTool` is available (`prompts/deep_research/dr_tool_prompts.py:17`)
   - `OPEN_URLS_TOOL_DESCRIPTION` -- if `OpenURLTool` is available (`dr_tool_prompts.py:26`)
   - For reasoning models, `OPEN_URLS_TOOL_DESCRIPTION_REASONING` is used instead (`dr_tool_prompts.py:34`)
4. **Template variables**: `{available_tools}`, `{current_datetime}`, `{current_cycle_count}`, plus the optional tool descriptions

### Tool Definitions Passed to LLM (Lines 332-347)

The research agent receives:
- Real tool definitions: `[tool.tool_definition() for tool in current_tools]` (search, web_search, open_url)
- Mock tool definitions: `get_research_agent_additional_tool_definitions(include_think_tool=not is_reasoning_model)` -- this includes `generate_report` and optionally `think_tool`

### LLM Call Configuration (Lines 343-368)

| Parameter | Value | Notes |
|-----------|-------|-------|
| `tool_choice` | `REQUIRED` | Agent must call a tool |
| `reasoning_effort` | `LOW` | Faster inference for iterative steps |
| `max_tokens` | 1000 | Safety limit to avoid infinite loops |
| `use_existing_tab_index` | `True` | Packets stay on the agent's tab |
| `is_deep_research` | `True` | Signals special deep research handling |

### Real Tool Execution (Lines 444-587)

When the agent calls real tools (search, web_search, open_url):

1. Tool calls are filtered to a single tool type per turn (`research_agent.py:380-384`) -- this is a current limitation due to the Placement system
2. `run_tool_calls()` executes the tools with `max_concurrent_tools=1`
3. For each tool response:
   - If it's a `SearchDocsResponse`, search docs are extracted and added to `state_container`
   - If it was a `WebSearchTool` call with results, set `just_ran_web_search = True` to trigger the `OPEN_URL_REMINDER_RESEARCH_AGENT` on the next cycle
   - `update_citation_processor_from_tool_response()` updates the citation processor with new documents
   - A `ToolCallInfo` is created and added to `state_container`
   - A `TOOL_CALL_RESPONSE` message is appended to the agent's local history

### Web Search -> Open URL Flow

After a web search returns results, the agent is nudged to open promising URLs:

- `just_ran_web_search` flag is set (`research_agent.py:542`)
- On the next cycle, `OPEN_URL_REMINDER_RESEARCH_AGENT` (`prompts/deep_research/research_agent.py:96`) is injected as a reminder message

## Intermediate Report Generation (`generate_intermediate_report`)

**Location**: `research_agent.py:86-202`

Called when the agent triggers `generate_report` or when cycles/time run out.

**Flow**:

1. Construct system prompt from `RESEARCH_REPORT_PROMPT` (`prompts/deep_research/research_agent.py:38`)
2. Construct reminder from `USER_REPORT_QUERY` (`research_agent.py:60`) with the original research topic
3. Build message history from the agent's local history
4. Call `run_llm_step_pkt_generator()` with:
   - `reasoning_effort=LOW`
   - `max_tokens=MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS` (10000)
   - `timeout_override=300` (5 min)
5. Translate packets:
   - `AgentResponseStart` -> `IntermediateReportStart`
   - `AgentResponseDelta` -> `IntermediateReportDelta`
6. On completion, emit `IntermediateReportCitedDocs` with the cited documents, then `SectionEnd`
7. Return the full report text

## Parallel Execution (`run_research_agent_calls`)

**Location**: `research_agent.py:644-708`

Coordinates multiple research agents running in parallel.

**Mechanism**: `run_functions_tuples_in_parallel()` from `onyx/utils/threadpool_concurrency.py`

**Configuration**:
- `allow_failures=False`
- `timeout=RESEARCH_AGENT_TIMEOUT_SECONDS` (30 min)
- `timeout_callback=_on_research_agent_timeout` -- returns a result with `RESEARCH_AGENT_TIMEOUT_MESSAGE` instead of crashing

**Post-processing** (Lines 687-708):
For each agent result:
1. If `None` (failure), append `None` to reports list
2. Otherwise, call `collapse_citations()` to renumber citations and merge into the combined mapping

Returns `CombinedResearchAgentCallResult` with all intermediate reports and the merged citation mapping.

## Error Handling

Individual research agent errors are caught at `research_agent.py:609-617`:
- Error is logged
- A `PacketException` is emitted
- `None` is returned (the orchestrator skips failed agents)

## Test Script

`research_agent.py:711-797` contains a `__main__` block for standalone testing of a single research agent call. It sets up the required infrastructure (LLM, tools, emitter, state container) and runs a single research agent with a configurable prompt.
