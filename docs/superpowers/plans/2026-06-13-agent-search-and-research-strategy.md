# 中文 Agent 搜索与研究能力层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of the shared Chinese Agent search and research capability layer for normal chat and deep research.

**Architecture:** Add a reusable prompt playbook module under `backend/onyx/prompts/`, wire it into existing chat tool guidance and deep research prompts, and add a Chinese benchmark dataset for manual and future automated evaluation. This keeps `llm_loop` and `dr_loop` intact while making search intent, query planning, source routing, evidence evaluation, and Chinese report shape explicit.

**Tech Stack:** Python 3.13, FastAPI backend prompt modules, Pydantic benchmark models, pytest unit tests.

---

## Issues to Address

- Ordinary chat currently relies on model discretion and generic tool guidance to decide when and how to search.
- Deep research already has an orchestrator chain, but its planner, research agent, and report prompts are not explicitly tuned for Chinese information seeking.
- Search method is duplicated implicitly across chat prompts and deep research prompts instead of sharing one vocabulary.
- There is no small Chinese benchmark set that can catch prompt regressions for search behavior, source choice, and report quality.

## Important Notes

- Do not rewrite `backend/onyx/chat/llm_loop.py` or `backend/onyx/deep_research/dr_loop.py` in Phase 1.
- Do not introduce DB tables or a new runtime planner in Phase 1.
- Keep ordinary chat guidance short enough to avoid bloating every prompt.
- Deep research prompts may be more explicit because that mode already spends more tokens.
- All prompt constants must avoid unescaped `{` / `}` because some target strings are later formatted with `.format(...)`.
- When adding tests, prefer unit tests that validate prompt assembly and benchmark shape. Live LLM quality checks belong to manual evaluation or later external dependency tests.

## File Structure

- Create `backend/onyx/prompts/search_strategy.py`
  - Owns shared prompt constants for chat search strategy, query portfolios, source routing, open URL evidence reading, deep research planning, research agent evidence capture, and final Chinese report structure.
- Modify `backend/onyx/prompts/tool_prompts.py`
  - Imports the shared chat/search constants and appends them to existing tool guidance.
- Modify `backend/onyx/prompts/deep_research/orchestration_layer.py`
  - Imports shared deep research constants and appends them to planner, orchestrator, and final report prompts.
- Modify `backend/onyx/prompts/deep_research/dr_tool_prompts.py`
  - Reuses query portfolio and evidence-reading guidance for deep research tool descriptions.
- Modify `backend/onyx/prompts/deep_research/research_agent.py`
  - Adds explicit source routing, query portfolio, evidence evaluation, and report preservation rules for research sub-agents.
- Create `backend/onyx/evals/glomi_search_research_benchmark.py`
  - Defines 20 Chinese benchmark cases spanning chat-lite and deep-research profiles.
- Create tests:
  - `backend/tests/unit/onyx/prompts/test_search_strategy.py`
  - `backend/tests/unit/onyx/prompts/test_tool_prompts.py`
  - `backend/tests/unit/onyx/prompts/deep_research/test_orchestration_layer.py`
  - `backend/tests/unit/onyx/prompts/deep_research/test_research_agent_prompts.py`
  - `backend/tests/unit/onyx/evals/test_glomi_search_research_benchmark.py`
- Modify `summary.md`
  - Record the implementation and any prompt/eval observations.

## Implementation Strategy

Implement Phase 1 as prompt and evaluation infrastructure only. First create the shared playbook constants and tests, then wire ordinary chat prompts, then wire deep research prompts, then add the benchmark set. Keep each task independently testable and commit after each passing task.

## Tests

- Unit tests for shared prompt constants and formatting safety.
- Unit tests for ordinary tool guidance containing the new search strategy markers.
- Unit tests for deep research prompt constants containing planning, source routing, evidence, and Chinese report markers.
- Unit tests for benchmark dataset size, profile coverage, category coverage, and expected tool assertions.
- Manual follow-up after implementation: run 3 chat-lite and 3 deep-research benchmark prompts against the configured default model and record results in `summary.md`.

---

### Task 1: Add Shared Search Strategy Playbook

**Files:**
- Create: `backend/onyx/prompts/search_strategy.py`
- Create: `backend/tests/unit/onyx/prompts/test_search_strategy.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/onyx/prompts/test_search_strategy.py`:

