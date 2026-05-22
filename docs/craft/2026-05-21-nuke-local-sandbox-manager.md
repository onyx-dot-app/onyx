# Nuke LocalSandboxManager

## Context

Today the default Craft dev loop runs against `LocalSandboxManager` (filesystem-backed, `SANDBOX_BACKEND=local`). That path is a maintenance liability — a ~2,700-line second implementation of the `SandboxManager` contract that drifts from the production kubernetes path, with bugs only reproducing on one side or the other (recent snapshot sub-string and service race-condition bugs only existed on the k8s side because local hides those concerns). Tests that exercise generic sandbox behavior (file ops, upload, snapshot, health) are pinned to the local class instead of the contract, so green CI does not prove the production code path works. New devs are pointed at the local path by default even though we already ship a polished kind-based workflow in `docs/dev/local-kubernetes.md`.

This change removes the local backend entirely and makes the kind cluster the canonical Craft dev environment. Coverage currently provided by `test_local_sandbox_*` is migrated onto the existing `pr-craft-k8s-tests.yml` workflow so it runs against a real cluster. A new `make craft-up` target + vscode task collapse the multi-step kind onboarding into one command, and `docs/dev/local-kubernetes.md` + the sandbox README are rewritten so the kind path is the obvious and only option.

Out of scope: the `docker` sandbox backend (`SandboxBackend.DOCKER`) stays.

## Issues to Address

1. Remove `LocalSandboxManager` and the entire `backend/onyx/server/features/build/sandbox/local/` directory.
2. Migrate test coverage off `LocalSandboxManager` and onto the existing kind-based k8s test suite without losing any assertions.
3. Make `SANDBOX_BACKEND=kubernetes` the only Craft dev path: change the default, fail fast on stale `"local"` values, and remove the dead env vars (`SANDBOX_BASE_PATH`, etc.).
4. Make Craft dev setup obvious and one-command: ship `make craft-up` + a `craft: up` vscode task that wraps cluster bring-up, sandbox image build/load, and `.env.k8s` bootstrap.
5. Expand `docs/dev/local-kubernetes.md` with the missing concrete operational detail (kubectl context inspection/switching, what each command does, troubleshooting recipes) so a new dev can follow it without prior k8s context.
6. Rewrite `backend/onyx/server/features/build/sandbox/README.md` as a kubernetes-only doc.
7. Point the root `README.md` and `CONTRIBUTING.md` at the kind path for Craft.

## Important Notes

### Codebase footprint (verified)

**Public contract is the abstract `SandboxManager`** at `backend/onyx/server/features/build/sandbox/base.py:62-542`. Both managers implement the same surface (`provision`, `setup_session_workspace`, `send_message`, `push_to_sandbox`, all file ops, snapshot ops). Removal touches only the `local/` package and the three call sites that branch on `SANDBOX_BACKEND == LOCAL`.

**The `local/` directory is fully self-contained.** Outside `backend/onyx/server/features/build/sandbox/local/`, the only importers are:
- `backend/onyx/server/features/build/sandbox/base.py:666` (factory)
- `backend/tests/external_dependency_unit/craft/conftest.py:54`
- `backend/tests/unit/onyx/server/features/build/test_path_sanitization.py:13`
- `backend/tests/unit/onyx/server/features/build/sandbox/test_sandbox_backend_selection.py:34`

So `agent_client.py`, `process_manager.py`, `try_agent_client.py`, and `local_sandbox_manager.py` get deleted as a directory.

**Three runtime branches need cleanup:**
- `backend/onyx/server/features/build/sandbox/base.py:648-688` — `get_sandbox_manager()` factory: drop the `LOCAL` branch.
- `backend/onyx/server/features/build/api/sessions_api.py:487` — `if SANDBOX_BACKEND != SandboxBackend.LOCAL:` wraps snapshot restoration; unwrap.
- `backend/onyx/server/features/build/sandbox/tasks/tasks.py:52-56` and `:200` — `cleanup_idle_sandboxes_task` early-returns on LOCAL; remove the guard and the commented-out block.

