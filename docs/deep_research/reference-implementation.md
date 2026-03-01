# Deep Research: Reference Implementation Analysis

A conceptual analysis of the Onyx deep research system's design patterns, structural decisions, and trade-offs. Intended as a reference for building or improving deep research systems, regardless of domain.

---

## 1. Multi-Phase Pipeline

The system decomposes research into four sequential phases with distinct responsibilities. Each phase produces a well-defined artifact that feeds the next.

### Phase Sequence

```
Clarification -> Plan -> Execution -> Synthesis
```

### Why Four Phases (Not Fewer)

**Clarification as a gate.** Separating clarification from planning prevents the planner from making assumptions about ambiguous queries. The clarification agent is instructed to *never answer the query* -- it either asks questions or signals readiness. This hard separation prevents a common failure mode where the model starts "helping" prematurely.

The clarification phase uses a clever signaling mechanism: a no-parameter tool (`generate_plan`) that the LLM calls when it believes the query is clear. If the LLM responds with text instead of calling this tool, that text is treated as clarification questions. This avoids parsing LLM output to determine intent -- the tool call IS the signal.

**Plan as a contract.** The research plan serves as a shared reference between the orchestrator and the final report generator. The orchestrator uses it to decide what to research; the report generator uses it to structure the answer. Without an explicit plan, the orchestrator tends to drift or fixate on subtopics.

The plan is deliberately capped at 5-6 steps. This is a prompt engineering decision to prevent over-decomposition, which leads to shallow, scattered research.

**Execution separated from synthesis.** The system never asks the model to research and synthesize simultaneously. Research agents produce fact-dense, unstructured intermediate reports ("no title, no sections, no conclusions"). The final report generator then operates on this raw material with a different prompt optimized for structure, readability, and comprehensiveness. This separation prevents the common failure mode where a model prematurely commits to a narrative structure before it has all the facts.

### Phase Communication

Phases communicate through minimal interfaces:

| From | To | What passes through |
|------|----|-------------------|
| Clarification | Plan | Nothing (implicit: query was clear enough) |
| Plan | Execution | Plan text (string) |
| Execution | Synthesis | Chat history containing intermediate reports + citation mapping |

Each boundary is a compression point. The plan compresses understanding of the query into steps. Intermediate reports compress raw tool outputs into findings. The final report compresses everything into a user-facing answer.

---

## 2. Hierarchical Agent Model

### Two-Level Hierarchy

```
Orchestrator (strategic)
    |
    +-- Research Agent 1 (tactical)
    +-- Research Agent 2 (tactical)
    +-- Research Agent 3 (tactical)
```

The orchestrator operates at the **strategic level**: what topics to research, whether enough information has been gathered, when to stop. It never touches tools directly.

Research agents operate at the **tactical level**: what queries to run, which pages to open, how to interpret results. They never see the big picture.

### Why Not Flat?

A single agent doing everything (planning + searching + synthesizing) degrades badly on complex queries because:

1. **Context pollution.** Raw search results and page contents fill the context window, pushing the original query and research direction out of view.
2. **Mode confusion.** The model oscillates between "researcher" and "writer" modes, often producing half-baked reports mid-research.
3. **No parallelism.** A single agent is sequential by nature.

The hierarchy solves these by giving each level a clean, focused context.

### The Isolation Trade-off

Research agents are **fully isolated** from each other and from the orchestrator's context. Each agent receives only a task string and has no knowledge of:
- The original user query
- The research plan
- What other agents have found
- What the orchestrator is thinking

This is a deliberate design choice with clear trade-offs:

**Benefits:**
- Clean context windows (no cross-contamination)
- Parallelizable (no shared mutable state beyond citation bookkeeping)
- Predictable behavior (same task string = similar research)

**Costs:**
- Redundant work across agents on related topics
- No ability to "continue" a prior agent's research
- The orchestrator must front-load all context into the task string, which the LLM may do poorly

### The Continuation Gap

This is the most significant structural limitation. When the orchestrator receives an insufficient result from an agent and wants to dig deeper, it must dispatch an entirely new agent with a fresh context. The new agent:

- Cannot see what was already searched
- Cannot see what pages were already read
- Cannot see what was already found
- Will likely repeat some of the same work

The system relies on the orchestrator LLM to formulate a sufficiently different task to avoid redundancy, but provides no structural mechanism to enforce this. Possible mitigations not currently implemented:

- **Append prior findings to the task string.** Simple but bloats the task parameter.
- **Pass a "negative context" of searches to avoid.** Requires the agent to understand and respect exclusions.
- **Stateful agents with resumable sessions.** Most complex but most powerful.
- **A shared knowledge base tool** that agents can read from and write to.

