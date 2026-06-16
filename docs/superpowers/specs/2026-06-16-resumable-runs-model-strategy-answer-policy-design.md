# Design: Resumable Runs, Model Strategy, Answer Policy, Vision Input, and Model Selector

- **Date**: 2026-06-16
- **Product**: Glomi AI
- **Related epics**: E2 Platform Models, E3 Super Chat Tuning, E4 Deep Research, future E13 Orchestrator
- **Status**: Design approved in discussion; ready for implementation planning

---

## Issues to Address

Glomi AI is moving from a simple chat product toward a consumer super-agent. Five current product gaps block that direction:

1. **Refresh loses in-progress work**: while a chat response is streaming, pressing F5 drops the frontend in-memory stream state. The backend has a short-lived processing fence, but the user cannot reconnect to the running work.
2. **Reasoning strength is not portable**: OpenAI, DeepSeek, Qwen, and GLM expose "thinking" differently. A raw `low / medium / high` knob is not a stable cross-provider product concept.
3. **Answers can be too heavy**: research-style chat often returns too many points at once. Users need the system to find the useful center: concise when possible, deeper only when warranted.
4. **Image and document input is overly blocked**: the frontend currently rejects pasted images when the currently selected model lacks vision support, even though the backend already has image-file and vision-model primitives.
5. **Model availability is not a product catalog**: the current platform default LLM seed initializes a single model per tenant. After upgrades, existing accounts need to receive new platform models, and users need a simple model selector rendered from backend provider/model capabilities.

---

## Important Notes

- Phase A should **not** build the full future Task/Run DAG system. It should make current chat responses resumable after refresh, while leaving a clean path to future persistent super-agent runs.
- The frontend should not infer model capabilities from hardcoded model names. It should trust backend-returned capabilities such as `supports_image_input`.
- The model list should be platform-defined in code for Phase A, not configured as one env var per model. Secrets and API bases still cannot be hardcoded; provider credentials must come from platform deployment configuration or admin-managed provider records.
- Existing tenant/admin choices must not be overwritten by catalog synchronization. Sync should add or update platform-owned records only.
- Search depth, reasoning strength, answer length, and model choice are related but distinct:
  - search depth controls evidence collection;
  - reasoning controls model computation/selection;
  - answer policy controls user-facing length and structure;
  - model selector controls the chosen model for the next turn.
- Model capability notes are based on official/platform docs checked on 2026-06-16:
  - OpenAI GPT-5.5: model docs list text and image input, configurable reasoning, and `gpt-5.5` as the model id.
  - OpenAI vision docs: image inputs are supported by recent language models through OpenAI APIs.
  - DeepSeek V4 Pro: official docs list `deepseek-v4-pro`, 1M context, and thinking/non-thinking modes; no official image-input capability is assumed for Phase A.
  - Qwen3.7 Plus: Qwen official pages describe Qwen3.7-Plus as multimodal; platform materials mention vision-language upgrades.
  - Z.AI GLM-5.2: Z.AI docs show `glm-5.2` as the latest coding/reasoning model with text input. Z.AI vision is exposed through separate vision models such as GLM-5V-Turbo, so `glm-5.2` defaults to no image input.

References:

- https://developers.openai.com/api/docs/models/gpt-5.5
- https://developers.openai.com/api/docs/models
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/guides/reasoning
- https://api-docs.deepseek.com/quick_start/pricing
- https://api-docs.deepseek.com/news/news260424
- https://qwen.ai/
- https://qwen.ai/blog?id=qwen3.7
- https://docs.z.ai/devpack/latest-model
- https://docs.z.ai/devpack/tool/others
- https://docs.z.ai/guides/overview/pricing

---

## Design Principles

1. **Backend is the source of truth**: model capabilities, available models, default model, and image support all come from backend state.
2. **Upgrade-safe by default**: existing accounts should gain newly shipped platform models through an idempotent sync path.
3. **User-facing simplicity**: users choose a model by name. They should not see provider keys, base URLs, or raw reasoning parameters.
4. **Capability-aware input**: when a selected model supports image input, the UI allows image upload/paste. If it does not, the UI blocks images with a clear model-specific hint.
5. **Resumable before orchestration**: make current chat streams refresh-safe before introducing full super-agent run orchestration.

---

## Architecture

### A. Resumable Chat Runs

Add a lightweight run/event layer around existing chat streaming.

Core concepts:

- `chat_run`: one running assistant response tied to `chat_session_id`, user message id, and reserved assistant message id.
- `chat_run_event`: append-only record of stream packets emitted for that run.
- `run_id`: stable identifier returned when the assistant response starts.
- `event_seq`: monotonically increasing offset for replay/resume.

Initial fields:

- `chat_run.id`
- `chat_run.chat_session_id`
- `chat_run.user_message_id`
- `chat_run.assistant_message_id`
- `chat_run.status`: `running | completed | failed | cancelled`
- `chat_run.created_at`, `updated_at`, `completed_at`
- `chat_run.error_detail`
- `chat_run.model_provider`, `chat_run.model_name`

Event fields:

- `chat_run_event.run_id`
- `chat_run_event.seq`
- `chat_run_event.packet_json`
- `chat_run_event.created_at`

Data flow:

1. User sends a chat message.
2. Backend creates normal chat messages plus a `chat_run`.
3. Each stream packet is emitted to the active SSE response and appended to `chat_run_event`.
4. On completion, existing `save_chat_turn` persists the final assistant message and the run becomes `completed`.
5. On browser refresh, chat session load returns active run metadata if a run is still `running`.
6. Frontend opens a resume endpoint with `run_id` and optional `after_seq`.
7. Backend replays stored events after `after_seq`, then streams future events until completion.

Phase A scope:

- Resume only the latest active run in the current chat session.
- Support one active run per chat session.
- Support replaying packets and continuing live stream after refresh.
- Preserve failed/cancelled state.

Out of scope:

- Multi-run task inbox.
- Retry orchestration.
- DAG/sub-agent progress graph.
- Cross-session background task scheduling UI.

### B. Internal Model Roles and Provider Capability Profiles

Introduce a Glomi platform model catalog. It maps platform models to product roles and backend capabilities.

Roles:

- `fast`: titles, classification, small rewrites, lightweight decisions.
- `balanced`: default ordinary chat.
- `reasoning`: careful multi-step judgment, planning, code reasoning.
- `research`: Deep Research planning and synthesis.
- `vision`: image, screenshot, chart, and visual document understanding.
- `coding`: code generation, Craft, and future build agents.

Capabilities:

- `supports_image_input`
- `supports_video_input`
- `supports_reasoning`
- `reasoning_control`: `openai_effort | deepseek_thinking | qwen_thinking | glm_effort | none`
- `context_window`
- `max_output_tokens`
- `is_default`
- `is_visible`

Phase A default catalog:

| Display name | Provider family | Model id | Image input | Reasoning | Roles |
|---|---|---:|---:|---:|---|
| GPT-5.5 | OpenAI | `gpt-5.5` | yes | yes | `balanced`, `reasoning`, `research`, `vision`, `coding` |
| Qwen3.7 Plus | Qwen | `qwen3.7-plus` | yes | yes | `balanced`, `reasoning`, `research`, `vision` |
| DeepSeek V4 Pro | DeepSeek | `deepseek-v4-pro` | no | yes | `reasoning`, `research` |
| GLM-5.2 | Z.AI / GLM | `glm-5.2` | no | yes | `reasoning`, `research`, `coding` |

Provider-specific mapping:

- OpenAI: use OpenAI reasoning effort only for models known to support it.
- DeepSeek: use model-level thinking/non-thinking support where exposed; do not assume OpenAI `reasoning_effort` compatibility.
- Qwen: map thinking behavior through Qwen/DashScope-compatible capability handling where supported.
- GLM: use GLM effort/thinking controls only when the active API supports them; keep image input false for `glm-5.2`.
- Unknown OpenAI-compatible providers: do not pass reasoning or multimodal parameters unless backend capability says they are supported.

### C. Platform Catalog Sync for New and Existing Accounts

Replace single-model tenant initialization with idempotent platform catalog sync.

Sync triggers:

- tenant creation / provisioning;
- backend startup or setup hook;
- user login fallback for old tenants;
- optional admin/manual maintenance endpoint later.

Rules:

- Add missing platform-owned providers/models.
- Update platform-owned capability metadata when the catalog changes.
- Do not overwrite manually edited provider credentials.
- Do not disable custom/admin-created models.
- Do not replace a user's selected model if the user already has one.
- If a user has no selected model, default to the platform default model, initially GPT-5.5.

Implementation boundary:

- The catalog defines model ids and capabilities in code.
- Provider credentials come from platform credential records/config, not from per-user env vars.
- Existing provider architecture remains the persistence mechanism: `LLMProvider`, `ModelConfiguration`, `LLMModelFlow`.

### D. Backend Model List API for the Frontend

Expose a user-facing model list endpoint for chat.

Suggested endpoint:

- `GET /api/chat/available-models`

Response shape:

- `provider_id`
- `provider_name`
- `provider_type`
- `model_id`
- `display_name`
- `supports_image_input`
- `supports_video_input`
- `supports_reasoning`
- `reasoning_control`
- `roles`
- `is_default`
- `is_selected`

The frontend renders only models returned by this endpoint.

### E. Frontend Model Selector

Add a compact model selector near the input submit controls, similar to the Stitch reference:

- current model shown as a pill;
- dropdown groups by provider or recommended role;
- each row shows display name and subtle capability labels such as `图片`, `深思`, `研究`, `代码`;
- no API key/base URL/provider admin detail is visible;
- selecting a model applies to the next message.

Image handling:

- If current model `supports_image_input=true`, allow paste, drag, and picker upload for images.
- If current model `supports_image_input=false`, disable image upload/paste and show a concise hint:
  - "当前模型暂不支持图片。请切换到 GPT-5.5 或 Qwen3.7 Plus。"
- If images are already attached and the user switches to a non-vision model, block the switch or ask them to remove images first.

### F. Answer Shape Policy

Continue the ordinary chat research answer policy, but make it a named product behavior.

Answer shapes:

- `direct_answer`: simple facts, definitions, direct operations.
- `focused_brief`: default for ordinary research, comparison, selection, and planning questions.
- `deep_report`: only when the user asks for report/complete analysis, or when Deep Research is explicitly active.

Default behavior:

- Simple questions get short answers.
- Research-style ordinary chat gives a concise judgment, 3-5 key reasons, evidence quality/conflicts, and next steps if useful.
- Deep Research remains a full report workflow.
- Search depth does not imply output length.

### G. User-Facing Status Copy

Avoid technical reasoning labels.

Use natural status text:

- "正在梳理关键判断..."
- "正在核对资料并归纳重点..."
- "正在深入研究并整理证据..."
- "正在分步推进任务..."
- "正在读取图片..."

Do not show `reasoning_effort=high`, provider params, or raw capability flags in the normal chat UI.

---

## Error Handling

- Use `OnyxError` for new backend API errors.
- If a resume endpoint receives an unknown or unauthorized `run_id`, return `NOT_FOUND` or `PERMISSION_DENIED`.
- If a run is completed, the resume endpoint may return replayed final events or tell the client to reload the chat session.
- If a model no longer exists or is no longer visible, fall back to the platform default model and surface a non-blocking warning.
- If image upload is attempted with a non-vision model, frontend should block before upload. Backend should still validate and reject unsafe mismatches.
- If provider credentials for a platform catalog model are missing, hide that model from the user-facing selector instead of showing a broken option.

---

## Data and Migration Strategy

Database changes are expected for resumable runs:

- add `chat_run`;
- add `chat_run_event`;
- add indexes by `chat_session_id`, `assistant_message_id`, and `(run_id, seq)`.

Catalog sync should be data-safe:

- no destructive migration;
- no mass overwrite of existing provider credentials;
- old tenants are backfilled by idempotent sync;
- all DB operations belong under `backend/onyx/db` or `backend/ee/onyx/db`.

The existing single default provider seed should evolve into platform model catalog sync. The old single-model env path may remain as a compatibility fallback but should no longer be the product model-list mechanism.

---

## Tests

Backend tests:

- unit tests for catalog capability profiles:
  - GPT-5.5 image/reasoning true;
  - Qwen3.7 Plus image/reasoning true;
  - DeepSeek V4 Pro image false, reasoning true;
  - GLM-5.2 image false, reasoning true.
- unit tests for catalog sync:
  - new tenant receives all platform models;
  - old tenant missing models is backfilled;
  - existing manual credentials are not overwritten;
  - selected/default model is not overwritten when already set.
- unit tests for available-models API response shape and permissions.
- unit tests for resumable run event append/replay ordering.
- integration test for refresh recovery:
  - start a streaming response;
  - disconnect/reconnect with `run_id`;
  - verify replay and continued stream produce the same final answer.

Frontend tests:

- selector renders backend models and capability labels.
- image paste is allowed for models with `supports_image_input=true`.
- image paste is blocked for models with `supports_image_input=false`.
- switching to a non-vision model while images are attached is blocked or requires removal.
- selected model is included in the next `send-chat-message` request.

Playwright tests:

- paste an image with GPT-5.5/Qwen3.7 Plus selected and confirm it becomes an attachment.
- select DeepSeek V4 Pro or GLM-5.2 and confirm image paste shows the supported-model hint.
- start a slow streamed answer, refresh, and confirm the in-progress run resumes.

---

## Open Follow-Ups for Implementation Planning

- Decide whether Phase A stores every packet type or a filtered subset of replay-safe packet types.
- Decide whether resume uses SSE only or also supports polling fallback.
- Decide the exact platform credential source for OpenAI/Qwen/DeepSeek/GLM providers.
- Decide if per-user selected model is stored in existing `User.default_model` or a new preference record with provider/model identifiers.
- Decide whether vision fallback should route to a separate vision model automatically, or whether Phase A only allows images when the selected model itself supports them. Current approved direction: frontend allows images only when backend says the selected model supports vision.
