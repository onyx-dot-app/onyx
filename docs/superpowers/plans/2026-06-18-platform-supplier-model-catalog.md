# Platform Supplier Model Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backend-controlled supplier model catalog so GPT and MiniMax appear as separate model-picker groups while still using concrete provider/model runtime selections.

**Architecture:** The backend catalog becomes a list of provider entries tagged with supplier metadata. Sync creates one `LLMProviderModel` per provider entry and `/api/chat/available-models` carries supplier fields to the frontend. The frontend groups model options by backend supplier metadata when available.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, SQLAlchemy model objects, Jest/Bun frontend unit tests, TypeScript React.

---

## File Structure

- Modify `backend/onyx/configs/app_configs.py`: add optional MiniMax env config.
- Modify `backend/onyx/db/glomi_model_catalog.py`: replace flat model catalog with supplier-tagged provider entries and multi-provider sync.
- Modify `backend/onyx/db/consumer_llm.py`: call the new multi-provider sync while preserving legacy enablement gates.
- Modify `backend/onyx/server/query_and_chat/models.py`: add supplier fields to `AvailableChatModel`.
- Modify `backend/onyx/server/query_and_chat/chat_backend.py`: populate supplier fields from provider/model metadata.
- Modify backend tests under `backend/tests/unit/onyx/db` and `backend/tests/unit/onyx/server/query_and_chat`.
- Modify `web/src/lib/languageModels/types.ts`: add supplier fields.
- Modify `web/src/lib/languageModels/chatAvailableModels.ts`: preserve supplier metadata.
- Modify `web/src/refresh-components/popovers/interfaces.ts`, `llmUtils.ts`, and `LLMPopover.tsx`: group by supplier.
- Modify frontend tests under `web/src/lib/languageModels` and `web/src/refresh-components/popovers`.
- Modify `deployment/docker_compose/env.template`, `.vscode/.env.k8s.template`, `docs/GlomiAI.md`, and `summary.md`.

## Task 1: Backend Catalog Tests

**Files:**
- Modify: `backend/tests/unit/onyx/db/test_glomi_model_catalog.py`
- Modify: `backend/onyx/db/glomi_model_catalog.py`

- [ ] **Step 1: Write failing tests for supplier provider entries**

Add tests asserting the catalog contains a GPT provider and an optional MiniMax provider when MiniMax config is enabled, with supplier IDs and model lists.

- [ ] **Step 2: Run backend catalog tests to verify failure**

Run: `source .venv/bin/activate && pytest -q backend/tests/unit/onyx/db/test_glomi_model_catalog.py`

Expected: FAIL because supplier catalog APIs and MiniMax config do not exist.

- [ ] **Step 3: Implement catalog provider entries**

Add supplier metadata dataclasses and `GLOMI_GPT_PLATFORM_MODELS` / `GLOMI_MINIMAX_PLATFORM_MODELS`. Build catalog providers from legacy GPT env vars plus optional MiniMax env vars.

- [ ] **Step 4: Run backend catalog tests to verify pass**

Run: `source .venv/bin/activate && pytest -q backend/tests/unit/onyx/db/test_glomi_model_catalog.py`

Expected: PASS.

## Task 2: Available Models API Contract

**Files:**
- Modify: `backend/onyx/server/query_and_chat/models.py`
- Modify: `backend/onyx/server/query_and_chat/chat_backend.py`
- Create or modify: `backend/tests/unit/onyx/server/query_and_chat/test_available_chat_models.py`

- [ ] **Step 1: Write failing test for supplier fields**

Test `build_available_chat_models_response` with a provider named `Glomi MiniMax` and assert each model returns `supplier_id="minimax"` and `supplier_display_name="MiniMax"`.

- [ ] **Step 2: Run the focused API contract test**

Run: `source .venv/bin/activate && pytest -q backend/tests/unit/onyx/server/query_and_chat/test_available_chat_models.py`

Expected: FAIL because supplier fields are missing.

- [ ] **Step 3: Add supplier fields and lookup helper**

Add optional fields to `AvailableChatModel`. Populate them from a helper in `glomi_model_catalog` that maps provider name/type to supplier metadata.

- [ ] **Step 4: Run the focused API contract test**

Run: `source .venv/bin/activate && pytest -q backend/tests/unit/onyx/server/query_and_chat/test_available_chat_models.py`

Expected: PASS.

## Task 3: Frontend Grouping Contract

**Files:**
- Modify: `web/src/lib/languageModels/types.ts`
- Modify: `web/src/lib/languageModels/chatAvailableModels.ts`
- Modify: `web/src/lib/languageModels/chatAvailableModels.test.ts`
- Modify: `web/src/refresh-components/popovers/interfaces.ts`
- Modify: `web/src/refresh-components/popovers/llmUtils.ts`
- Modify: `web/src/refresh-components/popovers/LLMPopover.tsx`
- Modify: `web/src/refresh-components/popovers/LLMPopover.test.tsx`

- [ ] **Step 1: Write failing frontend tests**

Add tests showing backend supplier fields are preserved and `groupLlmOptions` groups GPT and MiniMax separately even though both providers are `openai_compatible`.

- [ ] **Step 2: Run frontend tests to verify failure**

Run: `cd web && bun test src/lib/languageModels/chatAvailableModels.test.ts src/refresh-components/popovers/LLMPopover.test.tsx`

Expected: FAIL because supplier fields are not represented.

- [ ] **Step 3: Implement TypeScript supplier metadata propagation and grouping**

Add `supplier_id` / `supplier_display_name` to response types, descriptors, model configurations, LLM options, and grouping logic.

- [ ] **Step 4: Run frontend tests to verify pass**

Run: `cd web && bun test src/lib/languageModels/chatAvailableModels.test.ts src/refresh-components/popovers/LLMPopover.test.tsx`

Expected: PASS.

## Task 4: Env And Product Docs

**Files:**
- Modify: `deployment/docker_compose/env.template`
- Modify: `.vscode/.env.k8s.template`
- Modify: `docs/GlomiAI.md`
- Modify: `summary.md`

- [ ] **Step 1: Document MiniMax env variables**

Add `GLOMI_MINIMAX_LLM_ENABLED`, `GLOMI_MINIMAX_LLM_API_BASE`, `GLOMI_MINIMAX_LLM_API_KEY`, and `GLOMI_MINIMAX_LLM_MODEL_NAMES` examples.

- [ ] **Step 2: Update product docs and summary**

Update E2 references from a flat model directory to supplier-grouped GPT/MiniMax provider catalog.

- [ ] **Step 3: Run final focused verification**

Run backend and frontend focused tests plus `git diff --check`.

Expected: all focused tests pass and diff check has no whitespace errors.

## Self-Review

- Spec coverage: The plan covers backend supplier catalog construction, API metadata, frontend grouping, env templates, `docs/GlomiAI.md`, and `summary.md`.
- Placeholder scan: No TBD/TODO placeholders remain.
- Type consistency: Supplier fields use `supplier_id` and `supplier_display_name` consistently across Python response models and TypeScript response/option types.