---

## 3. Control Flow via Mock Tools

### The Pattern

Instead of building explicit state machines, the system uses LLM tool calling as a control flow mechanism. "Mock tools" are tool definitions presented to the LLM that are not backed by real implementations -- the system intercepts the tool call and routes execution accordingly.

```
LLM decides to call "generate_report"
    -> System intercepts this
    -> System runs report generation logic
    -> Report text is injected as tool response
```

### Mock Tool Inventory

| Tool | Signal Meaning | Called By |
|------|---------------|-----------|
| `generate_plan` | "Query is clear, proceed" | Clarification LLM |
| `research_agent` | "Research this topic" | Orchestrator |
| `generate_report` | "I'm done, synthesize" | Orchestrator, Research Agent |
| `think_tool` | "I need to reason" | Orchestrator, Research Agent |

### Why Mock Tools Instead of Structured Output

1. **Natural decision points.** The LLM decides when it has enough information by calling `generate_report`, rather than being asked "do you have enough?" in a structured output schema. This produces better calibration.
2. **Parallel dispatch for free.** The LLM can call `research_agent` multiple times in one turn, and the system interprets these as parallel dispatches. No special prompting for parallelism needed.
3. **Unified interface.** Mock tools and real tools share the same calling convention. The LLM doesn't distinguish between them, simplifying the prompt.
4. **Type-safe arguments.** The `research_agent` tool's `task` parameter has a schema, which constrains the LLM's output format naturally.

### The Think Tool: Simulated Reasoning

For non-reasoning models, the system provides a `think_tool` that simulates chain-of-thought reasoning. The LLM calls `think_tool(reasoning="I notice that...")`, and the system:

1. Strips the JSON wrapper from the arguments
2. Converts the content into reasoning display tokens for the UI
3. Injects a minimal acknowledgment ("Acknowledged, please continue.") as the tool response
4. Continues the loop

This achieves two things:
- Forces the model to reason between actions (the prompt makes `think_tool` mandatory between research cycles)
- Makes reasoning visible in the UI alongside reasoning-model output

For reasoning models, the `think_tool` is omitted entirely -- the model reasons natively, and the system detects reasoning tokens from the model's output.

The duality (think_tool for standard models, native reasoning for reasoning models) also drives structural differences:
- Standard models get 8 orchestrator cycles (because thinking takes a cycle)
- Reasoning models get 4 cycles (thinking is folded into each cycle)

---

## 4. Parallel Execution Model

### Dispatch Pattern

The orchestrator can call `research_agent` up to 3 times in a single LLM turn. These are executed in parallel threads.

```
Orchestrator turn N:
    research_agent(task="Topic A")  -> Thread 1
    research_agent(task="Topic B")  -> Thread 2
    research_agent(task="Topic C")  -> Thread 3
                                          |
                              All complete |
                                          v
                                    Merge results
                                          |
                                          v
                              Orchestrator turn N+1
```

### Parallelism Constraints

- **Max 3 agents per cycle** -- enforced by prompt, not code. A soft limit that could be violated by the LLM.
- **Max 1 tool call per agent turn** -- enforced by code. Within a research agent, tool calls of the same type are batched, but different tool types cannot execute in the same turn due to the placement system's inability to differentiate parallel sub-tool calls.
- **Shared state container** -- agents share a mutable `state_container` across threads. This is safe for additive operations (adding tool calls, adding search docs) but could cause issues with non-idempotent operations. Currently only used for writes plus one read (URL dedup map).

### Post-Parallel Merging

After parallel agents complete, their results must be reconciled:

1. **Citation renumbering.** Each agent independently numbers citations from `[1]`. After completion, `collapse_citations()` renumbers them to create a globally consistent scheme.
2. **Report concatenation.** Intermediate reports are appended to the orchestrator's chat history as separate tool responses.
3. **Failure handling.** If an agent returns `None` (failure/timeout), it's skipped. The orchestrator's next cycle sees no result for that task and may retry or move on.

---

## 5. Citation Architecture

### The KEEP_MARKERS Strategy

The system uses a two-pass citation approach:

**Pass 1 (During Research):** Citations are tracked but markers are preserved as-is. Each research agent numbers citations independently starting from `[1]`. The citation processor records which document each number refers to but doesn't modify the text.

**Pass 2 (After Research):** `collapse_citations()` renumbers citations to create a global, non-conflicting scheme across all agents and cycles.

### Why Not Renumber During Research?

