# Deep Research: Mock Tools

Mock tools are tool definitions presented to the LLM that are intercepted by the system rather than executed by real tool implementations. They provide structured control flow between the system and the LLM.

## Definitions

All mock tool definitions are in `backend/onyx/deep_research/dr_mock_tools.py`.

Tool name constants are also duplicated in `backend/onyx/prompts/deep_research/dr_tool_prompts.py:1-11` (used for prompt template references).

### `generate_plan`

**Name constant**: `GENERATE_PLAN_TOOL_NAME = "generate_plan"` (`dr_mock_tools.py:1`)
**Definition**: `dr_mock_tools.py:13-24`

```json
{
  "name": "generate_plan",
  "description": "No clarification needed, generate a research plan for the user's query.",
  "parameters": { "properties": {}, "required": [] }
}
```

**Used by**: Clarification phase
**Purpose**: The LLM calls this tool to signal that the user's query is clear enough -- no clarification questions needed. If the LLM responds with text instead of calling this tool, that text is treated as a clarification question.
**No parameters**.

### `research_agent`

**Name constant**: `RESEARCH_AGENT_TOOL_NAME = "research_agent"` (`dr_mock_tools.py:4`)
**Task key constant**: `RESEARCH_AGENT_TASK_KEY = "task"` (`dr_mock_tools.py:5`)
**Definition**: `dr_mock_tools.py:27-43`

```json
{
  "name": "research_agent",
  "description": "Conduct research on a specific topic.",
  "parameters": {
    "properties": {
      "task": {
        "type": "string",
        "description": "The research task to investigate, should be 1-2 descriptive sentences..."
      }
    },
    "required": ["task"]
  }
}
```

**Used by**: Orchestrator
**Purpose**: Delegates a research task to a research agent. The `task` argument becomes the agent's research topic.
**Parameters**: `task` (string, required) -- 1-2 descriptive sentences.

### `generate_report`

**Name constant**: `GENERATE_REPORT_TOOL_NAME = "generate_report"` (`dr_mock_tools.py:7`)
**Definitions**:
- Orchestrator version: `dr_mock_tools.py:46-57`
- Research agent version: `RESEARCH_AGENT_GENERATE_REPORT_TOOL_DESCRIPTION` (`dr_mock_tools.py:98-109`)

```json
{
  "name": "generate_report",
  "description": "Generate the final research report from all of the findings...",
  "parameters": { "properties": {}, "required": [] }
}
```

**Used by**: Both orchestrator and research agents
**Purpose**:
- In the **orchestrator**: Signals that research is complete, triggers `generate_final_report()`
- In the **research agent**: Signals that the agent has gathered enough information, triggers `generate_intermediate_report()`
**No parameters**.

### `think_tool`

**Name constant**: `THINK_TOOL_NAME = "think_tool"` (`dr_mock_tools.py:9`)
**Definitions**:
- Orchestrator version: `THINK_TOOL_DESCRIPTION` (`dr_mock_tools.py:60-76`)
- Research agent version: `RESEARCH_AGENT_THINK_TOOL_DESCRIPTION` (`dr_mock_tools.py:79-95`)

```json
{
  "name": "think_tool",
  "description": "Use this for reasoning between research_agent calls...",
  "parameters": {
    "properties": {
      "reasoning": {
        "type": "string",
        "description": "Your chain of thought reasoning, use paragraph format, no lists."
      }
    },
    "required": ["reasoning"]
  }
}
```

**Used by**: Both orchestrator and research agents (only for non-reasoning models)
**Purpose**: Enables chain-of-thought reasoning for models that don't have native reasoning. The `reasoning` argument text is converted into reasoning tokens for the UI via `create_think_tool_token_processor()`.
**Parameters**: `reasoning` (string, required)

The orchestrator version description says "Use this for reasoning between research_agent calls and before calling generate_report." The research agent version says "Use this for reasoning between research steps."

## Accessor Functions

| Function | Location | Returns | Used By |
|----------|----------|---------|---------|
| `get_clarification_tool_definitions()` | `dr_mock_tools.py:116` | `[GENERATE_PLAN_TOOL_DESCRIPTION]` | Phase 1 |
| `get_orchestrator_tools(include_think_tool)` | `dr_mock_tools.py:120` | `[research_agent, generate_report, (think_tool)]` | Phase 3 orchestrator |
| `get_research_agent_additional_tool_definitions(include_think_tool)` | `dr_mock_tools.py:130` | `[generate_report, (think_tool)]` | Research agent |

## Constants

| Constant | Value | Location | Purpose |
|----------|-------|----------|---------|
| `THINK_TOOL_RESPONSE_MESSAGE` | `"Acknowledged, please continue."` | `dr_mock_tools.py:112` | Response injected into chat history after think_tool |
| `THINK_TOOL_RESPONSE_TOKEN_COUNT` | `10` | `dr_mock_tools.py:113` | Approximate token count for the response |
| `RESEARCH_AGENT_IN_CODE_ID` | `"ResearchAgent"` | `dr_mock_tools.py:3` | Used for DB tool lookup |

## Detection Logic

Mock tool calls are detected by `check_special_tool_calls()` in `backend/onyx/deep_research/utils.py:203-216`:

```python
def check_special_tool_calls(tool_calls: list[ToolCallKickoff]) -> SpecialToolCalls:
    # Scans tool_calls for think_tool and generate_report
    # Returns SpecialToolCalls with the detected calls (or None)
```

This returns a `SpecialToolCalls` model (`deep_research/models.py:7-9`) with optional `think_tool_call` and `generate_report_tool_call` fields.

## Think Tool Token Processor

For non-reasoning models, the `think_tool` arguments are streamed as reasoning content in the UI. This is handled by `create_think_tool_token_processor()` in `backend/onyx/deep_research/utils.py:121-200`.

The processor:
1. Detects think_tool calls in streaming deltas
2. Strips the JSON wrapper (`{"reasoning": "...content..."}`)
3. Unescapes JSON string escape sequences
4. Converts the content to `Delta(reasoning_content=chunk)` for the UI
5. On flush, returns the complete tool call for proper chat history

**State class**: `ThinkToolProcessorState` (`utils.py:21-32`)

**JSON parsing details**:
- Looks for prefixes: `'{"reasoning": "'` or `'{"reasoning":"'`
- Holds back 3 characters to avoid splitting escape sequences or emitting the closing `"}`
- Uses `_unescape_json_string()` (`utils.py:35-60`) for `\n`, `\r`, `\t`, `\"`, `\\`
