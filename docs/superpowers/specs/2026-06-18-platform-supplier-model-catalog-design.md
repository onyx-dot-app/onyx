# Platform Supplier Model Catalog Design

## Issues To Address

The current Glomi platform model catalog stores multiple model families under one `openai_compatible` provider. This keeps runtime calls working, but it prevents the chat model picker from showing the product shape we want: supplier groups first, then provider instances, then concrete model IDs.

For the next test we need GPT models to keep using the existing platform gateway, while MiniMax uses an official MiniMax endpoint and key such as `https://api.minimax.io/v1`.

## Important Notes

- The existing runtime path should stay intact: model selection still resolves to an existing `LLMProviderModel` plus a `ModelConfiguration`.
- MiniMax can be represented as `openai_compatible` for this phase because its official API exposes OpenAI-compatible chat completions.
- Frontend grouping should be driven by backend metadata, not by model-name guessing or hardcoded provider lists.
- Existing `CONSUMER_DEFAULT_LLM_*` env vars remain the backward-compatible GPT provider seed.
- New MiniMax env vars should be additive and optional.

## Implementation Strategy

Add supplier metadata to the platform catalog. Each catalog provider has a `supplier_id`, `supplier_display_name`, provider connection settings, and model configurations. Syncing the catalog creates or updates one LLM provider per catalog provider, preserving existing credentials for already-created providers.

Extend `/api/chat/available-models` to include supplier metadata for each model. The frontend conversion layer passes those fields into `LLMProviderDescriptor` and `ModelConfiguration`. The chat model popover groups models by `supplier_id` when present, falling back to the previous provider/vendor grouping for non-Glomi providers.

For the first test catalog:

- GPT supplier: existing `CONSUMER_DEFAULT_LLM_*`, model defaults stay `gpt-5.5`.
- MiniMax supplier: `GLOMI_MINIMAX_LLM_*`, default model `MiniMax-M3`.

## Tests

- Unit test catalog construction and sync for GPT + MiniMax providers.
- Unit test `/api/chat/available-models` supplier metadata.
- Frontend unit tests for backend response conversion and model popover grouping.
- Run focused backend and frontend tests only; no integration test is needed for this metadata and seed change.
