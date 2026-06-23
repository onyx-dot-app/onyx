# Platform Provider Contracts Design

## Issues to Address

Glomi platform models currently mix three separate concepts:

- Product supplier: GPT, MiniMax, and later other platform suppliers.
- Runtime transport: `openai_compatible`, OpenRouter, Anthropic, and other provider types.
- Stream semantics: visible answer text, reasoning text, tool calls, multimodal payloads, and errors.

This caused three visible problems:

1. MiniMax appears as a separate supplier in the model picker, but runtime behavior is only generic `openai_compatible`. MiniMax can stream `<think>...</think>` inside ordinary content, so the chat UI renders reasoning tags as final answer text.
2. GPT gateway models also use `openai_compatible`, but the gateway output already fits the existing Onyx/LiteLLM assumptions. That success hid the fact that OpenAI-compatible transport does not guarantee OpenAI-compatible semantics.
3. The GPT platform provider can show many models from the upstream `/models` endpoint even though Glomi's product expectation is a fixed platform catalog controlled by `GLOMI_ENABLED_LLM_MODELS`.

## Important Notes

- `backend/onyx/db/glomi_model_catalog.py` is already the best source of platform supplier and model metadata. It should become the authority for user-facing platform model exposure.
- `backend/onyx/server/query_and_chat/chat_backend.py` currently builds `/api/chat/available-models` from DB-visible `ModelConfiguration` rows. It does not re-apply the Glomi catalog allowlist when reading.
- `backend/onyx/llm/litellm_singleton/monkey_patches.py` already handles Ollama `<think>` chunks, but MiniMax through `openai_compatible` does not use the Ollama transformer path.
- The fix should preserve existing admin/custom-provider behavior. Non-Glomi providers may still expose DB-visible models.
- Frontend rendering should remain packet-driven. The backend must normalize provider streams into `reasoning_content` vs `content` before packets are emitted.

## Design

Glomi platform suppliers remain represented as concrete `LLMProvider` rows, but their user-facing model set is filtered by the platform catalog at read time. A provider identified by `(provider_name, provider_type)` as a Glomi supplier may only return model IDs that are present in its enabled catalog entry. Historical DB rows from admin fetches or upstream `/models` sync remain in the database, but they do not appear in `/api/chat/available-models`.

OpenAI-compatible response normalization gains a small adapter in the LLM response boundary. For `openai_compatible` streams, content inside `<think>` or `<thinking>` tags is routed to `Delta.reasoning_content`; content outside the tags remains `Delta.content`. The adapter is stateful per stream so split tags, multi-chunk reasoning, and tags split across chunk boundaries do not leak into the visible answer. On final chunks, any pending partial-tag text is flushed back to the appropriate visible or reasoning field so ordinary text is not lost. Non-streaming `invoke()` responses also pass through the same normalizer after LiteLLM reassembles stream chunks. Existing provider-native `reasoning_content` remains untouched.

The frontend keeps consuming the same `reasoning_start`, `reasoning_delta`, `reasoning_done`, and `message_delta` packets. No UI patch should strip raw reasoning tags as the primary fix.

## Implementation Strategy

1. Extend `glomi_model_catalog.py` with provider-scoped enabled model lookup helpers.
2. Update `build_available_chat_models_response` to skip non-catalog models for Glomi platform providers.
3. Add a unit test showing that a `Glomi Default / openai_compatible` provider with extra visible DB models only returns enabled catalog models.
4. Add a stateful tagged-reasoning normalizer for streamed `Delta.content`.
5. Apply that normalizer only to the OpenAI-compatible stream path in `LitellmLLM.stream`.
6. Add unit tests for split `<think>` chunks, same-chunk close tags, tags split across chunk boundaries, final partial-tag flushing, normal content after reasoning, and OpenAI-compatible `invoke()` normalization.
7. Update `summary.md` and `docs/GlomiAI.md` with the platform provider contract.

## Tests

- Backend unit tests for `/api/chat/available-models` response building.
- Backend unit tests for streamed OpenAI-compatible tagged reasoning normalization.
- Existing LiteLLM monkey patch tests should still pass.

## Non-Goals

- Do not redesign all provider storage.
- Do not require a new first-class MiniMax provider type in this step.
- Do not expose upstream `/models` results to C-end users for Glomi platform providers.
- Do not solve every provider-specific error format; this step only addresses the provider contract issues observed above.
