# Deep Research: Streaming and Packets

Deep research streams all output to the frontend as typed packets. This document describes the packet system and how packets are emitted and consumed.

## Packet Infrastructure

### Placement

**File**: `backend/onyx/server/query_and_chat/placement.py:4`

```python
class Placement(BaseModel):
    turn_index: int        # Which iterative block in the UI
    tab_index: int = 0     # For parallel tool calls (0-2 for research agents)
    sub_turn_index: int | None = None  # For nested tool calls within agents
```

The `Placement` object encodes the position of a packet in the UI timeline:
- `turn_index`: Sequential position in the overall timeline (plan=0, orchestrator cycles increment)
- `tab_index`: Parallel branch identifier (0, 1, 2 for up to 3 parallel research agents)
- `sub_turn_index`: Depth within a research agent's tool calls

### Packet

**File**: `backend/onyx/server/query_and_chat/streaming_models.py`

```python
class Packet(BaseModel):
    placement: Placement
    obj: PacketObj  # Discriminated union of all packet types
```

### Emitter

The `Emitter` class wraps a `Queue[Packet]` and provides `emit(packet)`. Packets are consumed by the API streaming response.

## Deep Research Packet Types

All defined in `backend/onyx/server/query_and_chat/streaming_models.py`.

### Plan Packets

| Packet | StreamingType Enum | Fields | Emitted By |
|--------|-------------------|--------|------------|
| `DeepResearchPlanStart` | `DEEP_RESEARCH_PLAN_START` | `type` | Plan generation (`dr_loop.py:349-353`) |
| `DeepResearchPlanDelta` | `DEEP_RESEARCH_PLAN_DELTA` | `type`, `content: str` | Plan generation (`dr_loop.py:355-361`) |

### Research Agent Packets

| Packet | StreamingType Enum | Fields | Emitted By |
|--------|-------------------|--------|------------|
| `ResearchAgentStart` | `RESEARCH_AGENT_START` | `type`, `research_task: str` | Agent start (`research_agent.py:241-246`) |
| `IntermediateReportStart` | `INTERMEDIATE_REPORT_START` | `type` | Report gen (`research_agent.py:150-155`) |
| `IntermediateReportDelta` | `INTERMEDIATE_REPORT_DELTA` | `type`, `content: str` | Report gen (`research_agent.py:156-161`) |
| `IntermediateReportCitedDocs` | `INTERMEDIATE_REPORT_CITED_DOCS` | `type`, `cited_docs: list[SearchDoc] \| None` | Report complete (`research_agent.py:175-184`) |

### Control Packets

| Packet | StreamingType Enum | Fields | Emitted By |
|--------|-------------------|--------|------------|
| `SectionEnd` | `SECTION_END` | `type` | Phase/section completion |
| `OverallStop` | `STOP` | `type` | Deep research complete (`dr_loop.py:765-770`) |
| `TopLevelBranching` | `TOP_LEVEL_BRANCHING` | `type`, `num_parallel_branches: int` | Before parallel agents (`dr_loop.py:662-673`) |
| `PacketException` | `ERROR` | `type`, `exception` | Error handling (`research_agent.py:611-616`) |

### Shared Packets (Also Used by Deep Research)

| Packet | Purpose |
|--------|---------|
| `AgentResponseStart` | Start of final report text |
| `AgentResponseDelta` | Final report text chunks |
| `ReasoningStart` | Start of reasoning content |
| `ReasoningDelta` | Reasoning content chunks |
| `ReasoningDone` | Reasoning complete |

## Packet Flow by Phase

### Phase 1: Clarification

```
If clarification needed:
  AgentResponseStart (turn_index=0)
  AgentResponseDelta (content chunks)
  OverallStop (turn_index=0)

If no clarification:
  (no deep-research-specific packets)
```

### Phase 2: Plan

```
DeepResearchPlanStart (turn_index=0)
DeepResearchPlanDelta (content chunks, multiple)
[optional: ReasoningStart, ReasoningDelta, ReasoningDone]
SectionEnd (turn_index=0 or 1)
```

### Phase 3: Research Execution

```
Per orchestrator cycle:
  [optional: ReasoningStart/Delta/Done for think_tool]

  TopLevelBranching (if >1 parallel agents)

  Per research agent (tab_index=0,1,2):
    ResearchAgentStart (research_task="...")

    Per tool call (sub_turn_index=0,1,...):
      [tool-specific packets: SearchToolStart, OpenUrlStart, etc.]

    IntermediateReportStart
    IntermediateReportDelta (content chunks)
    IntermediateReportCitedDocs (cited_docs=[...])
    SectionEnd
```

### Phase 4: Final Report

```
[optional: ReasoningStart/Delta/Done]
AgentResponseStart (turn_index=N)
AgentResponseDelta (content chunks)
```

### Termination

```
OverallStop (turn_index=final_turn_index)
```

## Packet Translation

Deep research reuses the generic `run_llm_step` / `run_llm_step_pkt_generator` infrastructure but translates the generic packets to deep-research-specific ones:

| Source Packet | Translated To | Context |
|--------------|---------------|---------|
| `AgentResponseStart` | `DeepResearchPlanStart` | Plan phase (`dr_loop.py:348-353`) |
| `AgentResponseDelta` | `DeepResearchPlanDelta` | Plan phase (`dr_loop.py:355-361`) |
| `AgentResponseStart` | `IntermediateReportStart` | Intermediate report (`research_agent.py:149-155`) |
| `AgentResponseDelta` | `IntermediateReportDelta` | Intermediate report (`research_agent.py:156-161`) |

The final report does **not** translate packets -- `AgentResponseStart`/`AgentResponseDelta` are emitted directly.

## Frontend Packet Consumption

### TypeScript Packet Types

**File**: `web/src/app/app/services/streamingModels.ts`

The TypeScript enum mirrors the Python `StreamingType`:

```typescript
enum PacketType {
    DEEP_RESEARCH_PLAN_START = "deep_research_plan_start",   // line 54
    DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta",   // line 55
    RESEARCH_AGENT_START = "research_agent_start",           // line 56
    INTERMEDIATE_REPORT_START = "intermediate_report_start", // line 57
    INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta", // line 58
    INTERMEDIATE_REPORT_CITED_DOCS = "intermediate_report_cited_docs", // line 59
}
```

### Renderer Selection

**File**: `web/src/app/app/message/messageComponents/renderMessageComponent.tsx:89-123`

Packets are routed to renderers by type detection:

```typescript
isDeepResearchPlanPacket(packet)  -> DeepResearchPlanRenderer
isResearchAgentPacket(packet)     -> ResearchAgentRenderer
```

Detection functions (`renderMessageComponent.tsx:89-104`):
- `isDeepResearchPlanPacket()`: checks for `DEEP_RESEARCH_PLAN_START` or `DEEP_RESEARCH_PLAN_DELTA`
- `isResearchAgentPacket()`: checks for `RESEARCH_AGENT_START`, `INTERMEDIATE_REPORT_START`, `INTERMEDIATE_REPORT_DELTA`, or `INTERMEDIATE_REPORT_CITED_DOCS`

### Packet Helpers

**File**: `web/src/app/app/message/messageComponents/timeline/packetHelpers.ts`

- `COLLAPSED_STREAMING_PACKET_TYPES` (line 4): Set of packet types that can be collapsed in the timeline, includes `RESEARCH_AGENT_START` and `DEEP_RESEARCH_PLAN_START`
- `isDeepResearchPlanPackets()` (line 107): Checks if a group of packets contains deep research plan data
- `stepHasCollapsedStreamingContent()` (line 38): Determines if a step has content that should show in collapsed mode
