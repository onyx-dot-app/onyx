# Platform Provider Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Glomi platform model exposure catalog-driven and normalize MiniMax/OpenAI-compatible `<think>` responses before they reach chat rendering or non-streaming consumers.

**Architecture:** `glomi_model_catalog.py` owns supplier-scoped model allowlisting. `chat_backend.py` applies that allowlist when building `/api/chat/available-models`. `multi_llm.py` applies a tagged-reasoning normalizer for OpenAI-compatible streamed deltas before `llm_step.py` turns deltas into packets, and applies the same normalizer to `invoke()` responses after LiteLLM reassembles stream chunks.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy model objects, Pydantic response models, pytest.

---

## Files

- Modify: `backend/onyx/db/glomi_model_catalog.py`
- Modify: `backend/onyx/server/query_and_chat/chat_backend.py`
- Modify: `backend/onyx/llm/model_response.py`
- Modify: `backend/onyx/llm/multi_llm.py`
- Modify: `backend/tests/unit/onyx/server/query_and_chat/test_available_models_api.py`
- Modify: `backend/tests/unit/onyx/db/test_glomi_model_catalog.py`
- Modify: `backend/tests/unit/onyx/llm/test_model_response.py`
- Modify: `backend/tests/unit/onyx/llm/test_multi_llm.py`
- Modify: `summary.md`
- Modify: `docs/GlomiAI.md`

## Tasks

### Task 1: Catalog allowlist at chat model read time

- [x] Add a failing test in `backend/tests/unit/onyx/server/query_and_chat/test_available_models_api.py` that builds a `Glomi Default / openai_compatible` provider with visible `gpt-5.5`, `codex-auto-review`, and `gpt-4o-audio-preview`, patches `GLOMI_ENABLED_LLM_MODELS` to `gpt-5.5`, and asserts only `gpt-5.5` is returned.
- [x] Run `pytest -q backend/tests/unit/onyx/server/query_and_chat/test_available_models_api.py::test_available_chat_models_filters_glomi_provider_to_enabled_catalog_models` and confirm it fails because extra visible models leak.
- [x] Add provider-scoped lookup helpers to `backend/onyx/db/glomi_model_catalog.py`.
- [x] Use those helpers in `build_available_chat_models_response` before appending models.
- [x] Re-run the targeted test and confirm it passes.

### Task 2: OpenAI-compatible tagged reasoning stream normalization

- [x] Add failing tests in `backend/tests/unit/onyx/llm/test_model_response.py` for a stateful normalizer that converts `<think>reasoning</think>answer` content into `reasoning_content="reasoning"` and `content="answer"`.
- [x] Add a failing test for split chunks: `<think>step 1`, ` step 2`, `</think>final`.
- [x] Add failing tests for tags split across chunk boundaries, final partial-tag flushing, and OpenAI-compatible `invoke()` normalization.
- [x] Run the targeted tests and confirm they fail because the normalizer/flush/invoke behavior is missing.
- [x] Implement the normalizer in `backend/onyx/llm/model_response.py`.
- [x] Apply the normalizer in `LitellmLLM.stream` when `self._model_provider == LlmProviderNames.OPENAI_COMPATIBLE`.
- [x] Apply the normalizer to OpenAI-compatible `LitellmLLM.invoke` responses after LiteLLM reassembles stream chunks.
- [x] Re-run the targeted tests and confirm they pass.

### Task 3: Documentation and regression verification

- [x] Update `summary.md` with the allowlist and reasoning-normalization behavior.
- [x] Update `docs/GlomiAI.md` E2 / 对话模型 text to state that platform providers are catalog-filtered at read time and OpenAI-compatible suppliers may have supplier-specific response normalization.
- [x] Run:

```bash
pytest -q backend/tests/unit/onyx/server/query_and_chat/test_available_models_api.py backend/tests/unit/onyx/llm/test_model_response.py backend/tests/unit/onyx/llm/test_litellm_monkey_patches.py
```

- [x] If the full command fails, fix the failing behavior and re-run until the targeted suite passes.
