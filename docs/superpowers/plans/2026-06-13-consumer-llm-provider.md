# Consumer LLM Provider Implementation Plan

> **For agentic workers:** Implement inline task-by-task. Use TDD for behavior changes, keep edits scoped, and record implementation notes in `summary.md`.

**Goal:** New consumer tenants get a platform-managed Qwen OpenAI-compatible provider and users can choose safe model profiles without seeing provider credentials.

**Architecture:** Reuse Onyx's existing `LLMProvider`, `ModelConfiguration`, `LLMModelFlow`, and `User.default_model` surfaces. Add a consumer-facing catalog/profile layer that maps product profile IDs to platform-controlled provider/model/parameter metadata, then seed the backing provider idempotently.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Pydantic, Next.js/React/TypeScript/SWR.

---

## Issues to Address

- The current LLM configuration flow assumes an admin configures providers manually.
- New tenants and single-tenant installs need an automatic platform Qwen provider seed when enabled and configured.
- Ordinary users need a safe catalog/preference API that exposes profile metadata only, not provider IDs, API keys, API base URLs, or cost parameters.
- Existing user preference and chat runtime model selection should keep working with the new profile abstraction.
- Provider/model seeding must be idempotent and must hide removed catalog models instead of deleting them.

## Important Notes

- `backend/ee/onyx/server/tenants/provisioning.py` already seeds default OpenAI/Anthropic/OpenRouter providers during tenant setup via `configure_default_api_keys`.
- `backend/onyx/setup.py` runs single-tenant setup and can seed the default provider for the public schema.
- `backend/onyx/db/llm.py` owns provider/model DB operations; new DB operations must stay under `backend/onyx/db`.
- `User.default_model` already stores a structured frontend model choice string and is exposed in `UserInfo.preferences.default_model`.
- The user-facing `/api/llm/provider` endpoint already returns safe provider/model descriptors, but the new catalog API should be smaller and profile-oriented.
- Frontend standards prefer Opal/refresh components and forbid new raw inputs/buttons and non-project icon libraries.

## Implementation Strategy

### Task 1: Catalog and Profile Resolution

- Add a strictly typed backend catalog module for consumer Qwen profiles.
- Add config values for enabling the consumer default provider, provider name/type, API base/key, and default profile.
- Implement profile validation and fallback rules:
  - missing preference falls back to configured default profile;
  - unknown profile falls back to default profile;
  - if the configured default is invalid, fall back to `balanced`.
- Add unit tests for catalog shape, fallback, and sanitized API response models.

### Task 2: Idempotent Provider Seed

- Add `backend/onyx/db/consumer_llm.py` for all consumer default provider DB operations.
- Seed an `openai_compatible` Qwen provider only when enabled, the API key is present, and auto-provisioning is enabled.
- Upsert visible catalog models and mark no-longer-cataloged models invisible rather than deleting.
- Set the chat default to the default profile model when there is no existing default, or when a force flag is later added.
- Set the vision default when the catalog includes a vision profile and no vision default exists.
- Add external-dependency unit tests for idempotent seed behavior where practical; otherwise add unit coverage around request construction and mark DB coverage as a follow-up if local services are unavailable.

### Task 3: Wire Seeding Into Setup

- Call the consumer seed from multi-tenant provisioning after the existing default provider seed.
- Call the consumer seed from single-tenant setup after `setup_postgres`.
- Log clear skip reasons for disabled config, missing key, or disabled default provider auto-provisioning.
- Keep failures isolated so an optional consumer default seed does not break unrelated setup.

### Task 4: Consumer Model Catalog APIs

- Add a user-facing FastAPI router for:
  - `GET /api/model-catalog`
  - `GET /api/user/model-preference`
  - `PUT /api/user/model-preference`
- Return profile metadata only: profile id, label, description, supports image, and default profile id.
- Store preference through the existing `User.default_model` structured model string so current chat model selection can resolve it.
- Use `OnyxError` for invalid requests and service-unavailable states.
- Add unit tests or API-level tests for sanitized responses and preference fallback.

### Task 5: Frontend Model Selector

- Add typed frontend API helpers and a hook for the consumer model catalog/preference.
- Add a compact profile selector near the chat model control, using existing Opal/refresh components.
- Selecting a profile should update both the saved backend preference and the active `llmManager` model descriptor.
- The selector must never render provider credentials, base URLs, or advanced model parameters.
- Add focused TypeScript tests for mapping profile responses to model descriptors and fallback display behavior.

### Task 6: Verification and Notes

- Run targeted backend tests for catalog and seed behavior.
- Run targeted frontend tests for selector/helper behavior if frontend code changes.
- Run type or lint checks for touched TypeScript where feasible.
- Update `summary.md` with changes, pitfalls, and lessons learned.

## Tests

- Unit tests:
  - catalog default profile validation;
  - unknown profile fallback;
  - sanitized catalog response;
  - conversion from profile to `User.default_model` structured value.
- External dependency unit tests:
  - seed creates the Qwen provider and visible model configurations;
  - repeated seed does not duplicate providers or models;
  - removed catalog models are hidden rather than deleted.
- Integration/Playwright:
  - defer broad registration and live chat tests unless the implementation reaches frontend runtime wiring and services are confirmed running.
