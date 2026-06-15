# Search Debug Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight, non-persistent Search Debug Drawer for web search tool calls.

**Architecture:** Backend emits a new `search_tool_debug_delta` streaming packet from `WebSearchTool` after provider execution or immediately before provider failures. Frontend treats that packet as part of the existing search tool packet group and renders a collapsed debug drawer only in the full Web Search timeline view.

**Tech Stack:** Python 3.13, Pydantic streaming packet models, FastAPI/Onyx tool runtime, Next.js/React/TypeScript, Jest, pytest.

---

## Files

- Modify: `backend/onyx/server/query_and_chat/streaming_models.py`
- Modify: `backend/onyx/tools/tool_implementations/web_search/web_search_tool.py`
- Modify: `backend/tests/unit/onyx/tools/tool_implementations/websearch/test_web_search_tool_run.py`
- Modify: `web/src/app/app/services/streamingModels.ts`
- Modify: `web/src/app/app/services/packetUtils.ts`
- Modify: `web/src/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils.ts`
- Modify: `web/src/app/app/message/messageComponents/timeline/renderers/search/WebSearchToolRenderer.tsx`
- Modify: `web/src/app/app/message/messageComponents/timeline/hooks/__tests__/testHelpers.ts`
- Modify: `web/src/app/app/message/messageComponents/timeline/hooks/packetProcessor.test.ts`
- Modify: `summary.md`
- Modify: `docs/GlomiAI.md`

## Task 1: Backend Debug Packet Model

- [ ] Write a backend unit test in `test_web_search_tool_run.py` that runs `WebSearchTool` against a batch provider and asserts the emitter receives `SearchToolDebugDelta` with provider, mode, channel, queries, duration, result count, and result URLs.
- [ ] Run the focused pytest test and confirm it fails because `SearchToolDebugDelta` does not exist or is not emitted.
- [ ] Add `SEARCH_TOOL_DEBUG_DELTA = "search_tool_debug_delta"` to `StreamingType`.
- [ ] Add `SearchToolDebugResult` and `SearchToolDebugDelta` Pydantic models.
- [ ] Add `SearchToolDebugDelta` to `PacketObj`.
- [ ] Update `WebSearchTool.__init__` to keep safe provider metadata: provider type, provider name, and non-sensitive channel.
- [ ] Emit `SearchToolDebugDelta` after successful provider execution.
- [ ] Run the focused pytest test and confirm it passes.

## Task 2: Backend Failure Debug

- [ ] Add a unit test for per-query provider partial failure and assert the debug packet includes `failed_queries`.
- [ ] Add a unit test for batch provider failure and assert the debug packet includes `error` before `ToolCallException`.
- [ ] Run the tests and confirm they fail.
- [ ] Add timing/error capture in `WebSearchTool.run()` around provider execution.
- [ ] Emit debug before raising batch failure and after per-query execution with partial failures.
- [ ] Run the focused pytest file and confirm it passes.

## Task 3: Frontend Packet Types and State

- [ ] Add `SEARCH_TOOL_DEBUG_DELTA` and `SearchToolDebugDelta` to `streamingModels.ts`, and include it in `SearchToolObj`.
- [ ] Add `SEARCH_TOOL_DEBUG_DELTA` to `isToolPacket()` and `isSearchToolPacket()`.
- [ ] Add a Jest test in `packetProcessor.test.ts` that a search group keeps the debug packet with the search tool packets.
- [ ] Extend `searchStateUtils.ts` with `SearchDebugState` and parse the latest debug packet into `SearchState.debug`.
- [ ] Add a Jest test for `constructCurrentSearchState()` parsing provider/mode/channel/queries/results/failures.
- [ ] Run focused Jest and confirm the tests fail before implementation, then pass after implementation.

## Task 4: Frontend Drawer Rendering

- [ ] Add a small `SearchDebugDrawer` component inside `WebSearchToolRenderer.tsx` or a co-located file if it grows beyond a few dozen lines.
- [ ] Render it only in FULL mode and only when `searchState.debug` exists.
- [ ] Use existing text/components and restrained utility styling consistent with timeline tools.
- [ ] Keep it collapsed by default via native `<details>` or the existing local collapsible pattern if available in this renderer area.
- [ ] Run focused Jest/typecheck.

## Task 5: Docs and Verification

- [ ] Update `summary.md` with implementation notes, pitfalls, and validation commands.
- [ ] Update `docs/GlomiAI.md` to mention Search Debug as a Phase A developer/admin aid.
- [ ] Run backend focused pytest:

```powershell
$env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\tools\tool_implementations\websearch\test_web_search_tool_run.py
```

- [ ] Run frontend focused Jest:

```powershell
cd web; npm test -- packetProcessor.test.ts
```

- [ ] Run frontend type check:

```powershell
cd web; npm run types:check
```
