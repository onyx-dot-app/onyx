# Pluggable Search Gateway Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local Glomi Search Gateway reusable across Tavily, Brave, domestic search engines, and future extract providers without changing Onyx's `web_search` contract.

**Architecture:** Keep planner, mode policy, channel routing, capability degradation, and result merge/dedupe in Gateway common service code. Provider-specific code lives behind small adapters that declare capabilities and translate unified search options into upstream requests.

**Tech Stack:** Python 3.13, dataclasses, Protocol, FastAPI, httpx, pytest.

---

## Files

- Create `backend/onyx/search_gateway/adapters.py` for adapter protocol, capabilities, and normalized options.
- Create `backend/onyx/search_gateway/service.py` for channel registry, mode policy, query planning, capability degradation, and result merge/dedupe.
- Modify `backend/onyx/search_gateway/tavily.py` so Tavily is a concrete adapter and the existing client class is a compatibility wrapper.
- Modify `backend/onyx/search_gateway/server.py` so it builds a `SearchGatewayService` with registered adapters instead of hardcoding `channel=tavily` in the route.
- Add `backend/tests/unit/onyx/search_gateway/test_service.py`.
- Update Gateway specs, `docs/GlomiAI.md`, and `summary.md`.

## Tasks

### Task 1: Service Contract Tests

- [x] Add tests for default channel routing through a fake adapter.
- [x] Add tests for medium/deep mode options being converted into normalized adapter options.
- [x] Add tests for capability degradation when an adapter does not support advanced search or raw content.
- [x] Add tests for URL dedupe across adapter calls.
- [x] Add tests for unknown channel rejection.

### Task 2: Common Gateway Service

- [x] Implement `SearchAdapterCapabilities` and `SearchAdapterOptions`.
- [x] Implement `SearchGatewayService` with adapter registry and default channel handling.
- [x] Move query planning and per-query max-results policy into the common service.
- [x] Keep result merge/dedupe in the common service.

### Task 3: Tavily Adapter Migration

- [x] Convert Tavily logic into `TavilySearchAdapter`.
- [x] Keep `TavilySearchClient.search(request)` as a wrapper around `SearchGatewayService` so existing tests and server callers remain compatible.
- [x] Keep Tavily-specific request payload and response normalization inside the adapter.

### Task 4: Server Wiring And Docs

- [x] Build the default Gateway service with the Tavily adapter in `server.py`.
- [x] Let the common service reject unsupported channels.
- [x] Update docs and summary with adapter architecture and future provider path.
- [x] Run focused Gateway tests, ruff, and `git diff --check`.