**Config cleanup** in `backend/onyx/server/features/build/configs.py`:
- Drop `SandboxBackend.LOCAL` enum (line 14).
- Default `SANDBOX_BACKEND` changes from `"local"` to `"kubernetes"` (line 23).
- Delete `SANDBOX_BASE_PATH`, `OUTPUTS_TEMPLATE_PATH`, `VENV_TEMPLATE_PATH`, `SANDBOX_TEMPLATE_MODE` (lines 37-45).
- Wrap env parsing so a raw `SANDBOX_BACKEND=local` raises a startup error with a doc pointer at `docs/dev/local-kubernetes.md`, rather than the bare `ValueError` from the enum constructor.

### Test coverage parity

Craft tests in `backend/tests/external_dependency_unit/craft/` split cleanly into two groups today, which makes the migration tractable.

**Group 1 — tests that already use `StubSandboxManager`** (the in-process test double at `backend/tests/common/craft/stubs.py`, re-exported via `craft/stubs.py`). Unaffected by this change.
- `test_sandbox_lifecycle.py` (uses both stub and `running_sandbox`)
- `test_session_lifecycle.py`
- `test_scheduled_task_executor.py`
- `test_idle_cleanup.py`, `test_sandbox_pat.py`, `test_snapshot_manager.py`, `test_snapshot_restore.py`, `test_streaming_persistence.py`, `test_company_search_skill.py`, `test_skill_visibility.py`, `test_skills_fileset.py` (stub-only or pure-DB)

These continue to run in `pr-external-dependency-unit-tests.yml` exactly as today. `StubSandboxManager` is a test-scoped fixture (lives under `backend/tests/`, never shipped), unrelated to LocalSandboxManager.

**Group 2 — tests that today bind the `running_sandbox` / `sandbox` fixture to a real `LocalSandboxManager` and assert real I/O.** These need migration:
- `test_local_sandbox_file_ops.py` — covers `TestHealthCheck`, `TestListDirectory`, `TestReadFile`, `TestDeleteFile`, `TestCreateSnapshot`, `TestTerminate`. **Delete and rewrite** against kind.
- `test_local_sandbox_upload.py` — covers `TestUploadFile`, `TestGetUploadStats`. **Delete and rewrite** against kind.
- `test_skill_push.py` — covers `push_skill_to_affected_sandboxes` and `hydrate_sandbox_skills` end-to-end (12+ tests including public/private skill flows, sleeping/terminated sandboxes, grant changes, bundle replacement, deletion, per-user rendering, template exclusion). Asserts real file contents land in the sandbox.
- `test_user_library_sync.py` — covers `hydrate_user_library` and `sync_user_library_to_active_sandboxes` (5 tests). Asserts real symlink + file behavior in the sandbox.
- `test_affected_users.py` — uses `running_sandbox` for affected-user resolution checks.

The migration approach for Group 2: rewrite the `sandbox` / `running_sandbox` fixtures in `conftest.py` to bind to a real `KubernetesSandboxManager` against the kind cluster instead of a `LocalSandboxManager`. Fixture scope likely needs to widen to `module` or `session` (today function-scoped, fine for local; pod provisioning takes ~20s so per-test provisioning would balloon CI time). Wherever a test mutates sandbox state in a way the next test would notice, use a fresh-session-id-per-test pattern on a shared pod, mirroring how `test_kubernetes_sandbox.py` already amortizes.

Test files keep their existing names — they no longer say "local" in their content. The handful of file-ops assertions that today peek at on-disk layout get rewritten against the public `SandboxManager` contract (round-trip via `upload_file` → `read_file`, etc.).

**Path-sanitization unit tests get deleted, not migrated.** `backend/tests/unit/onyx/server/features/build/test_path_sanitization.py` tests private helpers `_sanitize_path` / `_is_path_allowed` on `LocalSandboxManager`. The k8s manager doesn't have these helpers — sanitization happens server-side in the sandbox daemon. Equivalent coverage moves into negative-case file-ops tests on k8s (e.g. `read_file("../etc/passwd")` returns the right error from the daemon).

