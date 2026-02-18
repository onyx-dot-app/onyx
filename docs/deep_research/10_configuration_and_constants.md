# Deep Research: Configuration and Constants

## Environment Variables

| Variable | Default | Location | Description |
|----------|---------|----------|-------------|
| `SKIP_DEEP_RESEARCH_CLARIFICATION` | `"false"` | `backend/onyx/configs/chat_configs.py:64-65` | Skip the clarification phase entirely |

## Backend Constants

### Orchestrator Constants (`dr_loop.py`)

| Constant | Value | Line | Description |
|----------|-------|------|-------------|
| `MAX_USER_MESSAGES_FOR_CONTEXT` | 5 | 77 | Max user messages included in truncated history |
| `MAX_FINAL_REPORT_TOKENS` | 20000 | 78 | Max tokens for the final report output |
| `DEEP_RESEARCH_FORCE_REPORT_SECONDS` | 1800 (30 min) | 83 | Timeout before forcing final report |
| `MAX_ORCHESTRATOR_CYCLES` | 8 | 95 | Max orchestrator iterations (non-reasoning) |
| `MAX_ORCHESTRATOR_CYCLES_REASONING` | 4 | 98 | Max orchestrator iterations (reasoning models) |

### Research Agent Constants (`research_agent.py`)

| Constant | Value | Line | Description |
|----------|-------|------|-------------|
| `RESEARCH_AGENT_TIMEOUT_SECONDS` | 1800 (30 min) | 78 | Per-agent timeout in parallel execution |
| `RESEARCH_AGENT_TIMEOUT_MESSAGE` | `"Research Agent timed out after 30 minutes"` | 79 | Message returned on timeout |
| `RESEARCH_AGENT_FORCE_REPORT_SECONDS` | 720 (12 min) | 81 | Timeout before forcing intermediate report |
| `MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS` | 10000 | 83 | Max tokens for intermediate report |
| `MAX_RESEARCH_CYCLES` | 8 | `prompts/deep_research/research_agent.py:5` | Max tool-calling cycles per agent |

### Mock Tool Constants (`dr_mock_tools.py`)

| Constant | Value | Line | Description |
|----------|-------|------|-------------|
| `GENERATE_PLAN_TOOL_NAME` | `"generate_plan"` | 1 | Clarification tool name |
| `RESEARCH_AGENT_IN_CODE_ID` | `"ResearchAgent"` | 3 | DB tool identifier |
| `RESEARCH_AGENT_TOOL_NAME` | `"research_agent"` | 4 | Orchestrator tool name |
| `RESEARCH_AGENT_TASK_KEY` | `"task"` | 5 | Key for research task argument |
| `GENERATE_REPORT_TOOL_NAME` | `"generate_report"` | 7 | Report generation tool name |
| `THINK_TOOL_NAME` | `"think_tool"` | 9 | Think/reasoning tool name |
| `THINK_TOOL_RESPONSE_MESSAGE` | `"Acknowledged, please continue."` | 112 | Response after think_tool call |
| `THINK_TOOL_RESPONSE_TOKEN_COUNT` | 10 | 113 | Approx tokens for think response |

### Prompt Constants (`orchestration_layer.py`)

| Constant | Value | Line | Description |
|----------|-------|------|-------------|
| `FIRST_CYCLE_REMINDER_TOKENS` | 100 | 205 | Approx tokens for first cycle reminder |

## LLM Call Configuration

### Orchestrator LLM Calls

| Parameter | Value | Notes |
|-----------|-------|-------|
| `tool_choice` | `REQUIRED` | Must call a tool |
| `max_tokens` | 1024 | Short output (just tool calls) |
| `custom_token_processor` | `create_think_tool_token_processor()` | Non-reasoning models only |

### Research Agent LLM Calls

| Parameter | Value | Notes |
|-----------|-------|-------|
| `tool_choice` | `REQUIRED` | Must call a tool |
| `reasoning_effort` | `LOW` | Faster iterations |
| `max_tokens` | 1000 | Safety limit |
| `use_existing_tab_index` | `True` | Stay on agent's tab |

### Intermediate Report LLM Calls

| Parameter | Value | Notes |
|-----------|-------|-------|
| `tool_choice` | `NONE` | No tools available |
| `reasoning_effort` | `LOW` | Faster generation |
| `max_tokens` | 10000 | `MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS` |
| `timeout_override` | 300 (5 min) | Long reports need more time |

### Final Report LLM Calls

| Parameter | Value | Notes |
|-----------|-------|-------|
| `tool_choice` | `NONE` | No tools available |
| `max_tokens` | 20000 | `MAX_FINAL_REPORT_TOKENS` |
| `timeout_override` | 300 (5 min) | Long reports need more time |

## Parallelism Limits

| Limit | Value | Enforced By |
|-------|-------|-------------|
| Max parallel research agents | 3 | Prompt instruction (not code-enforced) |
| Max concurrent tool calls per agent | 1 | `run_tool_calls(max_concurrent_tools=1)` at `research_agent.py:455` |
| Max parallel web search queries | 3 | Prompt instruction |

## Frontend Configuration

| Setting | Default | Location |
|---------|---------|----------|
| `deep_research_enabled` | `true` | `web/src/components/settings/lib.ts:116-118` |
| Toggle resets on session change | Yes | `web/src/hooks/useDeepResearchToggle.ts` |
| Toggle resets on assistant change | Yes | `web/src/hooks/useDeepResearchToggle.ts` |

## LLM Requirements

| Requirement | Value | Enforced At |
|-------------|-------|-------------|
| Min `max_input_tokens` | 50000 | `dr_loop.py:215-218` |

## Restrictions

| Restriction | Enforced At |
|-------------|-------------|
| Cannot use with projects | `process_message.py:870-871` |
| Only search/web_search/open_url tools allowed | `dr_loop.py:230` |