```python
from onyx.prompts.search_strategy import CHAT_SEARCH_STRATEGY_GUIDANCE
from onyx.prompts.search_strategy import DEEP_RESEARCH_FINAL_REPORT_GUIDANCE
from onyx.prompts.search_strategy import DEEP_RESEARCH_PLAN_GUIDANCE
from onyx.prompts.search_strategy import EVIDENCE_EVALUATION_GUIDANCE
from onyx.prompts.search_strategy import OPEN_URL_EVIDENCE_GUIDANCE
from onyx.prompts.search_strategy import QUERY_PORTFOLIO_GUIDANCE
from onyx.prompts.search_strategy import RESEARCH_AGENT_EVIDENCE_GUIDANCE
from onyx.prompts.search_strategy import SOURCE_ROUTING_GUIDANCE


def test_chat_search_strategy_has_required_decision_points() -> None:
    assert "Search intent" in CHAT_SEARCH_STRATEGY_GUIDANCE
    assert "Freshness" in CHAT_SEARCH_STRATEGY_GUIDANCE
    assert "Do not search" in CHAT_SEARCH_STRATEGY_GUIDANCE
    assert "中文" in CHAT_SEARCH_STRATEGY_GUIDANCE


def test_query_portfolio_guidance_mentions_bilingual_and_source_queries() -> None:
    assert "query portfolio" in QUERY_PORTFOLIO_GUIDANCE
    assert "Chinese" in QUERY_PORTFOLIO_GUIDANCE
    assert "English" in QUERY_PORTFOLIO_GUIDANCE
    assert "site:" in QUERY_PORTFOLIO_GUIDANCE


def test_source_and_evidence_guidance_cover_authority_and_conflicts() -> None:
    combined = SOURCE_ROUTING_GUIDANCE + EVIDENCE_EVALUATION_GUIDANCE
    assert "official" in combined.lower()
    assert "primary" in combined.lower()
    assert "conflict" in combined.lower()
    assert "freshness" in combined.lower()


def test_open_url_guidance_requires_reading_promising_pages() -> None:
    assert "open_url" in OPEN_URL_EVIDENCE_GUIDANCE
    assert "snippets" in OPEN_URL_EVIDENCE_GUIDANCE
    assert "reliable" in OPEN_URL_EVIDENCE_GUIDANCE


def test_deep_research_guidance_contains_chinese_report_expectations() -> None:
    combined = (
        DEEP_RESEARCH_PLAN_GUIDANCE
        + RESEARCH_AGENT_EVIDENCE_GUIDANCE
        + DEEP_RESEARCH_FINAL_REPORT_GUIDANCE
    )
    assert "information gaps" in combined
    assert "Evidence Pack" in combined
    assert "摘要" in combined
    assert "关键结论" in combined
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/test_search_strategy.py
```

Expected: fail with `ModuleNotFoundError: No module named 'onyx.prompts.search_strategy'`.

- [ ] **Step 3: Create the shared playbook module**

Create `backend/onyx/prompts/search_strategy.py`:

```python
# ruff: noqa: E501 start
"""Shared search and evidence prompt guidance for Glomi AI.

These constants make the search method reusable across ordinary chat and deep
research without introducing a new runtime planner in Phase 1.
"""

CHAT_SEARCH_STRATEGY_GUIDANCE = """
## Search intent
Use search when the user asks about fresh, changing, high-stakes, disputed, source-sensitive, price, policy, company, product, technical-version, or citation-requiring information.
Do not search for stable explanations, pure writing, brainstorming, or when the user explicitly asks not to search.
For Chinese users, prefer Chinese search terms first when the topic is China-facing, but add English terms when the domain is global, technical, academic, or product-specific.
When search is useful, generate a small set of distinct queries instead of repeating the user's exact wording.
After searching, answer from evidence rather than memory. If evidence is weak, say what is uncertain.
""".lstrip()

QUERY_PORTFOLIO_GUIDANCE = """
## Query portfolio
Before using web_search, form a query portfolio instead of one generic query.
Include Chinese terms, English terms, official names, product names, abbreviations, time qualifiers, and source-targeted forms such as site:official-domain when supported.
Use negative or risk-oriented terms when the user asks for evaluation, such as failure, controversy, limits, pricing, complaints, risk, or benchmark.
Keep each query focused. Do not merge unrelated research directions into one query.
""".lstrip()

SOURCE_ROUTING_GUIDANCE = """
## Source routing
Prefer official and primary sources when they exist.
For policy questions, prioritize government, regulator, and legal text sources.
For company and product questions, prioritize official sites, pricing pages, announcements, filings, blogs, release notes, and docs.
For technical questions, prioritize official docs, GitHub, papers, release notes, issues, and standards.
For market questions, combine reports, filings, company materials, industry media, and data sources.
For consumer decisions, combine reviews, community feedback, pricing pages, and recent hands-on evaluations.
""".lstrip()

EVIDENCE_EVALUATION_GUIDANCE = """
## Evidence evaluation
Evaluate each useful source for authority, freshness, relevance, duplication, conflict with other sources, and whether it directly supports the answer.
If sources conflict, preserve the conflict instead of hiding it.
If reliable evidence is missing for a key claim, mark the gap clearly.
""".lstrip()

OPEN_URL_EVIDENCE_GUIDANCE = """
## Evidence reading with open_url
Use open_url after web_search to read the most reliable and relevant pages. Do not rely only on snippets when the answer needs accuracy, citations, or nuanced comparison.
Open official, primary, recent, and high-signal pages before commentary pages.
Avoid opening many near-duplicate pages. Prefer pages that can add new evidence.
""".lstrip()

DEEP_RESEARCH_PLAN_GUIDANCE = """
## Deep research planning
Build the plan around information gaps, not generic steps.
Identify the decision the user is trying to make, the key hypotheses to verify, the time range, the source types needed, and any places where Chinese plus English searching may both be required.
Each plan item should be independently researchable and should include enough context for a downstream research agent.
""".lstrip()

DEEP_RESEARCH_ORCHESTRATOR_GUIDANCE = """
## Deep research orchestration
Assign research_agent tasks by independent evidence dimensions when possible, such as market, policy, company, technical, user feedback, risk, or counter-evidence.
Run independent dimensions in parallel, but use serial follow-up when the next query depends on what a previous source revealed.
After each research cycle, check which information gaps remain, whether sources conflict, and whether the evidence is strong enough to generate the final report.
""".lstrip()

RESEARCH_AGENT_EVIDENCE_GUIDANCE = """
## Research agent evidence work
Start by forming a query portfolio for the assigned task.
Prefer primary and official sources, then use secondary sources to add context, criticism, or independent confirmation.
After searches, open promising pages and preserve exact facts with source context.
Return an Evidence Pack: key facts, source titles or URLs, source type, freshness, confidence, conflicts, and remaining gaps.
""".lstrip()

DEEP_RESEARCH_FINAL_REPORT_GUIDANCE = """
## Chinese final report shape
Write the final report in natural Chinese unless the user asks otherwise.
Use this structure when it fits the task: 摘要, 关键结论, 证据与分析, 分歧与不确定性, 风险 / 机会 / 建议, 引用.
Lead with conclusions. Use inline citations for claims that come from gathered sources.
Mention evidence gaps and conflicts instead of overstating certainty.
""".lstrip()
# ruff: noqa: E501 end
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/test_search_strategy.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/prompts/search_strategy.py backend/tests/unit/onyx/prompts/test_search_strategy.py
git commit -m "feat: add shared agent search strategy prompts"
```

