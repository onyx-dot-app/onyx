# Deep Research: Citation System

Citations in deep research flow through multiple stages: tool responses -> research agent reports -> final report. This document traces how citations are tracked, preserved, renumbered, and merged.

## Citation Mode: KEEP_MARKERS

Each research agent creates its citation processor in `KEEP_MARKERS` mode:

```python
citation_processor = DynamicCitationProcessor(
    citation_mode=CitationMode.KEEP_MARKERS
)
```

**Reference**: `backend/onyx/tools/fake_tools/research_agent.py:228-230`

In `KEEP_MARKERS` mode, the processor:
- Preserves original citation markers like `[1]`, `[2]` in the text unchanged
- Tracks which documents were cited via an internal mapping (`get_seen_citations()`)
- Does NOT renumber citations during the agent's execution

This is important because each parallel research agent maintains its own independent citation numbering (starting from `[1]`), which must be reconciled later.

## Citation Flow

### Stage 1: Tool Responses -> Citation Processor

When a research agent calls a tool (search, web_search, open_url), the tool response contains documents with citation numbers.

`update_citation_processor_from_tool_response()` (`backend/onyx/chat/citation_utils.py`) updates the citation processor with all possible docs and citation numbers from the tool response.

**Reference**: `research_agent.py:546-549`

### Stage 2: Intermediate Report Generation

When the research agent generates its intermediate report:
- The LLM uses inline citations `[1]`, `[2]` etc. based on the documents it has seen
- These markers are preserved in the report text (KEEP_MARKERS mode)
- On completion, `citation_processor.get_seen_citations()` returns the mapping of citation numbers to `SearchDoc` objects

The intermediate report is returned as `ResearchAgentCallResult`:

```python
class ResearchAgentCallResult(BaseModel):
    intermediate_report: str          # Report text with [1], [2] markers
    citation_mapping: CitationMapping # {citation_num: SearchDoc}
```

**Reference**: `backend/onyx/deep_research/models.py:12-14`

### Stage 3: Citation Merging Across Agents

After parallel research agents complete, `run_research_agent_calls()` merges citations using `collapse_citations()`:

```python
updated_answer, updated_citation_mapping = collapse_citations(
    answer_text=result.intermediate_report,
    existing_citation_mapping=updated_citation_mapping,
    new_citation_mapping=result.citation_mapping,
)
```

**Reference**: `research_agent.py:698-702`

`collapse_citations()` (from `backend/onyx/chat/citation_utils.py`):
- Takes the report text and both the existing (accumulated) and new citation mappings
- Renumbers citations in the new report to avoid conflicts with existing ones
- Merges the mappings into a single combined mapping
- Returns the updated text and merged mapping

Example:
- Agent 1 report uses `[1]`, `[2]`, `[3]` (3 documents)
- Agent 2 report uses `[1]`, `[2]` (2 documents)
- After collapsing: Agent 2's `[1]` -> `[4]`, `[2]` -> `[5]`
- Combined mapping: `{1: doc_a, 2: doc_b, 3: doc_c, 4: doc_d, 5: doc_e}`

### Stage 4: Final Report

The accumulated `citation_mapping` from all cycles and agents is passed to `generate_final_report()`:

```python
citation_processor = DynamicCitationProcessor()
citation_processor.update_citation_mapping(citation_mapping)
```

**Reference**: `dr_loop.py:147-148`

The final report LLM is instructed to use inline citations `[1]`, `[2]`, etc. based on the citations included by the research agents. The `DynamicCitationProcessor` resolves these to the correct documents.

After generation, the mapping is saved for persistence:

```python
state_container.set_citation_mapping(citation_processor.citation_to_doc)
```

**Reference**: `dr_loop.py:171`

## Key Types

| Type | File | Description |
|------|------|-------------|
| `CitationMapping` | `backend/onyx/chat/citation_processor.py` | Type alias: `dict[int, SearchDoc]` -- maps citation number to document |
| `DynamicCitationProcessor` | `backend/onyx/chat/citation_processor.py` | Main citation processing class |
| `CitationMode` | `backend/onyx/chat/citation_processor.py` | Enum: `KEEP_MARKERS`, `REPLACE`, etc. |

## Key Functions

| Function | File | Purpose |
|----------|------|---------|
| `collapse_citations()` | `backend/onyx/chat/citation_utils.py` | Renumber citations and merge mappings |
| `update_citation_processor_from_tool_response()` | `backend/onyx/chat/citation_utils.py` | Update processor from tool response |
| `DynamicCitationProcessor.get_seen_citations()` | `backend/onyx/chat/citation_processor.py` | Get mapping of seen citation numbers to docs |
| `DynamicCitationProcessor.update_citation_mapping()` | `backend/onyx/chat/citation_processor.py` | Add citations from an existing mapping |
| `DynamicCitationProcessor.get_next_citation_number()` | `backend/onyx/chat/citation_processor.py` | Get the next available citation number |

## Frontend Citation Display

The `IntermediateReportCitedDocs` packet carries the final cited documents for each research agent to the frontend:

```python
emitter.emit(Packet(
    placement=placement,
    obj=IntermediateReportCitedDocs(
        cited_docs=list(citation_processor.get_seen_citations().values())
    ),
))
```

**Reference**: `research_agent.py:175-184`

The frontend's `ResearchAgentRenderer` processes this packet to display cited sources alongside the intermediate report.
