# Part 5: Demo Data & Connector Cleanup — Implementation Plan

> Parent design: [search-design.md](search-design.md) (Part 4 follow-up)

## Objective

Remove the demo data feature and the Craft-specific connector configuration UI. Users connect data sources via the standard admin connectors page. Ships as a single PR.

**Parts 1–4 are complete.** The sandbox now uses `onyx-cli search` for knowledge access (Part 4). The old file-sync infrastructure is removed (PR 3). User library files are delivered via S3 sync (PR 4). What remains is cleanup: the demo data toggle, the Craft connector config UI, and the `FILE_SYSTEM` processing mode bug.

---

## Current State

- **Craft connector UI**: The configure page has its own OAuth/credential flow (`ConfigureConnectorModal`, `CredentialStep`, `ConnectorCard`, etc.) that creates connectors with `FILE_SYSTEM` processing mode. These connectors are **not searchable** — `FILE_SYSTEM` bypasses Vespa indexing.
- **Demo data**: `demo_data.zip` was deleted from the Docker image in PR 3, but the frontend toggle ("Use Demo Dataset"), cookie (`build_demo_data_enabled`), and the `demo_data_enabled` column on `BuildSession` still exist. The only remaining backend effect of `use_demo_data` is gating `org_info/` setup and excluding user context from AGENTS.md.
- **`org_info/`**: Created when `use_demo_data=True` with demo persona info (user identity, org structure). Backed by `persona_mapping.py` and the onboarding flow that collects `user_work_area`/`user_level`.
- **Path sanitizer**: Test cases reference `files/` paths that no longer exist in sessions.

---

## Decisions

| Decision | Rationale |
|----------|-----------|
| Drop `demo_data_enabled` column in the same PR as code removal | Accepted rolling deploy risk. Deploy atomically. |
| Keep onboarding persona flow (`craft/onboarding/`, `persona_mapping.py`) | Useful for personalization. Decouple from demo data — always pass `user_work_area`/`user_level`. |
| Keep `user_work_area`/`user_level` on API | Still used by onboarding, no longer gated behind demo flag. |
| Remove `GET /api/build/connectors` endpoint | Only served the Craft connector UI being deleted. |
| Leave `FILE_SYSTEM` in `ProcessingMode` enum with deprecation comment | Existing rows may reference it. Separate cleanup script later. |
| Old FILE_SYSTEM connectors out of scope | Dozens on cloud. Prefer deletion over conversion. Separate script. |

---

## Implementation

### 1. Remove Craft connector UI

Replace the connector configuration section with a "Connect your data" link to the admin connectors page.

| Action | File |
|--------|------|
| Delete | `craft/v1/configure/components/ConfigureConnectorModal.tsx` |
| Delete | `craft/v1/configure/components/ConnectorCard.tsx` |
| Delete | `craft/v1/configure/components/ConnectorConfigStep.tsx` |
| Delete | `craft/v1/configure/components/CredentialStep.tsx` |
| Delete | `craft/v1/configure/components/CreateCredentialInline.tsx` |
| Delete | `craft/v1/configure/components/ComingSoonConnectors.tsx` |
| Delete | `craft/v1/configure/components/RequestConnectorModal.tsx` |
| Delete | `craft/v1/configure/components/ConfigureOverlays.tsx` |
| Delete | `craft/v1/configure/utils/createBuildConnector.ts` |
| Delete | `craft/hooks/useBuildConnectors.ts` |
| Modify | `craft/v1/configure/page.tsx` — remove connector cards, keep LLM + user library + persona. Add "Connect your data" link. Add standalone User Library trigger (was on CraftFile connector card). |
| Modify | `craft/components/ConnectDataBanner.tsx` — replace with link to admin connectors page |
| Modify | `craft/components/ConnectorBannersRow.tsx` — same |
| Modify | `craft/services/apiServices.ts` — remove `deleteConnector()` |
| Modify | `web/src/lib/swr-keys.ts` — remove `buildConnectors` key |

### 2. Remove Craft connector backend

| Action | File |
|--------|------|
| Delete or gut | `backend/onyx/server/features/build/api/api.py` — remove `GET /api/build/connectors` |
| Modify | `backend/onyx/server/features/build/api/models.py` — remove `BuildConnectorStatus`, `BuildConnectorInfo`, `BuildConnectorListResponse` |
| Modify | `backend/onyx/db/enums.py` — add deprecation comment to `FILE_SYSTEM` |
| Modify | `web/src/lib/types.ts` — remove `FILE_SYSTEM` from TS `ProcessingMode` type |

### 3. Remove demo data frontend

| Action | File |
|--------|------|
| Delete | `craft/v1/configure/components/DemoDataConfirmModal.tsx` |
| Modify | `craft/v1/constants.ts` — remove cookie functions |
| Modify | `craft/v1/configure/page.tsx` — remove demo data state, toggle, auto-enable |
| Modify | `craft/services/apiServices.ts` — remove `demoDataEnabled` from session creation |
| Modify | `craft/components/InputBar.tsx` — remove `demoDataEnabled` from callback, remove pill |
| Modify | `craft/components/ChatPanel.tsx` — remove unused `demoDataEnabled` param |
| Modify | `craft/components/BuildWelcome.tsx` — remove `demoDataEnabled` from callback |
| Modify | `craft/hooks/useBuildSessionStore.ts` — remove `demoDataEnabled` from state |

### 4. Remove demo data backend

Decouple `org_info/` from demo data: always set up when `user_work_area` is provided.

| Action | File |
|--------|------|
| Modify | `sandbox/base.py` — remove `use_demo_data` from `setup_session_workspace()`, `restore_snapshot()` |
| Modify | `sandbox/kubernetes/kubernetes_sandbox_manager.py` — remove `use_demo_data`, always set up org_info when work_area provided |
| Modify | `sandbox/local/local_sandbox_manager.py` — same |
| Modify | `sandbox/manager/directory_manager.py` — remove `use_demo_data` from `setup_agent_instructions()` |
| Modify | `sandbox/util/agent_instructions.py` — remove `use_demo_data`, `include_org_info`. Always include user context. |
| Modify | `session/manager.py` — remove `demo_data_enabled`. Always pass `user_work_area`/`user_level`. |
| Modify | `api/sessions_api.py` — remove `demo_data_enabled` gating |
| Modify | `api/models.py` — remove `demo_data_enabled` from `SessionCreateRequest` |
| Modify | `db/build_session.py` — remove `demo_data_enabled` from create/query |
| Modify | `db/models.py` — remove `demo_data_enabled` from `BuildSession` |
| Migration | `alembic/` — drop `demo_data_enabled` column |

**Keep**: `persona_mapping.py`, `craft/onboarding/`, `user_work_area`/`user_level`.

### 5. Path sanitizer cleanup

| Action | File |
|--------|------|
| Modify | `craft/utils/pathSanitizer.test.ts` — replace `files/` paths with `user_library/` |
| Modify | `craft/utils/pathSanitizer.ts` — update stale comment |

---

## File changes summary

~40 files: ~12 deletions, ~25 modifications, 1 migration.

## Tests

- New connectors use `REGULAR` processing mode and are searchable
- Session creation works without `demo_data_enabled`
- `org_info/` created when `user_work_area` provided (no demo flag)
- Configure page renders: LLM selection, user library, "Connect your data" link
- Banners link to admin connectors page
- Path sanitizer tests pass