---

### Task 2: Wire Search Strategy Into Ordinary Chat Tool Guidance

**Files:**
- Modify: `backend/onyx/prompts/tool_prompts.py`
- Create: `backend/tests/unit/onyx/prompts/test_tool_prompts.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/onyx/prompts/test_tool_prompts.py`:

```python
from onyx.prompts.tool_prompts import OPEN_URLS_GUIDANCE
from onyx.prompts.tool_prompts import TOOL_DESCRIPTION_SEARCH_GUIDANCE
from onyx.prompts.tool_prompts import WEB_SEARCH_GUIDANCE


def test_general_search_guidance_contains_search_intent_rules() -> None:
    assert "Search intent" in TOOL_DESCRIPTION_SEARCH_GUIDANCE
    assert "Do not search" in TOOL_DESCRIPTION_SEARCH_GUIDANCE
    assert "中文" in TOOL_DESCRIPTION_SEARCH_GUIDANCE


def test_web_search_guidance_contains_query_portfolio_and_source_routing() -> None:
    rendered = WEB_SEARCH_GUIDANCE.format(site_colon_disabled="")
    assert "query portfolio" in rendered
    assert "Source routing" in rendered
    assert "Evidence evaluation" in rendered


def test_open_url_guidance_contains_evidence_reading_rules() -> None:
    assert "Evidence reading with open_url" in OPEN_URLS_GUIDANCE
    assert "Do not rely only on snippets" in OPEN_URLS_GUIDANCE
    assert "near-duplicate" in OPEN_URLS_GUIDANCE
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/test_tool_prompts.py
```

Expected: fail because existing tool prompt constants do not contain the new strategy markers.

- [ ] **Step 3: Import shared guidance constants**

Modify the top of `backend/onyx/prompts/tool_prompts.py` after the ruff comments:

```python
from onyx.prompts.search_strategy import CHAT_SEARCH_STRATEGY_GUIDANCE
from onyx.prompts.search_strategy import EVIDENCE_EVALUATION_GUIDANCE
from onyx.prompts.search_strategy import OPEN_URL_EVIDENCE_GUIDANCE
from onyx.prompts.search_strategy import QUERY_PORTFOLIO_GUIDANCE
from onyx.prompts.search_strategy import SOURCE_ROUTING_GUIDANCE
```

- [ ] **Step 4: Append the shared guidance to chat search constants**

Update the constants in `backend/onyx/prompts/tool_prompts.py` so they end with the shared guidance:

```python
TOOL_DESCRIPTION_SEARCH_GUIDANCE = (
    """
For questions that can be answered from existing knowledge, answer the user directly without using any tools. \
If you suspect your knowledge is outdated or for topics where things are rapidly changing, use search tools to get more context. \
For statements that may be describing or referring to a document, run a search for the document. \
In ambiguous cases, favor searching to get more context.

When using any search type tool, do not make any assumptions and stay as faithful to the user's query as possible. \
Between internal and web search (if both are available), think about if the user's query is likely better answered by team internal sources or online web pages. \
When searching for information, if the initial results cannot fully answer the user's query, try again with different tools or arguments. \
Do not repeat the same or very similar queries if it already has been run in the chat history.

If it is unclear which tool to use, consider using multiple in parallel to be efficient with time.
"""
    + "\n"
    + CHAT_SEARCH_STRATEGY_GUIDANCE
).lstrip()

WEB_SEARCH_GUIDANCE = (
    """
## web_search
Use the `web_search` tool to access up-to-date information from the web. Some examples of when to use `web_search` include:
- Freshness: when the answer might be enhanced by up-to-date information on a topic. Very important for topics that are changing or evolving.
- Accuracy: if the cost of outdated/inaccurate information is high.
- Niche Information: when detailed info is not widely known or understood (but is likely found on the internet).{site_colon_disabled}
"""
    + "\n"
    + QUERY_PORTFOLIO_GUIDANCE
    + "\n"
    + SOURCE_ROUTING_GUIDANCE
    + "\n"
    + EVIDENCE_EVALUATION_GUIDANCE
).lstrip()

OPEN_URLS_GUIDANCE = (
    """
## open_url
Use the `open_url` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your web searches or user specified URLs. \
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources. \
Do not open URLs that are image files like .png, .jpg, etc.
You should almost always use open_url after a web_search call. Use this tool when a user asks about a specific provided URL.
"""
    + "\n"
    + OPEN_URL_EVIDENCE_GUIDANCE
).lstrip()
```

- [ ] **Step 5: Run prompt tests**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/test_tool_prompts.py backend/tests/unit/onyx/prompts/test_prompt_utils.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/onyx/prompts/tool_prompts.py backend/tests/unit/onyx/prompts/test_tool_prompts.py
git commit -m "feat: tune chat search tool guidance"
```

---

### Task 3: Wire Strategy Into Deep Research Orchestration Prompts

**Files:**
- Modify: `backend/onyx/prompts/deep_research/orchestration_layer.py`
- Create: `backend/tests/unit/onyx/prompts/deep_research/test_orchestration_layer.py`

- [ ] **Step 1: Write the failing tests**

Create directory `backend/tests/unit/onyx/prompts/deep_research` if it does not exist.

Create `backend/tests/unit/onyx/prompts/deep_research/test_orchestration_layer.py`:

```python
from onyx.prompts.deep_research.orchestration_layer import FINAL_REPORT_PROMPT
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT_REASONING
from onyx.prompts.deep_research.orchestration_layer import RESEARCH_PLAN_PROMPT


def test_research_plan_prompt_contains_information_gap_planning() -> None:
    rendered = RESEARCH_PLAN_PROMPT.format(current_datetime="June 13, 2026")
    assert "information gaps" in rendered
    assert "source types" in rendered
    assert "Chinese plus English" in rendered


def test_orchestrator_prompts_contain_cycle_evaluation_rules() -> None:
    rendered = ORCHESTRATOR_PROMPT.format(
        current_datetime="June 13, 2026",
        current_cycle_count=1,
        max_cycles=3,
        research_plan="1. 调研市场\n2. 调研政策",
        internal_search_research_task_guidance="",
    )
    reasoning_rendered = ORCHESTRATOR_PROMPT_REASONING.format(
        current_datetime="June 13, 2026",
        current_cycle_count=1,
        max_cycles=3,
        research_plan="1. 调研市场\n2. 调研政策",
        internal_search_research_task_guidance="",
    )
    assert "Deep research orchestration" in rendered
    assert "information gaps remain" in rendered
    assert "Deep research orchestration" in reasoning_rendered


def test_final_report_prompt_contains_chinese_report_structure() -> None:
    rendered = FINAL_REPORT_PROMPT.format(current_datetime="June 13, 2026")
    assert "Chinese final report shape" in rendered
    assert "摘要" in rendered
    assert "关键结论" in rendered
    assert "inline citations" in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/deep_research/test_orchestration_layer.py
