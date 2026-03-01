# Deep Research: Architecture Overview

This document describes the high-level architecture of the Onyx Deep Research system.

## System Design

Deep Research is a multi-agent, multi-phase orchestration system that enables thorough, long-form research on user queries. It employs a hierarchical agent model:

```
                        +-----------------------+
                        |   API Entry Point     |
                        |  /send-chat-message   |
                        |  (deep_research=true) |
                        +-----------+-----------+
                                    |
                        +-----------v-----------+
                        |   Orchestrator Loop   |
                        |  (dr_loop.py)         |
                        +-----------+-----------+
                                    |
              +---------------------+---------------------+
              |                     |                     |
     +--------v--------+  +--------v--------+  +--------v--------+
     | Research Agent 1 |  | Research Agent 2 |  | Research Agent 3 |
     | (parallel)       |  | (parallel)       |  | (parallel)       |
     +--------+---------+  +--------+---------+  +--------+---------+
              |                     |                     |
        +-----+-----+        +-----+-----+        +-----+-----+
        |  SearchTool |        | WebSearch |        | OpenURL   |
        |  WebSearch  |        | OpenURL   |        | SearchTool|
        |  OpenURL    |        | SearchTool|        | WebSearch |
        +-------------+        +-----------+        +-----------+
```

## Execution Phases

The system operates in four sequential phases:

| Phase | Name | Purpose | Optional |
|-------|------|---------|----------|
| 1 | Clarification | Ask user for missing context | Yes |
| 2 | Research Plan | Generate a structured 5-6 step plan | No |
| 3 | Research Execution | Iterative orchestration of research agents | No |
| 4 | Final Report | Synthesize all findings into a comprehensive answer | No |

See [02_execution_phases.md](./02_execution_phases.md) for detailed phase descriptions.

## Key Architectural Decisions

### Hierarchical Agent Model

The system uses a two-level agent hierarchy:

- **Orchestrator** (top level): Decides which research tasks to delegate, when to think, and when to produce the final report. It does not perform research directly.
- **Research Agents** (second level): Execute actual research using tools (search, URL reading). Each agent operates independently on a single research task and produces an intermediate report.

### Mock Tools for Control Flow

The orchestrator and research agents use "mock tools" -- tool definitions presented to the LLM that are not backed by real tool implementations. Instead, the system intercepts these tool calls to control execution flow:

| Mock Tool | Used By | Purpose |
|-----------|---------|---------|
| `generate_plan` | Clarification LLM | Signals that clarification is not needed |
| `research_agent` | Orchestrator | Delegates a research task |
| `generate_report` | Orchestrator & Research Agent | Signals completion |
| `think_tool` | Orchestrator & Research Agent | Chain-of-thought reasoning for non-reasoning models |

See [05_mock_tools.md](./05_mock_tools.md) for details.

### Parallel Research Agents

The orchestrator can dispatch up to 3 research agents in parallel per cycle. Each agent runs in its own thread via `run_functions_tuples_in_parallel()`. Citations from parallel agents are renumbered and merged using `collapse_citations()`.

### Reasoning Model Awareness

The system detects whether the LLM is a reasoning model (e.g., o1, o3) and adapts:

- **Non-reasoning models**: Use the `think_tool` for chain-of-thought, get 8 max orchestrator cycles
- **Reasoning models**: Use native reasoning, get 4 max orchestrator cycles (since thinking is baked in), skip `think_tool`

### Streaming Architecture

All output is streamed as typed packets via an `Emitter` / `Queue` system. Each packet carries a `Placement` object that tells the frontend exactly where to render it in the timeline UI.

See [06_streaming_and_packets.md](./06_streaming_and_packets.md) for the packet system.

## File Organization

```
backend/onyx/
  deep_research/
    dr_loop.py               # Main orchestration loop
    dr_mock_tools.py          # Mock tool definitions
    models.py                 # Pydantic models
    utils.py                  # Think tool processor, special tool detection
  tools/fake_tools/
    research_agent.py         # Research agent implementation
  prompts/deep_research/
    orchestration_layer.py    # Orchestrator & clarification prompts
    research_agent.py         # Research agent & report prompts
    dr_tool_prompts.py        # Tool description prompts

web/src/
  hooks/
    useDeepResearchToggle.ts  # Toggle state management
  app/app/
    services/streamingModels.ts   # Packet type definitions
    message/messageComponents/
      timeline/renderers/deepresearch/
        DeepResearchPlanRenderer.tsx   # Plan UI
        ResearchAgentRenderer.tsx      # Research agent UI
```

## Related Documents

- [02_execution_phases.md](./02_execution_phases.md) -- Detailed phase-by-phase execution flow
- [03_orchestrator.md](./03_orchestrator.md) -- Orchestrator agent internals
- [04_research_agent.md](./04_research_agent.md) -- Research agent internals
- [05_mock_tools.md](./05_mock_tools.md) -- Mock tool definitions and control flow
- [06_streaming_and_packets.md](./06_streaming_and_packets.md) -- Streaming packet system
- [07_citation_system.md](./07_citation_system.md) -- Citation tracking and merging
- [08_prompts.md](./08_prompts.md) -- All LLM prompts
- [09_frontend.md](./09_frontend.md) -- Frontend integration
- [10_configuration_and_constants.md](./10_configuration_and_constants.md) -- Configuration reference
- [11_database_schema.md](./11_database_schema.md) -- Database models and migrations