If citations were renumbered in real-time, streaming intermediate reports to the UI would show unstable citation numbers (a `[3]` could become `[7]` mid-stream). KEEP_MARKERS ensures that what's streamed is what's stored, and renumbering happens only in the final merged history.

### Citation Flow

```
Agent 1: [1]=DocA, [2]=DocB    Agent 2: [1]=DocC, [2]=DocD
    |                               |
    v                               v
Intermediate Report 1:         Intermediate Report 2:
"...found X [1]..."            "...found Y [1]..."
    |                               |
    +--- collapse_citations() ------+
    |
    v
Merged history:
Report 1: "...found X [1]..."  (unchanged)
Report 2: "...found Y [3]..."  (renumbered)
Mapping: {1:DocA, 2:DocB, 3:DocC, 4:DocD}
    |
    v
Final report LLM sees the merged history
and produces: "...X [1]...Y [3]..."
```

### What Passes to the Final Report

Only cited documents are passed to the final report generator, not all search results. This is a context management decision -- passing every search result would bloat the context. The trade-off is that the final report cannot cite documents that weren't explicitly cited in intermediate reports, even if they appeared in search results.

---

## 6. Timeout Cascade

The system implements a multi-level timeout strategy that degrades gracefully rather than failing hard.

### Timeout Hierarchy

```
Level 0: Research Agent Force Report    12 minutes
Level 1: Research Agent Hard Timeout    30 minutes
Level 2: Orchestrator Force Report      30 minutes
```

### Cascade Behavior

**Level 0 -- Agent force report (12 min).** If a research agent has been running for 12 minutes without calling `generate_report`, the system breaks the agent's research loop and forces intermediate report generation from whatever has been gathered so far. The agent doesn't fail -- it just stops researching and summarizes.

**Level 1 -- Agent hard timeout (30 min).** If the entire agent execution (including report generation) exceeds 30 minutes, the thread-level timeout fires. A callback returns a stub result with a timeout message. The orchestrator sees this as a low-quality result and may dispatch another agent or proceed to the final report.

**Level 2 -- Orchestrator force report (30 min).** If the overall deep research session exceeds 30 minutes (measured from the start of the orchestration loop), the system skips the LLM call entirely and jumps to `generate_final_report()`. This ensures the user always gets an answer.

### Important: These Are Not Cumulative

The total runtime can exceed any single timeout because:
- A research cycle starting at minute 29 can run for up to 30 more minutes
- The final report itself has a 5-minute timeout
- Multiple orchestrator cycles can each trigger their own research agents

Worst case: ~65 minutes (29 min orchestration + 30 min agent + 5 min report + overhead). This is acknowledged in the codebase but not explicitly bounded.

### Design Principle

Each timeout triggers a **graceful degradation** rather than a failure:
- Agent force report: partial results summarized
- Agent hard timeout: timeout message returned as result
- Orchestrator force report: final report from whatever was gathered

The user always gets something, even if research was incomplete.

---

## 7. Prompt Engineering Patterns

### Pattern: Tool-Only Output

Both the orchestrator and research agent prompts contain:

> "NEVER output normal response tokens, you must only call tools."

Combined with `tool_choice=REQUIRED`, this creates a hard constraint: the LLM must call a tool on every turn. This prevents the model from "chatting" or producing unsolicited commentary between research steps.

The max_tokens limit is set low (1024 for orchestrator, 1000 for agent) as a safety net -- if the model somehow bypasses tool_choice and starts generating text, it's cut short quickly.

### Pattern: Context Injection Through Task Strings

Since research agents have no context beyond their task string, the orchestrator prompt explicitly warns:

> "CRITICAL - the research_agent only receives the task and has no additional context about the user's query, research plan, other research agents, or message history. You absolutely must provide all of the context needed to complete the task in the argument."

This is a key architectural constraint enforced purely through prompting. The system doesn't validate that the task string contains sufficient context -- it trusts the LLM.

### Pattern: Combating Model Caution

The plan generation prompt contains:

> "CRITICAL - You MUST only output the research plan... Do not worry about the feasibility of the plan or access to data or tools, a different deep research flow will handle that."

This combats a known failure mode where models refuse to plan research because they're uncertain about their ability to execute it. By explicitly decoupling planning from execution concerns, the system gets bolder, more comprehensive plans.

### Pattern: Report Style Differentiation

Intermediate reports and the final report have deliberately different style instructions:

- **Intermediate reports:** "No title, no sections, no conclusions. Facts only. No formatting." These are agent-to-agent communication -- optimized for information density, not readability.
- **Final report:** "Structure logically into relevant sections. Use different text styles and formatting." This is agent-to-user communication -- optimized for comprehension.

The final report prompt even warns:

> "Ignore the format styles of the intermediate research_agent reports, those are not end user facing and different from your task."

This prevents the final report from inheriting the flat, unformatted style of intermediate reports.

### Pattern: Progressive Encouragement

On the second orchestrator cycle, a reminder is injected:

> "Make sure all parts of the user question and the plan have been thoroughly explored before calling generate_report."

This combats early termination -- models tend to call `generate_report` too early, especially after a single successful research cycle. The reminder is only injected once (cycle 1) to avoid repetitive nagging.

### Pattern: Nudging Tool Sequences

After a web search, the system injects a reminder to open promising URLs:

> "Remember that after using web_search, you are encouraged to open some pages to get more context unless the query is completely answered by the snippets."

This addresses a common failure mode where the model treats search snippets as sufficient and never reads full pages. The nudge is conditional (only after web_search) and soft (says "encouraged", not "must").

---

## 8. Streaming Architecture

### Placement as UI Coordinates

Every packet carries a `Placement` that acts as a coordinate system for the UI:

```
placement:
    turn_index:     Which vertical block (sequential position)
    tab_index:      Which horizontal tab (parallel branch: 0, 1, 2)
    sub_turn_index: Nesting depth within a branch
```

This allows the frontend to render a complex, nested, parallel timeline without any knowledge of the research logic. The backend simply tags each packet with where it belongs.

### Packet Translation

The system reuses a generic LLM step infrastructure (`run_llm_step_pkt_generator`) for all phases. Deep-research-specific packet types are created by translating generic packets:

```
Generic:  AgentResponseStart  ->  DeepResearchPlanStart   (plan phase)
Generic:  AgentResponseDelta  ->  IntermediateReportDelta  (agent report phase)
Generic:  (unchanged)         ->  AgentResponseDelta       (final report)
```

This means the final report uses the SAME packet types as normal chat, so the frontend's standard message renderer handles it automatically. Only the plan and intermediate reports need custom renderers.

### Branching Signal

Before parallel agents start, a `TopLevelBranching(num_parallel_branches=N)` packet tells the frontend to prepare N parallel lanes. Without this signal, the frontend wouldn't know how to lay out incoming packets from different `tab_index` values.

---

## 9. Error Handling Philosophy

### Agent-Level: Isolate and Continue

Research agent failures are caught, logged, and the agent returns `None`. The orchestrator sees a missing result and can decide to:
- Retry with a different task
- Proceed with whatever other agents returned
- Generate the final report from partial data

No single agent failure kills the session.

### Orchestrator-Level: Degrade to Report

If the orchestrator LLM fails to produce tool calls (which shouldn't happen with `tool_choice=REQUIRED` but can in edge cases), the system falls through to `generate_final_report()` with whatever has been gathered so far. On cycle 0 (no data gathered), this raises an error. On later cycles, it produces a partial report.

### Token Loop Protection

Both the orchestrator and research agent set low `max_tokens` limits (1024 and 1000 respectively). This prevents a failure mode where the model enters an infinite loop of null or garbage tokens, which can happen with long contexts. The low limit means a degenerate response is cheap and the system can attempt recovery on the next cycle.

---

## 10. Known Limitations and Open Questions

### Agent Memory / Continuation
As discussed, there is no mechanism for agents to build on prior agents' work. Each dispatch is stateless. This leads to redundant searches and wasted cycles when iterating on a topic.

### Parallelism Limit is Prompt-Based
The "max 3 parallel agents" constraint is enforced by prompt instruction, not by code. The LLM could call `research_agent` 5 times in one turn and the system would execute all 5. This is fragile.

### No Search Query Deduplication
While URL fetching has deduplication (via `url_snippet_map`), search queries do not. Two agents researching related topics will likely submit similar queries and get overlapping results.

### Intermediate Report Compression
Intermediate reports are capped at 10,000 tokens, but the information loss from this compression is uncontrolled. Important details from raw search results may be dropped during summarization, and there's no mechanism to detect or recover from this.

### Single-Turn Tool Type Restriction
Within a research agent, only one tool type can execute per turn (e.g., can't do a search AND open a URL in the same turn). This is a limitation of the placement/UI system, not a research logic constraint, and forces extra cycles.

### No Evaluation Loop
There is no mechanism to evaluate the quality of intermediate reports or the final report. The system cannot detect when a report is shallow, contains hallucinations, or misses key aspects of the query. Quality is entirely dependent on the LLM's judgment and the prompt engineering.

### Total Runtime is Unbounded in Practice
While individual components have timeouts, the cascade of timeouts means total runtime is not strictly bounded. A more robust approach would impose a global wall-clock deadline.