```

Expected: fail because orchestration prompts do not include the shared strategy sections.

- [ ] **Step 3: Import shared deep research guidance constants**

Modify imports in `backend/onyx/prompts/deep_research/orchestration_layer.py`:

```python
from onyx.prompts.search_strategy import DEEP_RESEARCH_FINAL_REPORT_GUIDANCE
from onyx.prompts.search_strategy import DEEP_RESEARCH_ORCHESTRATOR_GUIDANCE
from onyx.prompts.search_strategy import DEEP_RESEARCH_PLAN_GUIDANCE
```

- [ ] **Step 4: Append plan guidance to `RESEARCH_PLAN_PROMPT`**

Insert this paragraph before `Output only the numbered list...` in `RESEARCH_PLAN_PROMPT`:

```python
{deep_research_plan_guidance}
```

Then change the end of the constant to format in the guidance without requiring call-site changes:

```python
RESEARCH_PLAN_PROMPT = RESEARCH_PLAN_PROMPT.replace(
    "{deep_research_plan_guidance}",
    DEEP_RESEARCH_PLAN_GUIDANCE,
)
```

Place the replacement immediately after the `RESEARCH_PLAN_PROMPT` assignment.

- [ ] **Step 5: Append orchestration guidance to both orchestrator prompts**

In both `ORCHESTRATOR_PROMPT` and `ORCHESTRATOR_PROMPT_REASONING`, insert after the introductory paragraph and before `NEVER output normal response tokens`:

```python
{DEEP_RESEARCH_ORCHESTRATOR_GUIDANCE}
```

Because both constants are f-strings, use the imported constant directly inside the f-string:

```python
{DEEP_RESEARCH_ORCHESTRATOR_GUIDANCE}
```

- [ ] **Step 6: Append final report guidance**

In `FINAL_REPORT_PROMPT`, add this before `Provide inline citations...`:

```python
{deep_research_final_report_guidance}
```

Then place this replacement immediately after the `FINAL_REPORT_PROMPT` assignment:

```python
FINAL_REPORT_PROMPT = FINAL_REPORT_PROMPT.replace(
    "{deep_research_final_report_guidance}",
    DEEP_RESEARCH_FINAL_REPORT_GUIDANCE,
)
```

- [ ] **Step 7: Run orchestration tests**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/deep_research/test_orchestration_layer.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/onyx/prompts/deep_research/orchestration_layer.py backend/tests/unit/onyx/prompts/deep_research/test_orchestration_layer.py
git commit -m "feat: tune deep research orchestration prompts"
```

---

### Task 4: Wire Strategy Into Research Agent Tool Prompts

**Files:**
- Modify: `backend/onyx/prompts/deep_research/dr_tool_prompts.py`
- Modify: `backend/onyx/prompts/deep_research/research_agent.py`
- Create: `backend/tests/unit/onyx/prompts/deep_research/test_research_agent_prompts.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/onyx/prompts/deep_research/test_research_agent_prompts.py`:

```python
from onyx.prompts.deep_research.dr_tool_prompts import OPEN_URLS_TOOL_DESCRIPTION
from onyx.prompts.deep_research.dr_tool_prompts import WEB_SEARCH_TOOL_DESCRIPTION
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT_REASONING
from onyx.prompts.deep_research.research_agent import RESEARCH_REPORT_PROMPT


def test_deep_research_web_tool_description_contains_query_strategy() -> None:
    assert "query portfolio" in WEB_SEARCH_TOOL_DESCRIPTION
    assert "Chinese" in WEB_SEARCH_TOOL_DESCRIPTION
    assert "Source routing" in WEB_SEARCH_TOOL_DESCRIPTION


def test_deep_research_open_url_description_contains_evidence_reading() -> None:
    assert "Evidence reading with open_url" in OPEN_URLS_TOOL_DESCRIPTION
    assert "snippets" in OPEN_URLS_TOOL_DESCRIPTION


def test_research_agent_prompts_require_evidence_pack() -> None:
    rendered = RESEARCH_AGENT_PROMPT.format(
        available_tools="web_search, open_url",
        current_datetime="June 13, 2026",
        current_cycle_count=1,
        optional_internal_search_tool_description="",
        optional_web_search_tool_description=WEB_SEARCH_TOOL_DESCRIPTION,
        optional_open_url_tool_description=OPEN_URLS_TOOL_DESCRIPTION,
    )
    reasoning_rendered = RESEARCH_AGENT_PROMPT_REASONING.format(
        available_tools="web_search, open_url",
        current_datetime="June 13, 2026",
        current_cycle_count=1,
        optional_internal_search_tool_description="",
        optional_web_search_tool_description=WEB_SEARCH_TOOL_DESCRIPTION,
        optional_open_url_tool_description=OPEN_URLS_TOOL_DESCRIPTION,
    )
    assert "Research agent evidence work" in rendered
    assert "Evidence Pack" in rendered
    assert "Research agent evidence work" in reasoning_rendered


def test_research_report_prompt_preserves_conflicts_and_gaps() -> None:
    assert "conflicts" in RESEARCH_REPORT_PROMPT.lower()
    assert "remaining gaps" in RESEARCH_REPORT_PROMPT.lower()
    assert "source context" in RESEARCH_REPORT_PROMPT.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/deep_research/test_research_agent_prompts.py
```

Expected: fail because the deep research tool and research agent prompts do not contain the new strategy markers.

- [ ] **Step 3: Update deep research tool descriptions**

Modify `backend/onyx/prompts/deep_research/dr_tool_prompts.py` imports:

```python
from onyx.prompts.search_strategy import OPEN_URL_EVIDENCE_GUIDANCE
from onyx.prompts.search_strategy import QUERY_PORTFOLIO_GUIDANCE
from onyx.prompts.search_strategy import SOURCE_ROUTING_GUIDANCE
```

