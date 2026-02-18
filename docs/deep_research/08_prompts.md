# Deep Research: Prompts Reference

All prompts used by the deep research system, organized by phase and agent.

## Prompt Files

| File | Purpose |
|------|---------|
| `backend/onyx/prompts/deep_research/orchestration_layer.py` | Orchestrator, clarification, and final report prompts |
| `backend/onyx/prompts/deep_research/research_agent.py` | Research agent and intermediate report prompts |
| `backend/onyx/prompts/deep_research/dr_tool_prompts.py` | Tool description text injected into agent prompts |

## Phase 1: Clarification

### `CLARIFICATION_PROMPT`

**Location**: `orchestration_layer.py:8-25`
**Used at**: `dr_loop.py:245`
**Template variables**: `{current_datetime}`, `{internal_search_clarification_guidance}`

**Key instructions**:
- Never directly answer the user's query
- If query is already detailed (>3 sentences), call `generate_plan` tool instead
- Max 5 questions if clarification is needed
- Numbered list format
- Same language as user's query

### `INTERNAL_SEARCH_CLARIFICATION_GUIDANCE`

**Location**: `orchestration_layer.py:28-30`
**Injected when**: `SearchTool` is in the allowed tools
**Content**: Instructs to ask whether internal or web search is more appropriate.

## Phase 2: Research Plan

### `RESEARCH_PLAN_PROMPT`

**Location**: `orchestration_layer.py:34-50`
**Used at**: `dr_loop.py:306`
**Template variables**: `{current_datetime}`

**Key instructions**:
- Break query into main concepts and areas of exploration
- Stay on topic, avoid duplicates
- Emphasize up-to-date information
- MUST only output the plan (not respond to the user)
- 6 or fewer steps
- Numbered list, same language as query

### `RESEARCH_PLAN_REMINDER`

**Location**: `orchestration_layer.py:55-59`
**Used at**: `dr_loop.py:315`
**Type**: Appended as a `USER` message

**Purpose**: Reinforces that the model should only output the numbered list of steps.

## Phase 3: Orchestrator

### `ORCHESTRATOR_PROMPT` (Non-Reasoning Models)

**Location**: `orchestration_layer.py:62-106`
**Used at**: `dr_loop.py:401`
**Template variables**: `{current_datetime}`, `{current_cycle_count}`, `{max_cycles}`, `{research_plan}`, `{internal_search_research_task_guidance}`

**Key instructions**:
- Conduct research by calling `research_agent` with high-level tasks
- NEVER output normal response tokens, only call tools
- Research agent tasks should be 1-2 descriptive sentences
- CRITICAL: research_agent has NO context about the query/plan -- all context must be in the task argument
- Call research_agent MANY times before completing
- Max 3 parallel research_agent calls
- CRITICAL: Use `think_tool` between every research_agent call and before generate_report
- Never use think_tool in parallel with other tools
- Conditions for calling generate_report: all topics researched, enough info gathered, last cycle yielded minimal new info

### `ORCHESTRATOR_PROMPT_REASONING` (Reasoning Models)

**Location**: `orchestration_layer.py:156-193`
**Used at**: `dr_loop.py:403`
**Template variables**: Same as above

**Differences from non-reasoning version**:
- No `think_tool` section (reasoning models think natively)
- Instructions to "think deeply on what to do next" between calls
- Otherwise structurally identical

### `FIRST_CYCLE_REMINDER`

**Location**: `orchestration_layer.py:206-208`
**Used at**: `dr_loop.py:458-465`
**Injected on**: Cycle 1 only

**Content**: "Make sure all parts of the user question and the plan have been thoroughly explored before calling generate_report."

### `INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE`

**Location**: `orchestration_layer.py:109-113`
**Injected when**: `SearchTool` is available

**Content**: Guidance to clarify if research agent should focus on internal, web, or both search types.

## Phase 3: Research Agent

### `RESEARCH_AGENT_PROMPT` (Non-Reasoning Models)

