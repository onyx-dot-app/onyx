# Deep Research: Database Schema

## Migrations

Deep research introduced several database changes via Alembic migrations.

### Main Migration

**File**: `backend/alembic/versions/5ae8240accb3_add_research_agent_database_tables_and_.py`

This migration creates the core tables for persisting deep research state.

### Chat Message Extensions

New columns added to the `chat_message` table:

| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `research_type` | `VARCHAR` | Yes | Type of research (e.g., "LEGACY_AGENTIC") |
| `research_plan` | `JSONB` | Yes | The research plan generated in Phase 2 |
| `is_clarification` | `BOOLEAN` | No | `True` if message is a clarification question |

**Model reference**: `backend/onyx/db/models.py:2549` -- `is_clarification: Mapped[bool]`

### `research_agent_iteration` Table

Stores each orchestrator cycle's metadata.

| Column | Type | Nullable | Constraints | Purpose |
|--------|------|----------|-------------|---------|
| `id` | `INTEGER` | No | PK, autoincrement | Row identifier |
| `primary_question_id` | `INTEGER` | No | FK -> `chat_message.id`, CASCADE | Links to the user's original message |
| `iteration_nr` | `INTEGER` | No | | Orchestrator cycle number |
| `created_at` | `DATETIME(tz)` | No | | Timestamp |
| `purpose` | `VARCHAR` | Yes | | Purpose/description of the iteration |
| `reasoning` | `VARCHAR` | Yes | | Reasoning content (from think_tool or native reasoning) |

**Unique constraint**: `(primary_question_id, iteration_nr)`

### `research_agent_iteration_sub_step` Table

Stores each individual tool call within a research agent's execution.

| Column | Type | Nullable | Constraints | Purpose |
|--------|------|----------|-------------|---------|
| `id` | `INTEGER` | No | PK, autoincrement | Row identifier |
| `primary_question_id` | `INTEGER` | No | FK -> `chat_message.id`, CASCADE | Links to original message |
| `iteration_nr` | `INTEGER` | No | | Parent orchestrator cycle |
| `iteration_sub_step_nr` | `INTEGER` | No | | Step number within the agent |
| `created_at` | `DATETIME(tz)` | No | | Timestamp |
| `sub_step_instructions` | `VARCHAR` | Yes | | The research task given to the agent |
| `sub_step_tool_id` | `INTEGER` | Yes | FK -> `tool.id` | Which tool was used |
| `reasoning` | `VARCHAR` | Yes | | Agent's reasoning for this step |
| `sub_answer` | `VARCHAR` | Yes | | Tool response / agent's findings |
| `cited_doc_results` | `JSONB` | Yes | | Cited documents from this step |
| `claims` | `JSONB` | Yes | | Claims extracted from results |
| `generated_images` | `JSONB` | Yes | | Any generated images |
| `additional_data` | `JSONB` | Yes | | Extensible metadata |

**Composite FK**: `(primary_question_id, iteration_nr)` -> `research_agent_iteration`

### Tool Registration

**File**: `backend/alembic/versions/c1d2e3f4a5b6_add_deep_research_tool.py`

Inserts a tool record for the research agent:

| Field | Value |
|-------|-------|
| `name` | `"ResearchAgent"` |
| `display_name` | `"Research Agent"` |
| `in_code_tool_id` | `"ResearchAgent"` |
| `enabled` | `false` |

This tool ID is referenced at runtime via `get_tool_by_name(tool_name=RESEARCH_AGENT_TOOL_NAME, db_session=db_session)` at `dr_loop.py:740-743`.

### Additional Migrations

| File | Purpose |
|------|---------|
| `f8a9b2c3d4e5_*.py` | Adds `research_answer_purpose` column to `chat_message` |
| `f9b8c7d6e5a4_*.py` | Updates `parent_question_id` foreign key in `research_agent_iteration` |
| `bd7c3bf8beba_*.py` | Migrates legacy agent responses to `research_agent_iteration` format |

## State Persistence

During deep research execution, the `ChatStateContainer` accumulates state:

| Method | What It Stores | Persisted To |
|--------|---------------|-------------|
| `add_tool_call(tool_call_info)` | Tool call details (args, response, docs) | `research_agent_iteration_sub_step` |
| `set_citation_mapping(mapping)` | Citation number -> document mapping | `chat_message` (via completion callback) |
| `set_is_clarification(True)` | Mark turn as clarification | `chat_message.is_clarification` |
| `set_reasoning_tokens(reasoning)` | Think tool / native reasoning text | `research_agent_iteration.reasoning` |

The `llm_loop_completion_callback` (referenced in `process_message.py:877-879`) handles persisting the accumulated state to the database after the deep research loop completes.

## Pydantic Models

**File**: `backend/onyx/deep_research/models.py`

```python
class SpecialToolCalls(BaseModel):          # line 7
    think_tool_call: ToolCallKickoff | None = None
    generate_report_tool_call: ToolCallKickoff | None = None

class ResearchAgentCallResult(BaseModel):   # line 12
    intermediate_report: str
    citation_mapping: CitationMapping

class CombinedResearchAgentCallResult(BaseModel):  # line 17
    intermediate_reports: list[str | None]
    citation_mapping: CitationMapping
```

## Chat State Container

**File**: `backend/onyx/chat/chat_state.py`

Deep-research-relevant fields and methods:

| Member | Type | Line | Purpose |
|--------|------|------|---------|
| `is_clarification` | `bool` | 47 | Whether this turn is a clarification |
| `set_reasoning_tokens()` | method | 61 | Save reasoning text |
| `set_is_clarification()` | method | 76 | Set clarification flag (thread-safe) |
| `get_is_clarification()` | method | 101 | Get clarification flag (thread-safe) |
| `set_citation_mapping()` | method | -- | Save final citation mapping |
| `add_tool_call()` | method | -- | Add a tool call info record |
| `add_search_docs()` | method | -- | Add search documents |
