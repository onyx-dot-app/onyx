# Medium And Deep Search Gateway Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mode=medium` and `mode=deep` in the local Glomi Search Gateway behave like bounded research-oriented retrieval passes by broadening queries and returning richer extracted snippets.

**Architecture:** Keep Onyx's `web_search` contract stable while extending the mode enum. Add deterministic query fan-out inside the local Gateway Tavily adapter, request Tavily raw content only for medium/deep searches, and cap normalized snippets by mode so the LLM gets stronger evidence without unbounded context growth.

**Tech Stack:** Python 3.13, Pydantic v2, httpx, pytest.

---

## Files

- Create `backend/onyx/search_gateway/query_planner.py` for medium/deep query fan-out.
- Modify `backend/onyx/search_gateway/tavily.py` to use query fan-out and medium/deep raw-content snippets.
- Modify `backend/tests/unit/onyx/search_gateway/test_tavily.py` to cover the new behavior.
- Create `backend/tests/unit/onyx/search_gateway/test_query_planner.py`.
- Modify `docs/superpowers/specs/2026-06-15-local-glomi-search-gateway-design.md`, `docs/GlomiAI.md`, and `summary.md`.

## Tasks

### Task 1: Query Fan-Out Tests

- [ ] Add unit tests that verify `lite` keeps original queries only.
- [ ] Add unit tests that verify `medium` expands a software/project query into a smaller official docs, GitHub, changelog, and comparison portfolio.
- [ ] Add unit tests that verify `deep` expands a software/project query into official docs, GitHub, changelog, issue/discussion, comparison, and limitation angles.
- [ ] Run the new tests and verify they fail because the planner module does not exist.

### Task 2: Query Planner

- [ ] Implement query normalization, dedupe, capped medium fan-out, and capped deep fan-out.
- [ ] Keep expansion deterministic and bounded to avoid surprise cost growth.
- [ ] Run query planner tests.

### Task 3: Tavily Medium/Deep Payload And Snippets

- [ ] Add failing Tavily adapter tests for `include_raw_content=true` in medium/deep mode and `false` in lite mode.
- [ ] Add failing Tavily adapter tests that medium/deep results prefer truncated `raw_content` over short search snippets when available.
- [ ] Implement minimal Tavily adapter changes.
- [ ] Run Tavily adapter tests.

### Task 4: Docs And Verification

- [ ] Update product/spec notes with the new deep-mode semantics and current limitations.
- [ ] Run focused Gateway tests.
- [ ] Run ruff on the changed Gateway modules/tests.
- [ ] Run `git diff --check`.