**Location**: `prompts/deep_research/research_agent.py:8-35`
**Used at**: `research_agent.py:297`
**Template variables**: `{available_tools}`, `{current_datetime}`, `{current_cycle_count}`, `{optional_internal_search_tool_description}`, `{optional_web_search_tool_description}`, `{optional_open_url_tool_description}`

**Key instructions**:
- Thorough research over being helpful; curious but on-topic
- Iteratively call tools until done, then call `generate_report`
- NEVER output normal response tokens
- CRITICAL: Use `think_tool` after every set of searches+reads
- MUST use think_tool before web_search (except first call)
- Use think_tool before generate_report
- Reflect on key findings, reason about gaps

### `RESEARCH_AGENT_PROMPT_REASONING` (Reasoning Models)

**Location**: `prompts/deep_research/research_agent.py:75-93`
**Used at**: `research_agent.py:295`
**Template variables**: Same as above

**Differences**: No think_tool section; instructions to think between calls natively.

### `OPEN_URL_REMINDER_RESEARCH_AGENT`

**Location**: `prompts/deep_research/research_agent.py:96-99`
**Injected when**: The previous cycle used `web_search` successfully
**Used at**: `research_agent.py:316`

**Content**: Reminds to open promising pages after web_search.

## Intermediate Report

### `RESEARCH_REPORT_PROMPT`

**Location**: `prompts/deep_research/research_agent.py:38-57`
**Used at**: `research_agent.py:106`
**No template variables**

**Key instructions**:
- Organize findings from research
- Report seen by another agent, not user -- focus on facts only
- No title, no sections, no conclusions/analysis
- EXTREMELY thorough and comprehensive -- several pages long
- Remove irrelevant/duplicative information
- Flag untrustworthy or contradictory statements
- Same language as the task
- Cite ALL sources inline as `[1]`, `[2]`, etc.

### `USER_REPORT_QUERY`

**Location**: `prompts/deep_research/research_agent.py:60-71`
**Used at**: `research_agent.py:111`
**Template variables**: `{research_topic}`

**Purpose**: Reminder message for the intermediate report, restates the original topic.

## Phase 4: Final Report

### `FINAL_REPORT_PROMPT`

**Location**: `orchestration_layer.py:123-137`
**Used at**: `dr_loop.py:123`
**Template variables**: `{current_datetime}`

**Key instructions**:
- Thorough, balanced, and comprehensive answer
- Get straight to the point, no title, avoid lengthy intros
- Users expect long and detailed answer (several pages)
- Structure logically into relevant sections
- Use different text styles and formatting
- Markdown rarely when necessary
- Inline citations `[1]`, `[2]`, `[3]`

### `USER_FINAL_REPORT_QUERY`

**Location**: `orchestration_layer.py:140-152`
**Used at**: `dr_loop.py:131`
**Template variables**: `{research_plan}`

**Key instructions**:
- Includes the original research plan as reference
- CRITICAL: be extremely thorough
- Ignore format styles of intermediate reports
- Inline citations as `[1]`, `[2]` -- just a number in a bracket

## Tool Description Prompts

### `WEB_SEARCH_TOOL_DESCRIPTION`

**Location**: `dr_tool_prompts.py:17-23`
**Injected into**: Research agent system prompt

**Content**: Guidance for using web_search -- concise queries, max 3 parallel queries, avoid redundant queries.

### `OPEN_URLS_TOOL_DESCRIPTION`

**Location**: `dr_tool_prompts.py:26-32`
**Injected into**: Research agent system prompt (non-reasoning models)

**Content**: Guidance for using open_urls -- open promising pages, can open many at once, prioritize reputable sources, almost always use after web_search.

### `OPEN_URLS_TOOL_DESCRIPTION_REASONING`

**Location**: `dr_tool_prompts.py:34-40`
**Injected into**: Research agent system prompt (reasoning models)

**Difference from non-reasoning version**: Removes the reference to the `think_tool` for when to use open_urls.
