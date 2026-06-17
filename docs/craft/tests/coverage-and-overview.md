# Craft Test Coverage

Craft is Onyx's sandboxed build environment — per-user pods running an AI agent with admin-published skills. This doc summarizes what our test suite covers and where the boundaries are.

## What we test

### Security boundaries

- **Tar/zip extraction safety** — symlink rejection, path traversal, size caps, atomic swap, permission masking. Both the bundle validator and the in-pod extractor are tested independently.
- **Path sanitization** — file-op endpoints reject `..`, URL-encoded traversal, null bytes, and shell metacharacters. Tested at pure-logic and HTTP layers.
- **Bundle validation** — slug format, missing SKILL.md, template rejection, symlink detection, size caps, reserved-slug collision.
- **Skill visibility** — admins see everything, users see only public + granted skills, curators get the regular-user filter.
- **Auth gating** — admin endpoints reject non-admins; user endpoints require auth.

### Skill push pipeline

- **End-to-end push** — public skills land in every running sandbox; private skills respect grants; sleeping/terminated sandboxes are skipped; disable removes files; grants changes add/remove correctly; bundle replacement propagates; deletion cleans up; partial failure is logged not raised.
- **Affected-user join logic** — public/private branches, dedup across groups, eager-load regression.
- **Fileset assembly** — built-in skills (static + template-rendered), custom bundles, exclusion filters.

### Sandbox lifecycle

- Provision → running transition, idempotent provision, health-check-failure recovery, idle cleanup (including NULL-heartbeat edge case), session create/reuse/delete cascades, port allocation, Redis lock serialization.
- **K8s contract** (K8s CI only) — pod directories, session workspace tree, signed tarball push, atomic swap, bad-signature rejection, ephemeral ACP client lifecycle, cancel-during-send race.

### Streaming + persistence

- **BuildStreamingState** — chunk accumulation, type-change finalization, boundary detection.
- **DB persistence** — agent messages persist as single rows, tool_call_start is never persisted, completed tool calls are, TodoWrite persists on every update, plans are upserted per turn, turn index increments correctly.
- **Error semantics** — sandbox-not-running, session-not-found, agent exceptions, timeout and keepalive.

### HTTP API

- **Sessions** — create, list, delete, restore (with lock contention), pre-provisioned check, sandbox reset, generate-suggestions fallback, rename fallback chain, limited-role check.
- **Uploads** — success, auth, foreign session rejection, blocked extensions, unicode filenames.
- **File ops** — path traversal rejection on every verb, hidden-entry filtering, cross-user isolation, opencode.json hidden from download.
- **Skills admin** — full CRUD HTTP contract, invalid/oversized/corrupt bundle rejection, duplicate slug, FK violation on unknown group, orphan-blob cleanup. Push-pipeline side effects (visibility change, description-only no-op, replace/delete propagation, grant union) live in the ext-dep tier — see `external_dependency_unit/craft/test_skill_push.py`.
- **Webapp proxy** — sharing scope enforcement, set-cookie stripping, route-order, cross-session isolation.
- **User library** — upload/delete/toggle, cross-user isolation.
- **Scheduled tasks** — cron compilation, paired-field validation, run-now on paused, idempotent soft-delete, pagination.

### Other

- **PAT lifecycle** — mint, reuse, hash-mismatch revocation, multi-stale cleanup, expiry remint.
- **Push retry + error mapping** — retry on retriable errors, give up after 3, no retry on fatal, daemon 5xx/4xx/timeout classification.
- **In-pod push daemon** — Ed25519 signature verification, timestamp drift, SHA mismatch, size cap, mount-path prefix.
- **Snapshot/restore** (K8s only) — inclusion/exclusion rules, restore re-pushes skills, traversal blocked, streamed archive checksum validation.
- **Feature gating** — env-var fallback, PostHog flag override.

## What we don't test

- **Pod-side skill scripts** (`onyx/skills/builtin/pptx/scripts/*.py`) — run inside the sandbox, not reachable from the backend Python path.
- **Celery dispatch shims** — the thin `@shared_task` wrappers are covered transitively by executor tests.
- **Frontend Craft E2E** — no Playwright tests for build mode yet.
- **Sidecar regressions** (`/exec` pipe-deadlock, `/files/read` TOCTOU) — different deployment shape.

## Known bugs pinned by xfail tests

| Test | Bug |
|---|---|
| `test_pod_name_uses_full_uuid_not_first_8_chars` | `_get_pod_name` truncates to 8 hex chars (32 bits). Birthday collision at ~77k sandboxes; current failure is K8s 409, not data leak. |
| `test_pat_refreshes_on_reprovision_after_expiry` | No background PAT refresh on long-lived sandboxes. Masked by 1h idle cleanup. |

## Where to find things

| What | Where |
|---|---|
| Unit tests (pure logic) | `backend/tests/unit/onyx/skills/` and `backend/tests/unit/onyx/server/features/build/` |
| Ext-dep tests (real DB) | `backend/tests/external_dependency_unit/craft/` |
| Integration tests (real HTTP) | `backend/tests/integration/tests/craft/` and `backend/tests/integration/tests/skills/` |
| K8s-gated tests | `test_kubernetes_sandbox.py` and `test_snapshot_restore.py` (file-level `skipif`) |
| Shared fixtures | `backend/tests/external_dependency_unit/craft/conftest.py` |
| Stub sandbox manager | `backend/tests/common/craft/stubs.py` |
| Shared helpers | `backend/tests/external_dependency_unit/craft/_test_helpers.py` |
| Integration HTTP wrappers | `backend/tests/integration/common_utils/managers/skill.py` and `build_session.py` |
