# Local Glomi Search Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable local Glomi Search Gateway service that lets Onyx use a Tavily API key through the existing `glomi` web search provider.

**Architecture:** Add a standalone FastAPI app under `backend/onyx/search_gateway`. Keep protocol models, Tavily adapter, configuration, and HTTP server/auth separate so the Gateway can be tested without live Tavily calls.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, httpx, pytest, FastAPI TestClient.

---

## Files

- Create `backend/onyx/search_gateway/__init__.py` for package initialization.
- Create `backend/onyx/search_gateway/models.py` for request/response models and query cleanup.
- Create `backend/onyx/search_gateway/config.py` for environment-driven Gateway config.
- Create `backend/onyx/search_gateway/tavily.py` for Tavily API mapping and result normalization.
- Create `backend/onyx/search_gateway/server.py` for `create_app()`, `/health`, `/search`, and bearer auth.
- Create `backend/tests/unit/onyx/search_gateway/test_tavily.py`.
- Create `backend/tests/unit/onyx/search_gateway/test_server.py`.
- Modify `.vscode/.env` to add local Gateway variables without adding real secrets.
- Modify `docs/GlomiAI.md` and `summary.md`.

## Tasks

### Task 1: Tests First

- [ ] Write failing tests for the Tavily adapter.
- [ ] Write failing tests for the FastAPI server auth/channel/delegation behavior.
- [ ] Run the new tests and verify they fail because `onyx.search_gateway` does not exist yet.

### Task 2: Gateway Models And Config

- [ ] Add Pydantic request and response models.
- [ ] Add environment config with `GLOMI_SEARCH_GATEWAY_API_KEY`, `TAVILY_API_KEY`, `GLOMI_SEARCH_GATEWAY_TAVILY_API_URL`, and `GLOMI_SEARCH_GATEWAY_TIMEOUT_SECONDS`.
- [ ] Run the new tests and verify model/config imports are no longer the failing point.

### Task 3: Tavily Adapter

- [ ] Implement Tavily payload construction.
- [ ] Map `lite` to `basic` and `deep` to `advanced`.
- [ ] Normalize `title`, `url`, `content`/`snippet`, `author`, and `published_date`.
- [ ] Dedupe by URL and truncate to `max_results`.
- [ ] Run `test_tavily.py`.

### Task 4: FastAPI Server

- [ ] Add `create_app()` with `GET /health` and `POST /search`.
- [ ] Register shared `OnyxError` handlers.
- [ ] Enforce Gateway bearer auth.
- [ ] Reject unsupported channels.
- [ ] Run `test_server.py`.

### Task 5: Docs And Verification

- [ ] Add local Gateway env examples to `.vscode/.env`.
- [ ] Update `docs/GlomiAI.md` and `summary.md`.
- [ ] Run focused Gateway tests plus existing Glomi web search tests.
- [ ] Run `git diff --check`.