Update `WEB_SEARCH_TOOL_DESCRIPTION`:

```python
WEB_SEARCH_TOOL_DESCRIPTION = (
    """

## web_search
Use the `web_search` tool to get search results from the web. You should use this tool to get context for your research. These should be optimized for search engines like Google. \
Use concise and specific queries and avoid merging multiple queries into one. You can call web_search with multiple queries at once (3 max) but generally only do this when there is a clear opportunity for parallel searching. \
If you use multiple queries, ensure that the queries are related in topic but not similar such that the results would be redundant.
"""
    + "\n"
    + QUERY_PORTFOLIO_GUIDANCE
    + "\n"
    + SOURCE_ROUTING_GUIDANCE
)
```

Update both open URL descriptions:

```python
OPEN_URLS_TOOL_DESCRIPTION = (
    f"""

## open_urls
Use the `open_urls` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your searches. \
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources. \
You should almost always use open_urls after a web_search call and sometimes after reasoning with the {THINK_TOOL_NAME} tool.
"""
    + "\n"
    + OPEN_URL_EVIDENCE_GUIDANCE
)

OPEN_URLS_TOOL_DESCRIPTION_REASONING = (
    """

## open_urls
Use the `open_urls` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your searches. \
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources. \
You should almost always use open_urls after a web_search call.
"""
    + "\n"
    + OPEN_URL_EVIDENCE_GUIDANCE
)
```

- [ ] **Step 4: Update research agent prompts**

Modify imports in `backend/onyx/prompts/deep_research/research_agent.py`:

```python
from onyx.prompts.search_strategy import RESEARCH_AGENT_EVIDENCE_GUIDANCE
```

Add this after the first context/date paragraph in both `RESEARCH_AGENT_PROMPT` and `RESEARCH_AGENT_PROMPT_REASONING`:

```python
{RESEARCH_AGENT_EVIDENCE_GUIDANCE}
```

Add this paragraph near the end of `RESEARCH_REPORT_PROMPT`, before citation instructions:

```python
Preserve source context, confidence, conflicts, and remaining gaps from the research history. If a fact is useful but uncertain, keep it and label why it is uncertain rather than dropping it.
```

- [ ] **Step 5: Run research agent prompt tests**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/deep_research/test_research_agent_prompts.py
```

Expected: all tests pass.

- [ ] **Step 6: Run all prompt tests touched so far**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/test_search_strategy.py backend/tests/unit/onyx/prompts/test_tool_prompts.py backend/tests/unit/onyx/prompts/deep_research
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/onyx/prompts/deep_research/dr_tool_prompts.py backend/onyx/prompts/deep_research/research_agent.py backend/tests/unit/onyx/prompts/deep_research/test_research_agent_prompts.py
git commit -m "feat: tune deep research agent search prompts"
```

---

### Task 5: Add Chinese Search and Research Benchmark Dataset

**Files:**
- Create: `backend/onyx/evals/glomi_search_research_benchmark.py`
- Create: `backend/tests/unit/onyx/evals/test_glomi_search_research_benchmark.py`

- [ ] **Step 1: Write the failing tests**

Create directory `backend/tests/unit/onyx/evals` if it does not exist.

Create `backend/tests/unit/onyx/evals/test_glomi_search_research_benchmark.py`:

```python
from onyx.evals.glomi_search_research_benchmark import BENCHMARK_CASES
from onyx.evals.glomi_search_research_benchmark import BenchmarkProfile
from onyx.evals.glomi_search_research_benchmark import BenchmarkCategory


def test_benchmark_has_phase_one_size() -> None:
    assert len(BENCHMARK_CASES) >= 20


def test_benchmark_covers_chat_and_deep_profiles() -> None:
    profiles = {case.profile for case in BENCHMARK_CASES}
    assert BenchmarkProfile.CHAT_LITE in profiles
    assert BenchmarkProfile.DEEP_RESEARCH in profiles


def test_benchmark_covers_required_categories() -> None:
    categories = {case.category for case in BENCHMARK_CASES}
    assert BenchmarkCategory.FRESH_FACT in categories
    assert BenchmarkCategory.POLICY_RESEARCH in categories
    assert BenchmarkCategory.PRODUCT_COMPARISON in categories
    assert BenchmarkCategory.TECHNICAL_RESEARCH in categories
    assert BenchmarkCategory.MARKET_RESEARCH in categories
    assert BenchmarkCategory.FACT_CHECK in categories


def test_each_case_has_expected_behaviors_and_tools() -> None:
    for case in BENCHMARK_CASES:
        assert case.id
        assert case.prompt
        assert case.expected_behaviors
        assert case.expected_tools


def test_chinese_cases_are_not_english_only() -> None:
    chinese_count = sum(any("\u4e00" <= char <= "\u9fff" for char in case.prompt) for case in BENCHMARK_CASES)
    assert chinese_count == len(BENCHMARK_CASES)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q backend/tests/unit/onyx/evals/test_glomi_search_research_benchmark.py
```