**Backend selection unit test.** `test_sandbox_backend_selection.py` becomes trivial — trim to cover `KUBERNETES` and `DOCKER`.

### CI workflow placement

Group 1 tests (StubSandboxManager-based) stay in `pr-external-dependency-unit-tests.yml`. Nothing changes for them.

Group 2 tests (real-sandbox-backed) need kind. Today kind is set up only in `.github/workflows/pr-craft-k8s-tests.yml`. Two options:

- **(a) Run the migrated Group 2 tests in `pr-craft-k8s-tests.yml`.** Recommended. Path filter at lines 16-27 already covers `backend/onyx/server/features/build/sandbox/**`; expanding the `py.test` invocation at line 235 to include the migrated files is a one-line change. CI runtime for that job grows (~Group 2 has roughly 30 tests; against a shared kind cluster and amortized pod provisioning, probably +5-10 min on top of today's ~10 min). Workflow timeout is 20 min today — may need to bump to 30 min.
- **(b) Add kind setup to `pr-external-dependency-unit-tests.yml` and keep Group 2 tests there.** Means every PR pays the kind-cluster bring-up cost (~3-5 min) even for completely unrelated changes. Not recommended.

The choice doesn't affect coverage — kind is kind, and the path filter in `pr-craft-k8s-tests.yml` already triggers on sandbox changes. Recommending (a) on CI-runtime grounds, but flagging that this is an optimization decision, not a coverage decision. If we change our minds later, moving tests between workflows is a path-filter edit, not a test rewrite.

### Existing tooling we are building on

- `deployment/helm/dev/k8s-up.sh` is already idempotent, refuses to operate against the wrong kubectl context, creates the `onyx-sandboxes` namespace, installs telepresence traffic-manager, and prints "next steps" pointing at the vscode launch profile.
- `.vscode/tasks.json` already exposes `k8s: cluster up`, `k8s: cluster down (full teardown)`, `k8s: pause cluster`, `k8s: resume cluster`, `k8s: telepresence connect`, `k8s: telepresence intercept api_server`, `k8s: telepresence quit`. The `intercept api_server` task is wired as a `preLaunchTask` on every `(k8s)` launch profile.
- `.github/workflows/pr-craft-k8s-tests.yml` already boots kind + a local image registry + builds the sandbox image + applies sandbox manifests + runs `test_kubernetes_sandbox.py`. Path filter already covers `backend/onyx/server/features/build/sandbox/**`, so adding more tests to that file lands in the same workflow with no CI changes.

What is **missing** today: a one-shot wrapper that combines `k8s-up.sh` + sandbox image build/load + `.env.k8s` bootstrap. This is the most-skipped step in `docs/dev/local-kubernetes.md` ("Skipping step 3 (the sandbox image) is the most common Craft setup failure"), so collapsing it into one command directly addresses the existing pain point.

### Tooling: `make craft-up`

There is no root `Makefile` today (verified — `ls Makefile` returns nothing). Two reasonable choices:

- **(a) Add a root `Makefile`** with a `craft-up` target (and stubs `craft-down`, `craft-sandbox-image` for the inner steps). Familiar entry point; easy to `make help` to discover.
- **(b) Add `deployment/helm/dev/craft-up.sh`** modelled on the existing `k8s-up.sh`. Consistent with the current pattern; no new file types.

Recommend **(b)**, because every other dev script in this repo is bash under `deployment/helm/dev/`, and the existing `k8s-up.sh` already has the idempotency / preflight / next-steps patterns we want to reuse. We get `make craft-up` ergonomics by adding a thin root `Makefile` that delegates to the script, so both work — `make craft-up` from anywhere in the tree, or the script directly with flags.

`deployment/helm/dev/craft-up.sh` does, in order:
1. `require docker kind kubectl helm` (mirrors `k8s-up.sh`'s preflight). Print install hints on missing.
2. Call `deployment/helm/dev/k8s-up.sh "$@"` — idempotent cluster bring-up, telepresence traffic-manager install, namespace setup.
3. Bootstrap `.vscode/.env.k8s` from template if missing: `[ -f .vscode/.env.k8s ] || cp .vscode/.env.k8s.template .vscode/.env.k8s`. Print a one-line "edit `<REPLACE THIS>` values" reminder. Do not overwrite an existing file.
4. Build the sandbox image and `kind load` it:
   ```
   docker build -t onyxdotapp/sandbox:dev \
     backend/onyx/server/features/build/sandbox/kubernetes/docker
   kind load docker-image onyxdotapp/sandbox:dev --name onyx-dev
   ```
   Skip the build if `--skip-sandbox-image` is passed (rebuild loop optimization), but always run the `kind load` so a previously-built image gets picked up by a fresh cluster.
5. Print "next steps": open vscode, run the **Run All Onyx Services (k8s)** launch profile.

Flags: `--cluster-name`, `--skip-cluster-create`, `--skip-helm`, `--skip-sandbox-image`, `-h/--help`. Passes through anything it doesn't consume to `k8s-up.sh`.

### Tooling: `make craft-down`

`make craft-up`'s symmetric teardown. Today `k8s-down.sh` only deletes the kind cluster — it leaves telepresence connected (host DNS routes intact, daemon still resident, listening on the loopback), and leaves the locally-built `onyxdotapp/sandbox:dev` image taking up disk. A fresh `make craft-up` after a partial teardown works, but the dangling telepresence state confuses `telepresence status` and the next `connect` can produce stale-route errors. `make craft-down` is a single command that returns the dev machine to the pre-`craft-up` state.

`deployment/helm/dev/craft-down.sh` does, in order:

1. Quit telepresence if running: `telepresence quit 2>/dev/null || true`. Idempotent — quit on a non-running daemon is a no-op. Skip silently if `telepresence` is not installed.
2. Call `deployment/helm/dev/k8s-down.sh "$@"` — uninstalls helm release and deletes the kind cluster (this is what `k8s-down.sh` does today). Inherits the context-safety guard there.
3. With `--remove-images` (off by default), `docker rmi onyxdotapp/sandbox:dev onyxdotapp/onyx-backend:dev 2>/dev/null || true`. Default-off because rebuilding from cache is fast and devs commonly cycle the cluster without wanting to re-pay the full image build.
4. Print "next steps": "Run `make craft-up` to bring it back. Your `.vscode/.env.k8s` was not touched."

**Never touches `.vscode/.env.k8s`** — it contains user-edited secrets (GEN_AI_API_KEY, etc.). Removing it would create a foot-gun on every teardown.

Flags: `--cluster-name`, `--keep-cluster` (pass-through to `k8s-down.sh` — uninstalls helm but preserves PVCs), `--remove-images`, `-h/--help`.

Root `Makefile` (new file) starts minimal:
```
.PHONY: craft-up craft-down craft-sandbox-image

craft-up:
	deployment/helm/dev/craft-up.sh

craft-down:
	deployment/helm/dev/craft-down.sh

craft-sandbox-image:
	docker build -t onyxdotapp/sandbox:dev backend/onyx/server/features/build/sandbox/kubernetes/docker
	kind load docker-image onyxdotapp/sandbox:dev --name onyx-dev
```

### Tooling: vscode task

Add to `.vscode/tasks.json` alongside the existing `k8s: *` tasks:

```json
{
  "label": "craft: up (cluster + sandbox image + .env.k8s)",
  "detail": "One-command Craft setup: kind cluster + Onyx helm install + sandbox image build/load + .env.k8s bootstrap. Idempotent.",
  "type": "shell",
  "command": "${workspaceFolder}/deployment/helm/dev/craft-up.sh",
  "options": { "cwd": "${workspaceFolder}" },
  "presentation": { "reveal": "always", "panel": "dedicated", "clear": true },
  "problemMatcher": []
},
{
  "label": "craft: down (teardown + telepresence quit)",
  "detail": "Symmetric teardown: telepresence quit + delete kind cluster. Does not touch .vscode/.env.k8s. Pass --remove-images to also remove locally-built sandbox/backend images.",
  "type": "shell",
  "command": "${workspaceFolder}/deployment/helm/dev/craft-down.sh",
  "options": { "cwd": "${workspaceFolder}" },
  "presentation": { "reveal": "always", "panel": "dedicated", "clear": true },
  "problemMatcher": []
},
{
  "label": "craft: rebuild sandbox image",
  "detail": "Rebuild onyxdotapp/sandbox:dev and load it into the kind node. Use after editing backend/onyx/server/features/build/sandbox/kubernetes/docker/.",
  "type": "shell",
  "command": "bash",
  "args": ["-c", "docker build -t onyxdotapp/sandbox:dev backend/onyx/server/features/build/sandbox/kubernetes/docker && kind load docker-image onyxdotapp/sandbox:dev --name onyx-dev"],
  "options": { "cwd": "${workspaceFolder}" },
  "presentation": { "reveal": "always", "panel": "dedicated", "clear": true },
  "problemMatcher": []
}
```

### Doc rewrites

**`docs/dev/local-kubernetes.md`** — expand with concrete operational detail. The current doc has good structure but is missing pieces a new dev hits:

1. Reframe "When you need this" (lines 6-13): drop the "use only for Craft" caveat. With `LocalSandboxManager` gone, this is the canonical setup for any Craft work; non-Craft work can still use the docker-compose path from `CONTRIBUTING.md`.
2. Add a **kubectl context** section after Prerequisites, before "One-time setup":
   - How to list contexts: `kubectl config get-contexts`.
   - How to check current: `kubectl config current-context`.
   - How to switch: `kubectl config use-context kind-onyx-dev`.
   - Why the scripts pin `--context kind-onyx-dev` everywhere (the `onyx` namespace also exists in prod EKS — pinning prevents catastrophic cross-cluster operations).
   - How to verify you're on the right cluster before running anything destructive: `kubectl config current-context # expect: kind-onyx-dev`.
3. Replace step 1 ("Bring up the cluster") with a `make craft-up` first-class path:
   - "Run **`make craft-up`** (or the **`craft: up`** vscode task) — handles cluster, helm install, sandbox image build/load, and `.env.k8s` bootstrap in one shot. Idempotent, safe to re-run."
   - Keep the existing step-by-step (k8s-up.sh, .env.k8s copy, sandbox image, telepresence) below as "What `craft-up` does", for transparency and for the rebuild loop (`make craft-sandbox-image`).
4. Add a **Common commands** subsection under "Daily workflow" with the recipes a new dev hits in their first week:
   - Watch pods: `kubectl -n onyx get pods -w`.
   - Tail logs from one pod: `kubectl -n onyx logs -f <pod>`.
   - Stream logs across all api_server replicas (the `stern` recipe used in production debugging).
   - Shell into the postgres DB: `kubectl -n onyx exec -it onyx-pg-1 -- psql -U postgres`.
   - Restart api_server after a chart edit: `kubectl -n onyx rollout restart deployment/onyx-api-server`.
   - Delete one sandbox pod (test a recovery path): `kubectl -n onyx-sandboxes delete pod <name>`.
   - Inspect cluster events: `kubectl -n onyx get events --sort-by=.lastTimestamp | tail -30`.
5. Expand "Troubleshooting" with the failure modes we already know:
   - Sandbox pods stuck in `ImagePullBackOff` — `onyxdotapp/sandbox:dev` is local-only; you didn't run step 3 (or `make craft-up`). Recovery: `make craft-sandbox-image`.
   - api_server can't resolve `onyx-pg-rw` — telepresence not connected. `telepresence status`, `telepresence connect -n onyx`.
   - `kubectl` operating against the wrong cluster (e.g. `docker-desktop`) — `kubectl config use-context kind-onyx-dev`, then verify with `kubectl config current-context`.
   - CNPG `unable to setup PKI infrastructure` (already documented; leave).
   - `onyx-sandboxes` namespace exists without Helm ownership (already documented; leave).

**`backend/onyx/server/features/build/sandbox/README.md`** — rewrite as kubernetes-only:
- Delete the "deployment modes" section (lines 18-40 — covered LOCAL/KUBERNETES/DOCKER).
- Delete local-only env vars (lines 213-224).
- Delete the local testing example (lines 290-295) and "Templates Not Found (Local Mode)" troubleshooting (lines 349-362).
- Add a "Local Development" section at the top pointing at `docs/dev/local-kubernetes.md` ("Craft requires a local kind cluster — see [Local Kubernetes Development](/docs/dev/local-kubernetes.md). One-shot setup: `make craft-up`.")

**Root `README.md`** — add a one-paragraph Craft pointer in the existing "Getting Started" or "Development" area: "Craft (Build) requires a local kind cluster. From a clean checkout: `make craft-up`. See [Local Kubernetes Development](/docs/dev/local-kubernetes.md) for the full workflow." (Need to read this file during implementation to pick the right insertion point.)

**`CONTRIBUTING.md`** — wherever it currently says "for Craft work, set `SANDBOX_BACKEND=local`", replace with "for Craft work, see `docs/dev/local-kubernetes.md`" and `make craft-up`. (Need to grep the file during implementation to find every reference.)

**Historical docs** in `docs/craft/legacy/sandbox-backends.md`, `docs/craft/infra/sandbox-file-push.md`, `docs/craft/opencode-serve-migration.md`, `docs/craft/features/search/4-craft-search.md`, `docs/craft/features/skills/builtin-skills-migration-plan.md`, `docs/craft/infra/sandbox-daemon-expansion.md` — leave content as-is (they describe historical migration work). Add a one-line note at the top of `legacy/sandbox-backends.md` only: "**Note: the local backend has been removed. See `docs/dev/local-kubernetes.md`.**"

## Implementation Strategy

Single PR, ordered so the tree compiles and tests pass at each step. Four chunks.

### Chunk 1 — migrate test coverage onto kind

Goes first so coverage never regresses at any commit boundary.

**1a. Port file-ops tests against the existing `kubernetes_sandbox` fixture.**
- Create `backend/tests/external_dependency_unit/craft/test_kubernetes_sandbox_file_ops.py`. Reuse the session/module-scoped `kubernetes_sandbox` fixture pattern from `test_kubernetes_sandbox.py`.
- Move the test classes from `test_local_sandbox_file_ops.py` (`TestHealthCheck`, `TestListDirectory`, `TestReadFile`, `TestDeleteFile`, `TestCreateSnapshot`, `TestTerminate`) and `test_local_sandbox_upload.py` (`TestUploadFile`, `TestGetUploadStats`) — rewriting each assertion to use the public `SandboxManager` API only (no on-disk inspection). Snapshot tests round-trip: `setup_session_workspace` → `upload_file` known content → `create_snapshot` → `cleanup_session_workspace` → `restore_snapshot` → `read_file` returns the original bytes.
- Add negative-path tests covering what `test_path_sanitization.py` was guarding: `read_file("../etc/passwd")` returns the right error from the daemon, etc.

**1b. Migrate the broader real-sandbox tests** (`test_skill_push.py`, `test_user_library_sync.py`, `test_affected_users.py`, parts of `test_sandbox_lifecycle.py`).
- In `conftest.py`, replace the LocalSandboxManager-backed `sandbox` / `running_sandbox` fixtures with a KubernetesSandboxManager-backed equivalent. Widen scope (`module` or `session`) and use fresh-session-id-per-test to amortize pod provisioning, mirroring `test_kubernetes_sandbox.py`'s pattern.
- No test bodies should need substantive changes — they call `running_sandbox()` and operate via the same `SandboxHandle` API.
- Group 1 stub-based tests (`test_session_lifecycle.py`, `test_scheduled_task_executor.py`, etc.) need no changes — they go through `stub_sandbox_manager`, untouched.

**1c. Wire CI.**
- Expand path filter in `.github/workflows/pr-craft-k8s-tests.yml:16-27` to cover the migrated test files.
- Expand the `py.test` invocation at line 235 to include `test_kubernetes_sandbox_file_ops.py`, `test_skill_push.py`, `test_user_library_sync.py`, `test_affected_users.py`, `test_sandbox_lifecycle.py`.
- Bump the workflow `timeout-minutes` from 20 to 30 if the new test load pushes runtime past ~15 min.
- Remove the migrated tests from whatever job runs them in `pr-external-dependency-unit-tests.yml` (likely a directory glob — they'll get picked up automatically as deleted in Chunk 3, but adjust here if the workflow uses a hard list).

Keep the existing local test files passing through this chunk — both suites run side-by-side until Chunk 3. Commit: `feat(craft): migrate real-sandbox craft tests onto kind`.

### Chunk 2 — tooling + docs that push devs onto kind

- Create `deployment/helm/dev/craft-up.sh` per the spec under "Tooling: `make craft-up`" above. Mirror `k8s-up.sh`'s flag-parsing and `require` preflight patterns.
- Create `deployment/helm/dev/craft-down.sh` per the spec under "Tooling: `make craft-down`" above. Mirror `k8s-down.sh`'s context-safety guard (inherited via the call into it).
- Create root `Makefile` with `craft-up`, `craft-down`, `craft-sandbox-image` targets.
- Add `craft: up`, `craft: down`, and `craft: rebuild sandbox image` tasks to `.vscode/tasks.json`.
- Rewrite `backend/onyx/server/features/build/sandbox/README.md` as kubernetes-only.
- Expand `docs/dev/local-kubernetes.md` with the kubectl context section, common commands section, expanded troubleshooting, and `make craft-up` as the headline path.
- Update root `README.md` with the Craft-dev pointer paragraph.
- Update `CONTRIBUTING.md` to point at `docs/dev/local-kubernetes.md` + `make craft-up` for Craft work.
- Add the one-line banner to `docs/craft/legacy/sandbox-backends.md`.
- Commit: `docs(craft): make-kind setup, expanded local-k8s docs, kubernetes-only sandbox README`.

### Chunk 3 — delete the local backend

After Chunks 1 and 2 are in, one focused commit:

- Delete directory `backend/onyx/server/features/build/sandbox/local/` (all four files).
- `backend/onyx/server/features/build/sandbox/base.py:648-688` — remove the `LOCAL` branch from `get_sandbox_manager()`. Result: factory only branches between `KUBERNETES` and `DOCKER`.
- `backend/onyx/server/features/build/configs.py` — drop `SandboxBackend.LOCAL`, change `SANDBOX_BACKEND` default to `KUBERNETES`, remove the four local-only env vars. Wrap the enum parse so a raw `"local"` value raises a startup error with a doc pointer.
- `backend/onyx/server/features/build/api/sessions_api.py:487` — unwrap the `if SANDBOX_BACKEND != SandboxBackend.LOCAL:` guard.
- `backend/onyx/server/features/build/sandbox/tasks/tasks.py:52-56` and `:200` — remove the `LOCAL` early-return and the commented-out local block.
- Delete `backend/tests/external_dependency_unit/craft/test_local_sandbox_file_ops.py`, `test_local_sandbox_upload.py`.
- Delete `backend/tests/unit/onyx/server/features/build/test_path_sanitization.py`.
- Edit `backend/tests/external_dependency_unit/craft/conftest.py` to drop the LocalSandboxManager fixture, the singleton-reset code, and the `SANDBOX_BASE_PATH` monkeypatch (~150 lines).
- Trim `backend/tests/unit/onyx/server/features/build/sandbox/test_sandbox_backend_selection.py` to cover only `KUBERNETES` and `DOCKER`.
- `grep -r "LocalSandboxManager\|SandboxBackend\.LOCAL\|SANDBOX_BASE_PATH\|OUTPUTS_TEMPLATE_PATH\|VENV_TEMPLATE_PATH\|SANDBOX_TEMPLATE_MODE" backend/ web/ docs/ deployment/` and clean up any stragglers.
- Commit: `refactor(craft): delete LocalSandboxManager and local sandbox backend`.

### Chunk 4 — verify

See **Verification** section below.

## Verification

End-to-end checks before merging:

1. **Static checks pass.**
   - `pre-commit run --all-files` is clean (formatters, ruff, mypy).
   - `grep -r "LocalSandboxManager\|SandboxBackend\.LOCAL" backend/ web/ docs/` returns zero hits.

2. **Unit tests pass without the LOCAL path.**
   ```
   uv run pytest backend/tests/unit -xv
   ```
   `test_sandbox_backend_selection.py` covers `KUBERNETES` and `DOCKER` only; `test_path_sanitization.py` is gone.

3. **All real-sandbox craft tests pass against a real kind cluster.**
   ```
   make craft-up
   uv run python -m dotenv -f .vscode/.env run -- pytest \
     backend/tests/external_dependency_unit/craft/test_kubernetes_sandbox.py \
     backend/tests/external_dependency_unit/craft/test_kubernetes_sandbox_file_ops.py \
     backend/tests/external_dependency_unit/craft/test_skill_push.py \
     backend/tests/external_dependency_unit/craft/test_user_library_sync.py \
     backend/tests/external_dependency_unit/craft/test_affected_users.py \
     backend/tests/external_dependency_unit/craft/test_sandbox_lifecycle.py \
     -xv
   ```
   All migrated tests pass. New negative-path tests assert the right daemon error codes. Stub-based tests still pass via the unchanged external-dep workflow path.

4. **One-shot setup works on a clean checkout.**
   - `kind delete cluster --name onyx-dev` (clean slate).
   - `rm .vscode/.env.k8s` (if it exists).
   - `make craft-up` — succeeds end-to-end, prints next steps, leaves `.vscode/.env.k8s` populated from template.
   - Re-run `make craft-up` — idempotent, no errors.

5. **vscode tasks work.**
   - Cmd+Shift+P → "Tasks: Run Task" → `craft: up` — runs to completion.
   - `craft: rebuild sandbox image` — rebuilds and re-loads cleanly.
   - `craft: down` — quits telepresence and deletes the cluster; `.vscode/.env.k8s` survives.

6. **`make craft-down` is symmetric.**
   - With telepresence connected and the cluster running: `make craft-down` quits telepresence (`telepresence status` → "Not connected") and deletes the cluster (`kind get clusters` no longer lists `onyx-dev`).
   - `.vscode/.env.k8s` is still present afterwards.
   - `make craft-up` immediately after returns the dev machine to a working state.

7. **Stale `SANDBOX_BACKEND=local` fails fast.**
   - Set `SANDBOX_BACKEND=local` in `.vscode/.env.k8s` and boot api_server.
   - Expected: startup error mentioning `docs/dev/local-kubernetes.md`, not a generic `ValueError`.

8. **End-to-end Craft session works.**
   - In vscode: **Run All Onyx Services (k8s)** launch profile.
   - Open `http://localhost:3000`, log in as `a@example.com` / `a`.
   - Create a Build session, send a message, verify ACP events stream back.
   - In the sandbox session: upload a file, list directory, read it back, delete it, take a snapshot, restore from snapshot — every file op exercises the kubernetes manager.

9. **CI signal.**
   - `pr-craft-k8s-tests.yml` job goes green on the PR; runtime increases by the file-ops migration (+~2-3 min, well under the 20-min timeout).
   - Generic `pr-external-dependency-unit-tests.yml` no longer runs the deleted local tests (directory globs pick up the deletion automatically).
