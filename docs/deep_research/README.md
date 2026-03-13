# Onyx Deep Research -- Technical Documentation

This document set provides a comprehensive reference for the Onyx Deep Research system. It is intended to serve as a resource for understanding, evaluating, and improving the deep research implementation.

## What is Deep Research?

Deep Research is a multi-agent, multi-phase system within Onyx that conducts thorough, long-form research on user queries. Rather than producing a single LLM response, it:

1. Optionally asks the user for clarification
2. Generates a structured research plan (5-6 steps)
3. Iteratively dispatches parallel research agents that use search and URL reading tools
4. Synthesizes all findings into a comprehensive, cited final report

A single deep research session can involve dozens of LLM calls, multiple parallel research agents, and hundreds of documents -- producing a final report that is several pages long with inline citations.

## System at a Glance

```
User Query
    |
    v
[Phase 1] Clarification (optional) ------> Ask user questions, wait for response
    |
    v
[Phase 2] Plan Generation ----------------> 5-6 step numbered research plan
    |
    v
[Phase 3] Research Execution Loop --------> Up to 8 orchestrator cycles
    |                                           |
    |   +-----------------------------------+   |
    |   | Orchestrator decides:             |   |
    |   |   - research_agent (1-3 parallel) |   |
    |   |   - think_tool (reasoning)        |   |
    |   |   - generate_report (done)        |   |
    |   +-----------------------------------+   |
    |       |                                   |
    |       v                                   |
    |   Research Agent (per task):              |
    |     - web_search / search / open_url     |
    |     - think_tool (reasoning)             |
    |     - generate_report -> intermediate    |
    |                          report          |
    |                                           |
    v
[Phase 4] Final Report --------------------> Comprehensive cited answer
```

## Key Implementation Files

### Backend Core

| File | Purpose | Key Function |
|------|---------|--------------|
| `backend/onyx/deep_research/dr_loop.py` | Main orchestration loop | `run_deep_research_llm_loop()` (line 188) |
| `backend/onyx/tools/fake_tools/research_agent.py` | Research agent execution | `run_research_agent_call()` (line 205) |
| `backend/onyx/deep_research/dr_mock_tools.py` | Mock tool definitions | `get_orchestrator_tools()` (line 120) |
| `backend/onyx/deep_research/models.py` | Data models | `ResearchAgentCallResult` (line 12) |
| `backend/onyx/deep_research/utils.py` | Utilities | `create_think_tool_token_processor()` (line 121) |

### Prompts

| File | Purpose |
|------|---------|
| `backend/onyx/prompts/deep_research/orchestration_layer.py` | Clarification, plan, orchestrator, and final report prompts |
| `backend/onyx/prompts/deep_research/research_agent.py` | Research agent and intermediate report prompts |
| `backend/onyx/prompts/deep_research/dr_tool_prompts.py` | Tool-specific description text |

### API Layer

| File | Purpose | Key Reference |
|------|---------|---------------|
| `backend/onyx/chat/process_message.py` | Routes to deep research | Lines 869-893 |
| `backend/onyx/server/query_and_chat/models.py` | Request model | `SendMessageRequest.deep_research` (line 99) |
| `backend/onyx/server/query_and_chat/streaming_models.py` | Packet types | Lines 49-54 (enum), 302-341 (classes) |
| `backend/onyx/server/query_and_chat/placement.py` | UI positioning | `Placement` class (line 4) |

### Frontend

| File | Purpose |
|------|---------|
| `web/src/hooks/useDeepResearchToggle.ts` | Toggle state management |
| `web/src/sections/input/AppInputBar.tsx` | Deep Research button (lines 386-398, 706-717) |
| `web/src/app/app/services/streamingModels.ts` | TypeScript packet types (lines 54-59) |
| `web/src/app/app/message/messageComponents/timeline/renderers/deepresearch/DeepResearchPlanRenderer.tsx` | Plan renderer |
| `web/src/app/app/message/messageComponents/timeline/renderers/deepresearch/ResearchAgentRenderer.tsx` | Research agent renderer (385 lines) |
| `web/src/app/app/message/messageComponents/renderMessageComponent.tsx` | Renderer dispatch (lines 89-123) |

## Key Constants

| Constant | Value | Description |
|----------|-------|-------------|
| Max orchestrator cycles | 8 (non-reasoning) / 4 (reasoning) | How many times the orchestrator can loop |
| Max research cycles per agent | 8 | Tool-calling cycles within a single agent |
| Max parallel agents | 3 | Parallel research agents per orchestrator cycle |
| Orchestrator timeout | 30 minutes | Forces final report generation |
| Agent forced report timeout | 12 minutes | Forces intermediate report within an agent |
| Agent hard timeout | 30 minutes | Thread-level timeout for parallel execution |
| Final report max tokens | 20,000 | Output token limit for the final report |
| Intermediate report max tokens | 10,000 | Output token limit per intermediate report |
| Min LLM input tokens | 50,000 | LLM must support at least this context window |

## Documents

| # | Document | Description |
|---|----------|-------------|
| 01 | [Architecture Overview](./01_architecture_overview.md) | High-level system design, agent hierarchy, key decisions |
| 02 | [Execution Phases](./02_execution_phases.md) | Phase-by-phase execution flow with code references |
| 03 | [Orchestrator Agent](./03_orchestrator.md) | Orchestrator loop mechanics, decision tree, timeout handling |
| 04 | [Research Agent](./04_research_agent.md) | Research agent lifecycle, tool execution, intermediate reports |
| 05 | [Mock Tools](./05_mock_tools.md) | Mock tool definitions, detection logic, think tool processor |
| 06 | [Streaming and Packets](./06_streaming_and_packets.md) | Packet types, flow by phase, translation, frontend consumption |
| 07 | [Citation System](./07_citation_system.md) | KEEP_MARKERS mode, citation flow, merging across agents |
| 08 | [Prompts Reference](./08_prompts.md) | Every prompt with location, template variables, key instructions |
| 09 | [Frontend Integration](./09_frontend.md) | Toggle hook, renderers, API integration, data flow |
| 10 | [Configuration and Constants](./10_configuration_and_constants.md) | All constants, env vars, LLM call config, limits |
| 11 | [Database Schema](./11_database_schema.md) | Migrations, tables, state persistence, Pydantic models |

## Quick Reference: Function Call Chain

```
POST /api/chat/send-chat-message { deep_research: true }
  -> process_message.py:869 (detect deep_research flag)
    -> run_deep_research_llm_loop()                          [dr_loop.py:188]
      -> Phase 1: run_llm_step() with clarification prompt   [dr_loop.py:269]
      -> Phase 2: run_llm_step_pkt_generator() for plan      [dr_loop.py:330]
      -> Phase 3: orchestrator loop                           [dr_loop.py:426]
        -> run_llm_step() for orchestrator decisions          [dr_loop.py:502]
        -> run_research_agent_calls()                         [research_agent.py:644]
          -> run_research_agent_call() x N (parallel)         [research_agent.py:205]
            -> run_llm_step() per research cycle              [research_agent.py:343]
            -> run_tool_calls() for real tools                [research_agent.py:445]
            -> generate_intermediate_report()                 [research_agent.py:86]
        -> collapse_citations()                               [research_agent.py:698]
      -> Phase 4: generate_final_report()                     [dr_loop.py:101]
        -> run_llm_step() for final answer                    [dr_loop.py:153]
```