Expected: fail with `ModuleNotFoundError: No module named 'onyx.evals.glomi_search_research_benchmark'`.

- [ ] **Step 3: Create benchmark module**

Create `backend/onyx/evals/glomi_search_research_benchmark.py`:

```python
from enum import StrEnum

from pydantic import BaseModel
from pydantic import Field


class BenchmarkProfile(StrEnum):
    CHAT_LITE = "chat_lite"
    DEEP_RESEARCH = "deep_research"


class BenchmarkCategory(StrEnum):
    FRESH_FACT = "fresh_fact"
    POLICY_RESEARCH = "policy_research"
    PRODUCT_COMPARISON = "product_comparison"
    TECHNICAL_RESEARCH = "technical_research"
    MARKET_RESEARCH = "market_research"
    CONSUMER_DECISION = "consumer_decision"
    FACT_CHECK = "fact_check"
    COMPANY_RESEARCH = "company_research"


class GlomiSearchBenchmarkCase(BaseModel):
    id: str
    profile: BenchmarkProfile
    category: BenchmarkCategory
    prompt: str
    expected_tools: list[str] = Field(default_factory=list)
    expected_behaviors: list[str] = Field(default_factory=list)


BENCHMARK_CASES: list[GlomiSearchBenchmarkCase] = [
    GlomiSearchBenchmarkCase(
        id="chat_fresh_ai_news",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.FRESH_FACT,
        prompt="最近一个月国内 AI 编程工具有什么重要变化？请给我简洁结论和来源。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["主动搜索", "打开高价值来源", "结论先行", "保留引用"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_policy_quick_check",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.POLICY_RESEARCH,
        prompt="现在中国对生成式 AI 服务备案有什么基本要求？请不要凭记忆回答。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["优先官方或监管来源", "说明适用范围", "标注不确定性"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_product_price",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.PRODUCT_COMPARISON,
        prompt="Cursor 和 Windsurf 现在个人版价格大概有什么区别？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["查询最新价格页", "对比维度清晰", "避免过期价格"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_technical_version",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.TECHNICAL_RESEARCH,
        prompt="Next.js 15 现在推荐的缓存写法跟 14 有什么变化？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["优先官方文档", "区分版本", "避免泛泛解释"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_company_fact",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.COMPANY_RESEARCH,
        prompt="月之暗面最近有没有发布新的 Kimi 模型或产品？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["搜索最新信息", "优先官方公告", "给出时间线"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_fact_check_claim",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.FACT_CHECK,
        prompt="有人说 Manus 已经完全开源了，这是真的吗？帮我核实。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["核实主张", "查官方与代码来源", "区分完全开源和部分开放"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_consumer_decision",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.CONSUMER_DECISION,
        prompt="如果我主要写中文长文，Kimi、豆包、通义千问现在怎么选？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["搜索近期产品状态", "结合中文写作场景", "给出选择建议"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_market_snapshot",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="中国 AI 搜索产品现在有哪些主要玩家？给我一个快速版。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["拆分玩家与定位", "使用近期来源", "输出简洁表格"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_github_release",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.TECHNICAL_RESEARCH,
        prompt="Playwright 最近几个版本有什么值得注意的更新？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["优先 release notes", "按版本总结", "避免旧知识"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_conflicting_sources",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.FACT_CHECK,
        prompt="网上说某 AI 产品月活已经超过 ChatGPT，这种说法怎么判断靠不靠谱？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["寻找原始数据来源", "说明口径差异", "指出证据不足"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_ai_coding_startup",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="请深度研究 2026 年 AI 编程工具还有没有创业机会，重点看中国市场。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["拆信息缺口", "中英双语搜索", "来源矩阵", "中文报告"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_china_ai_policy",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.POLICY_RESEARCH,
        prompt="请研究中国生成式 AI 应用上线前需要关注的备案、内容安全和合规要求。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["优先官方来源", "区分法规与解读", "列出风险与建议"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_ai_search_competition",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="请研究国内 AI 搜索和超级 Agent 产品格局，分析 Glomi AI 的切入机会。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["竞品分层", "产品定位", "机会与风险", "引用准确"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_model_provider_compare",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.PRODUCT_COMPARISON,
        prompt="请对比 Qwen、DeepSeek、Kimi、豆包在中文 Agent 产品中的适用性。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["比较模型能力", "搜索官方文档", "说明成本与工具调用风险"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_technical_rag_cn",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.TECHNICAL_RESEARCH,
        prompt="请研究中文 RAG 系统在 embedding、rerank、chunking 上的最佳实践。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["技术来源优先", "官方和论文结合", "给出工程建议"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_creator_tools",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="请研究中文自媒体创作者最可能为什么样的 AI Agent 工具付费。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["用户场景拆分", "消费决策来源", "机会排序"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_wechat_ecosystem",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.COMPANY_RESEARCH,
        prompt="请研究微信生态里适合 AI Agent 分发和获客的路径。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["来源覆盖微信规则", "案例研究", "风险提示"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_sandbox_deployment_cn",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.TECHNICAL_RESEARCH,
        prompt="请研究在国内云上部署代码沙箱和网页生成环境的技术方案与风险。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["技术方案对比", "安全风险", "云服务限制", "引用来源"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_pricing_strategy",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="请研究中国 C 端 AI 工具的订阅、积分和按量付费模式，给 Glomi AI 定价建议。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["价格来源", "竞品对比", "用户心理", "建议分层"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_fact_check_benchmark",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.FACT_CHECK,
        prompt="请核查“AI Agent 产品留存普遍很差”这个判断是否成立，并找证据支持或反驳。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["寻找数据来源", "保留冲突", "说明证据缺口"],
    ),
]
```

- [ ] **Step 4: Run benchmark tests**

Run:

```bash
pytest -q backend/tests/unit/onyx/evals/test_glomi_search_research_benchmark.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/evals/glomi_search_research_benchmark.py backend/tests/unit/onyx/evals/test_glomi_search_research_benchmark.py
git commit -m "test: add Chinese search research benchmark"
```

---

### Task 6: Final Verification and Documentation Record

**Files:**
- Modify: `summary.md`

- [ ] **Step 1: Run all focused unit tests**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts/test_search_strategy.py backend/tests/unit/onyx/prompts/test_tool_prompts.py backend/tests/unit/onyx/prompts/deep_research backend/tests/unit/onyx/evals/test_glomi_search_research_benchmark.py
```

Expected: all tests pass.

- [ ] **Step 2: Run a broader prompt/eval unit test slice**

Run:

```bash
pytest -q backend/tests/unit/onyx/prompts backend/tests/unit/onyx/evals
```

Expected: all tests pass. If `backend/tests/unit/onyx/evals` contains only the new benchmark test, this command still validates the package path.

- [ ] **Step 3: Record implementation in `summary.md`**

Append under `## 2026-06-13`:

```markdown
- 实现进展：落地中文 Agent 搜索与研究能力层 Phase 1，新增共享 search strategy prompt 常量，普通 chat tool guidance 与 deep research planner/orchestrator/research-agent/final-report prompts 统一引用同一套搜索方法论。
- 测试记录：新增 prompt 单测与中文 benchmark dataset 单测，验证 Search Intent、query portfolio、source routing、Evidence Pack、中文报告结构等关键标记不会被后续 prompt 改动删掉。
- 经验与坑：Phase 1 只改 prompt/playbook/benchmark，不改 `llm_loop` / `dr_loop` runtime；后续需要用真实 Qwen/DeepSeek/Kimi 跑 benchmark，再判断是否引入结构化 `SearchIntent` / `SearchPlan` / `EvidencePack`。
```

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff -- backend/onyx/prompts/search_strategy.py backend/onyx/prompts/tool_prompts.py backend/onyx/prompts/deep_research/orchestration_layer.py backend/onyx/prompts/deep_research/dr_tool_prompts.py backend/onyx/prompts/deep_research/research_agent.py backend/onyx/evals/glomi_search_research_benchmark.py backend/tests/unit/onyx/prompts backend/tests/unit/onyx/evals summary.md
```

Expected: diff only includes the prompt, benchmark, test, and summary changes from this plan.

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/prompts/search_strategy.py backend/onyx/prompts/tool_prompts.py backend/onyx/prompts/deep_research/orchestration_layer.py backend/onyx/prompts/deep_research/dr_tool_prompts.py backend/onyx/prompts/deep_research/research_agent.py backend/onyx/evals/glomi_search_research_benchmark.py backend/tests/unit/onyx/prompts backend/tests/unit/onyx/evals summary.md
git commit -m "feat: add Chinese agent search research strategy"
```

## Manual Evaluation After Implementation

After code and tests pass, run these six prompts manually through the app with the configured default model:

- Chat lite: “最近一个月国内 AI 编程工具有什么重要变化？请给我简洁结论和来源。”
- Chat lite: “现在中国对生成式 AI 服务备案有什么基本要求？请不要凭记忆回答。”
- Chat lite: “Cursor 和 Windsurf 现在个人版价格大概有什么区别？”
- Deep research: “请深度研究 2026 年 AI 编程工具还有没有创业机会，重点看中国市场。”
- Deep research: “请研究中国生成式 AI 应用上线前需要关注的备案、内容安全和合规要求。”
- Deep research: “请研究国内 AI 搜索和超级 Agent 产品格局，分析 Glomi AI 的切入机会。”

Record for each:

```markdown
- Prompt:
- Mode:
- Did it search:
- Did it open sources:
- Query quality:
- Source quality:
- Citation quality:
- Chinese answer/report quality:
- Main failure:
- Follow-up prompt change:
```

Add the manual evaluation notes to `summary.md` after the run.
