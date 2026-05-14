> **Archived.** Superseded by the S3-mounted-bucket delivery model described in `../skills-requirements.md` §5. The push-pipeline / tarball / kubectl-exec abstraction designed here is no longer the direction for skill delivery to sandboxes. Kept for historical context only — do not use as an implementation reference.

# Sandbox File Sync — Generic Bundle Abstraction

**Status**: design · **Owner**: Roshan · **Date**: 2026-05-12

A reusable abstraction for pushing files from S3 (or the database) into one or more Craft sandbox pods. Skills, user_library, and future admin-uploaded org-wide files all flow through the same machinery. Replaces the `file-sync` sidecar and supersedes the bespoke push pipeline in `skills_plan.md` §9.7.

## Issues to Address

1. **The `file-sync` sidecar is going away.** `user_library` currently relies on a per-pod `s5cmd sync` sidecar triggered by `kubectl exec`. Without it there is no path for files in S3 to reach sandbox pods.
2. **Skills, user_library, and org-wide admin files all reinvent the same plumbing.** Each feature would otherwise grow its own tarball endpoint, targeting logic, Celery fan-out, and in-pod refresh script. `skills_plan.md` §9.7 already designed one such pipeline; without an abstraction the next two consumers copy it.
3. **No shared event hook.** Feature mutations (skill upload, doc index complete, admin file upload) have no shared API for saying "the bundle changed, get it to the pods."

## Important Notes

- **Single delivery shape.** Each consumer's payload is delivered as a tarball materialized on demand by the api_server. No incremental/delta path in v1. Sources of files (admin-uploaded zips, individual file uploads, indexed docs) are normalized at the ingest boundary, not the delivery boundary.
- **Push + lifecycle triggers, no polling.** Mutations enqueue an immediate push via Celery → kubectl exec. The ~5% push-failure tail (overwhelmingly kubectl-exec into not-Ready pods) is recovered on the next lifecycle transition: session setup, session wakeup (snapshot restore), or a manual "refresh sandbox" button. No background cron in the pod.
- **`If-Modified-Since` makes every refresh cheap.** Each bundle exposes `last_modified()` (an indexed `MAX(updated_at)` query). The tarball endpoint returns `304` when nothing changed, so duplicate or no-op refreshes (a push that arrives after a manual refresh, a wakeup after a clean shutdown, etc.) cost one DB query.
- **Two architectural assumptions.** (a) Each user has at most one active sandbox, so user-scoped bundles have no fan-out within a scope. (b) Sandbox pods and the api_server / S3 live in the same region, so intra-region egress is free on AWS and isn't a cost driver.
- **Full deployments only — Onyx Craft is not supported on Lite.** The push pipeline (`enqueue_change` → `propagate_bundle_change` → `refresh_pod_bundle`) requires Redis (for the write-through cache and Celery broker) and an active Celery worker pool. Lite deployments ship without those, and they also ship without Craft sandbox infrastructure — there is nothing on a Lite deployment for this pipeline to talk to. No guard or feature-flag branch is needed in `enqueue_change`: the skills admin endpoints, sandbox manager, and bundle pipeline are all part of the Craft surface, which is full-deployment-only. Same scoping rule that already governs `skills_plan.md` §9.7 and the §16 orphan-cleanup beat task.
- **Builds on the K8s label work from `skills_plan.md` §9.7.** `onyx.app/tenant-id` and `onyx.app/sandbox-id` already planned there are all the labels v1 needs. No new pod labels.
- **Per-bundle ingest is each feature's problem; source storage reuses existing primitives.** Skills accepts a zip and stores it as a single blob in **OnyxFileStore** (`FileOrigin.SKILL_BUNDLE`, one per custom skill; built-ins stay on-disk in the repo). user_library reads from the existing indexed-document storage that the indexing pipeline already populates. No new S3 bucket, no new IAM. The abstraction only governs delivery from source → pod.

## Distribution Model

The cost structure breaks into three pieces, each handled the simplest way that works at v1 scale:

| Cost component | v1 answer |
|---|---|
| **Materialization** (DB queries + S3 reads + tar packing) | None. Skills bundles are KBs–single MBs and materialize in milliseconds; user_library has no fan-out (1 sandbox per user). Even tenant fan-out for skills is small enough that N×materialize is trivial. |
| **Network egress** (api_server → pod) | None. Same-region AWS makes intra-cluster transfer free. |
| **In-pod work** (extract + atomic swap) | Unavoidable, one pod, one extract. Fine at our scale. |

### Why not a shared ReadOnlyMany volume per tenant?

That's the textbook k8s answer for shared content (one EFS/Filestore filesystem, mounted RO by every sandbox pod). It's strictly more efficient: one materialization, no per-pod transfer, instant visibility on the pod. We're deferring it because:

- v1 bundles are small (skills: KBs–MBs) or per-user (user_library: 1 sandbox per user, no fan-out to optimize).
- EFS/Filestore adds real infrastructure: provisioning, mount targets per AZ, mount-failure modes at pod boot, per-GB-month cost.
- The bundle interface tolerates a transport swap later. Bundle authors write `materialize()`; the transport between `materialize()` and the pod's mount path is internal. If `OrgFilesBundle` (admin-uploaded org-wide files — picture multi-GB policy archives) lands and tenant-fan-out costs become measurable, we promote tenant-scoped bundles to a shared-volume transport without changing any bundle implementation.

### Refresh triggers

A pod runs `/usr/local/bin/refresh-bundle <key>` in exactly four situations:

| Trigger | How it's invoked |
|---|---|
| **Mutation push** (admin uploads skill, user uploads doc) | Celery task `refresh_pod_bundle` kubectl-execs the script |
| **Session setup** (new sandbox pod boots) | Pod's entrypoint runs the script for each registered bundle before starting the agent |
| **Session wakeup** (snapshot restored into a fresh pod) | Same entrypoint path — a restored pod is still "freshly booted" from its own perspective; the s5cmd-restored snapshot reflects pre-suspension session state, then bundles refresh against the *current* server state on top of it |
| **Manual refresh button** | `POST /api/sandbox/{sid}/refresh` → server kubectl-execs the script for each registered bundle on that one pod |

Push covers the happy path. The three lifecycle triggers cover the failure tail: any pod about to do real work (run an agent turn, resume from snapshot, respond to a user click) refreshes first, so stale state never persists across a transition that the user cares about.

## Implementation Strategy

### Bundle interface

A small ABC under `backend/onyx/sandbox_sync/bundle.py`. Each consumer provides one implementation.

```python
class SandboxBundle(ABC):
    bundle_key: ClassVar[str]                    # "skills" | "user_library" | "org_files"
    mount_path: ClassVar[str]                    # in-pod absolute path
    cache_on_mutation: ClassVar[bool] = False    # write-through tarball cache (see below)

    @abstractmethod
    def materialize(self, db: Session, ctx: SandboxContext) -> Iterator[BundleEntry]: ...

    @abstractmethod
    def pod_label_selector(self, tenant_id: str, user_id: str | None) -> str: ...

    @abstractmethod
    def last_modified(self, db: Session, ctx: SandboxContext) -> datetime: ...
```

- `BundleEntry` is `(rel_path, content_stream, mode)` — lazy, so materializing a large bundle doesn't load every file into memory.
- `SandboxContext` carries `tenant_id`, `sandbox_id`, and `user_id` (resolved at request time from the sandbox row). Bundles read what they need.
- `pod_label_selector(tenant_id, user_id)` returns a K8s label selector string. Skills ignores `user_id` and returns `onyx.app/tenant-id={tenant}`. user_library returns the same selector — server filters per-sandbox by `user_id` at materialize time, so no extra label is needed.
- `last_modified` returns the max source-row timestamp under this scope — used by the tarball endpoint for `If-Modified-Since`.
- `cache_on_mutation` opts the bundle into write-through tarball caching. Default `False`. Bundles that fan out across many pods (skills) set it to `True`; per-user bundles (user_library) leave it off since there's nothing to amortize. See the "Write-through tarball cache" section.

Registration happens at import time in `backend/onyx/sandbox_sync/bundles/__init__.py`:

```python
BundleRegistry.register(SkillsBundle())
BundleRegistry.register(UserLibraryBundle())
```

### Mutation → push flow

```
[ event site ]                          [ Celery worker ]                       [ pod ]
enqueue_change(t, b, [u])  ───────────► propagate_bundle_change(t, b, [u])
                                         │ resolve pods via
                                         │ bundle.pod_label_selector(t, u)
                                         ▼
                                         fan-out refresh_pod_bundle(pod, b)
                                         ───────────────────────────────────►  /usr/local/bin/refresh-bundle <key>
                                                                                ├ flock
                                                                                ├ curl tarball-endpoint (If-Modified-Since)
                                                                                ├ 304 → exit; 200 → extract to sibling dir
                                                                                ├ atomic mv-swap mount_path
                                                                                └ write /var/lib/sandbox/<key>.last-modified
```

- **`enqueue_change(tenant_id, bundle_key, user_id=None)`** lives in `backend/onyx/sandbox_sync/enqueue.py`. Just enqueues `propagate_bundle_change.apply_async(args=..., expires=60)`. No debounce: bursts are absorbed by the pod's flock and 304 short-circuit.
- **`propagate_bundle_change(tenant_id, bundle_key, user_id=None)`** (Celery, in `backend/onyx/background/celery/tasks/sandbox_sync/propagate.py`):
  - Calls `core_v1.list_namespaced_pod(namespace=NS, label_selector=bundle.pod_label_selector(tenant_id, user_id))`.
  - Fans out `refresh_pod_bundle.delay(pod_name, bundle_key)` per pod. `expires=60`.
- **`refresh_pod_bundle(pod_name, bundle_key)`** (Celery, in `.../refresh.py`): single `kubectl exec` invoking `/usr/local/bin/refresh-bundle <bundle_key>`. Non-zero exit logged; the next lifecycle trigger reconciles. `expires=120`. The manual refresh endpoint reuses this exact path (it just invokes the script for a known pod, skipping the `propagate` fan-out).

### In-pod refresh

Single script `backend/onyx/server/features/build/sandbox/kubernetes/docker/refresh-bundle`, installed at `/usr/local/bin/refresh-bundle`. The script knows each bundle's mount path via a small hardcoded case statement (bundles are registered at compile time; new bundles ship with an image rebuild anyway):

```bash
refresh-bundle <bundle_key>
  case "$1" in
    skills)        MOUNT=/skills ;;
    user_library)  MOUNT=/workspace/files/user_library ;;
  esac

  flock /var/lock/bundle-$1.lock
  curl -fS -H "Authorization: Bearer $(cat /var/run/sandbox-token)" \
       -H "If-Modified-Since: $(cat /var/lib/sandbox/$1.last-modified 2>/dev/null)" \
       "$API_URL/api/internal/sandbox/$SANDBOX_ID/bundles/$1/tarball" \
       -D /tmp/$1.headers -o /tmp/$1.tar -w '%{http_code}'
  if 304 → exit 0
  mkdir /tmp/$1.new && tar -x -C /tmp/$1.new -f /tmp/$1.tar
  mv $MOUNT $MOUNT.old.$$ && mv /tmp/$1.new $MOUNT && rm -rf $MOUNT.old.* /tmp/$1.*
  grep -i ^Last-Modified /tmp/$1.headers > /var/lib/sandbox/$1.last-modified
```

**Pod entrypoint** runs the script once per registered bundle before the agent starts. The same entrypoint runs whether the pod is fresh or restored from snapshot — a restored pod is freshly booted from its own perspective, so this single code path covers both session setup and session wakeup:

```bash
# in the sandbox container entrypoint, before exec'ing the agent
for key in skills user_library; do
  refresh-bundle "$key" || echo "warning: initial $key refresh failed"
done
exec /usr/local/bin/agent ...
```

If a bundle refresh fails at boot, the pod still starts — the agent gets an empty mount path for that bundle and the next manual refresh / mutation push reconciles. We do not block sandbox provisioning on the api_server being healthy.

### Tarball endpoint

`GET /api/internal/sandbox/{sandbox_id}/bundles/{bundle_key}/tarball` in `backend/onyx/server/internal/sandbox_bundles.py`:

- Auth: existing sandbox bearer token (the same one already used by `skills_plan.md` §9.7's `/skills-tarball`).
- Resolves `tenant_id`, `user_id` from the sandbox row → `SandboxContext`.
- Computes `last_modified = bundle.last_modified(db, ctx)`.
- If `If-Modified-Since` ≥ `last_modified` → `304 Not Modified`. (~one indexed DB query, no S3, no tarring.)
- Else streams `tar(bundle.materialize(db, ctx))` with `Last-Modified` header set.

**Cache lookup before materialize.** If the bundle's `cache_on_mutation` is `True`, the endpoint first tries `redis.get("bundle:tar:{tenant}:{bundle_key}:{last_modified_iso}")` and streams those bytes when present. Miss → fall through to live materialize (this is the failure mode if the write-through wasn't durable; the response is still correct, just N-way racy on bursts).

### Write-through tarball cache

For bundles with `cache_on_mutation = True`, the **mutation site** populates the cache before enqueuing propagation. This eliminates the thundering herd on tenant fan-out:

```python
# in the mutation handler, after writing to DB + S3:
bundle_sync.enqueue_change(db, tenant_id, "skills")

# enqueue_change internally:
def enqueue_change(db, tenant_id, bundle_key, user_id=None):
    bundle = BundleRegistry.get(bundle_key)
    if bundle.cache_on_mutation:
        ctx = SandboxContext(tenant_id=tenant_id, user_id=user_id)
        last_modified = bundle.last_modified(db, ctx)
        tarball = b"".join(tar_stream(bundle.materialize(db, ctx)))
        redis.set(
            f"bundle:tar:{tenant_id}:{bundle_key}:{last_modified.isoformat()}",
            tarball,
            ex=15 * 60,
        )
    propagate_bundle_change.apply_async(args=(tenant_id, bundle_key, user_id), expires=60)
```

**Ordering guarantee:** the cache is populated *before* `propagate_bundle_change` is enqueued. By the time any pod curls the tarball endpoint, the cache key exists. N pods on the same change → 1 materialization (at the mutation site) + N cache reads. No race, no singleflight machinery.

**Failure modes:**
- Redis write fails → log warning, continue. Propagation still fires; pods fall back to live materialize on miss (the original lazy path, with its N-way race, but only on this one mutation).
- Mutation handler crashes between DB commit and `enqueue_change` → manual refresh / next lifecycle event reconciles.
- Cache TTL expires (15 min) before all pods have refreshed → pods on the next push fall back to live materialize, which is correct just less optimal.

**Why per-bundle, not always-on:** user_library has no fan-out within a user (1 sandbox/user), so write-through adds work without benefit. The flag keeps the optimization scoped to bundles that actually benefit.

**Operational notes:**
- Cache keys live under a single prefix `bundle:tar:` so they can be flushed independently of other Redis state.
- 15-min TTL bounds memory footprint; each `last_modified` advance retires the prior key naturally.
- A metric `bundle_tarball_cache_hit_total{bundle_key}` / `_miss_total{bundle_key}` surfaces whether the cache is earning its keep. Skills should run near 100% hit ratio after the first request post-mutation.

### Manual refresh endpoint

`POST /api/sandbox/{sandbox_id}/refresh` in `backend/onyx/server/features/build/sandbox/router.py` (or wherever the existing sandbox-control endpoints live):

- Auth: standard user session — caller must own (or be admin of) the sandbox.
- Resolves `sandbox_id` → pod name via the sandbox row.
- For each registered bundle, invokes the same per-pod refresh used by push: `refresh_pod_bundle.delay(pod_name, bundle_key)` (or a sync kubectl-exec, depending on what feels right at implementation time — a few seconds is fine for a user-clicked button).
- Returns 200 once all refreshes complete (or 202 + a status endpoint if we go async).

The frontend wires this to a "Refresh sandbox" button in the Craft UI's sandbox menu — placed near other sandbox-control actions (restart, suspend) rather than as a primary action.

### v1 bundle implementations

**`SkillsBundle`** (`backend/onyx/sandbox_sync/bundles/skills.py`):

- `cache_on_mutation = True` — tenant fan-out benefits from write-through caching.
- `materialize`:
  - Walks built-in skills on disk (`docker/skills/` in the Onyx repo) and yields each file as a `BundleEntry`.
  - For each custom skill row, reads its zip blob from FileStore via `file_store.read_file(skill.bundle_file_id)`, iterates the zip members in-memory, and yields each member as a `BundleEntry` under `{skill_slug}/`. No on-disk unpack — the zip is streamed straight into the output tar.
  - Applies template rendering for built-ins that declare a template. Replaces the rendering/discovery work currently in `skills_plan.md` §9.
- `pod_label_selector(tenant_id, _)`: `onyx.app/tenant-id={tenant_id}`.
- `last_modified`: `SELECT MAX(updated_at) FROM skill WHERE tenant_id=...`.

**Skill upload handler** (`backend/onyx/server/admin/skills/api.py`, per `skills_plan.md` §3): on `POST /api/admin/skills/upload`, the handler validates the zip, calls `file_store.save_file(zip_bytes, display_name=skill_name, file_origin=FileOrigin.SKILL_BUNDLE, file_type="application/zip")` → receives a `file_id`, writes the `skill` row with `bundle_file_id=file_id`, then calls `enqueue_change(db, tenant_id, "skills")`. Tenant isolation is automatic via FileStore's `get_current_tenant_id()`.

**`UserLibraryBundle`** (`backend/onyx/sandbox_sync/bundles/user_library.py`):

- `cache_on_mutation = False` (default) — no fan-out within a user (1 sandbox/user), so write-through adds work without benefit.
- `materialize`: lists enabled docs for the user from Postgres (`Document` table, filtering `sync_disabled`), streams each from its existing storage location (the path the indexing pipeline already writes to — not FileStore; user_library predates that primitive and uses its own layout). The bundle interface doesn't care which storage source the bytes come from.
- `pod_label_selector(tenant_id, user_id)`: `onyx.app/tenant-id={tenant_id}`. (Server filters per-sandbox by `user_id` at materialize time; no `onyx.app/user-id` label needed since the tarball endpoint resolves user from the sandbox row.)
- `last_modified`: `SELECT MAX(updated_at) FROM document WHERE user_id=...`. **Important:** do **not** filter by `sync_disabled=false` here even though `materialize` does. A disable event bumps the row's `updated_at` (SQLAlchemy `onupdate=func.now()`), and `last_modified` needs to see that bump so the pod re-fetches and the materialize call drops the now-disabled doc. Filtering by `sync_disabled` here would hide every event that *removes* a doc from the materialized set, returning a stale 304 and leaving the disabled doc in the pod's tarball. Same hazard applies to any future flag that affects materialization. **Invariant:** every mutation that affects `materialize`'s output must touch the row's `updated_at`; hard-delete (no row left to bump) is out of scope for v1 — if it lands, add a `user_library_state.last_modified` ticker bumped by an app-level helper on every mutation.

### Wiring at event sites

- Skills admin mutations (in `backend/onyx/server/admin/skills/*.py`): call `enqueue_change(tenant_id, "skills")` after successful commit.
- User library doc indexing: at the existing `sync_sandbox_files` call site (or its replacement), call `enqueue_change(tenant_id, "user_library", user_id=user_id)` after successful index.

Both replace bespoke push calls; no other changes to those handlers.

### Relationship to `skills_plan.md` §9.7

`skills_plan.md` §9.7 currently specifies `propagate_skill_change` + `refresh_pod_skills` + `/skills-tarball` + `refresh-skills` script. This design supersedes that section: skills becomes the first consumer of the generic bundle pipeline. The skills plan needs a small follow-up to point §9.7 at this abstraction; the in-pod paths described here are compatible with what skills_plan already calls for.

### What we are explicitly **not** doing in v1

- **No content_hash, no bundle-version table, no monotonic counter.** `If-Modified-Since` over `MAX(updated_at)` is sufficient.
- **No Redis debounce in `enqueue_change`.** Bursts are rare in practice; when they happen, the pod's flock + 304 short-circuit absorb them with a few seconds of busy work.
- **Tarball cache is scoped, not global.** Only bundles that fan out across many pods opt in via `cache_on_mutation = True` (skills). Per-user bundles (user_library) skip it — there's nothing to amortize across, and write-through would just add a Redis round-trip per upload.
- **No ConfigMap-driven bundle discovery on the pod.** The bundle list is hardcoded in `refresh-bundle` and the pod entrypoint. Adding `OrgFilesBundle` is a code + image-rebuild change anyway.
- **No delta / incremental push.** Full tarball every time. user_library at scale is fine because of the 304 short-circuit; if a real bundle gets large enough to hurt, add `materialize_delta` then.
- **No background polling cron in the pod.** Push covers the happy path; session setup, session wakeup, and manual refresh cover the ~5% push-failure tail. A pod doing nothing isn't checking for updates — when it next does anything user-visible, it refreshes first.
- **No `onyx.app/user-id` pod label.** Server resolves user from the sandbox row.
- **No ReadOnlyMany / shared-volume transport.** Direct curl is sufficient given v1 bundle sizes, 1-sandbox-per-user, and intra-region pod placement. Upgrade path exists if `OrgFilesBundle` or scale forces it.
- **No new S3 bucket, no new IAM, no new storage primitive.** Custom skill blobs ride on the existing **OnyxFileStore** (`FileOrigin.SKILL_BUNDLE`, tenant-isolated automatically via FileStore's key-prefix scheme). user_library reads from the existing indexed-document storage. Built-in skills stay on-disk in the Onyx repo. The bundle abstraction is storage-agnostic — `materialize()` is opaque, so each bundle reads from whatever its source-of-truth already is.
- **No bundle author UI / marketplace / org_files endpoint.** The interface is ready for `OrgFilesBundle` but no consumer is shipping in v1.

## Tests

The dominant test type for this work is **integration**: a real Postgres + Redis + Celery + k8s pod, mutation → enqueue → pod state. The interface is small enough that a few **external dependency unit tests** cover the bundle implementations themselves.

### External dependency unit tests (`backend/tests/external_dependency_unit/sandbox_sync/`)

- `test_skills_bundle.py` — materialize a SkillsBundle against a real DB + FileStore; assert correct file set, template rendering, `last_modified` returns expected timestamp.
- `test_user_library_bundle.py` — materialize against a real DB + S3 (MinIO); assert `sync_disabled` files excluded, `last_modified` reflects most recent doc update.

### Integration tests (`backend/tests/integration/tests/sandbox_sync/`)

- `test_push_path.py` — provision a sandbox, mutate a skill, assert the pod's `/skills/` reflects the change within ~5s. Verify the kubectl exec actually happened (check propagate + refresh task logs).
- `test_boot_refresh.py` — provision a sandbox with skills already present in the DB; before any push fires, assert the pod's `/skills/` contains them. Confirms the entrypoint refresh runs.
- `test_wakeup_refresh.py` — suspend a sandbox, mutate skills while suspended, resume the sandbox from snapshot. Assert the resumed pod sees the post-mutation skills (entrypoint refresh on the restored pod reconciles against current server state).
- `test_manual_refresh_recovers_from_push_miss.py` — provision a sandbox, mutate a skill, simulate kubectl-exec failure (block the API or kill the refresh worker mid-task). Call `POST /api/sandbox/{sid}/refresh`. Assert the pod now reflects the mutation.
- `test_304_short_circuit.py` — mutate nothing between two refreshes (any trigger), assert tarball endpoint returns 304 and pod state is untouched.
- `test_user_library_per_user_isolation.py` — two users, two sandboxes; mutate user A's library; assert user A's pod gets the new file and user B's pod does not.
- `test_user_library_disable_invalidates_cache.py` — regression test for the "removal events go missing" bug. Seed two docs for a user, provision a sandbox, let it pull the tarball (records `If-Modified-Since`). Disable one doc (`sync_disabled = True`). Trigger a refresh. Assert the tarball endpoint returns 200 (not 304) AND the pod's `user_library/` no longer contains the disabled doc. This guards the invariant that `last_modified` is not filtered by `sync_disabled` — if someone re-adds that filter "to optimize," this test fails.
- `test_skills_writethrough_cache.py` — provision two sandboxes in the same tenant, instrument `SkillsBundle.materialize` with a call counter, upload a skill. After all pods finish refreshing, assert `materialize` ran exactly once (the upload-time call) and that subsequent pod tarball requests hit the Redis cache.

### Unit tests

None planned; the components are thin and have no isolated business logic worth mocking out.

## Files Touched / Added

```
backend/onyx/sandbox_sync/                                          NEW
├── bundle.py                  # SandboxBundle ABC, BundleEntry, SandboxContext
├── registry.py                # BundleRegistry
├── enqueue.py                 # enqueue_change() — calls cache.materialize_and_store if bundle opts in
├── tarball.py                 # streaming tar builder over BundleEntry iterator
├── cache.py                   # Redis-backed tarball cache (get / materialize_and_store)
└── bundles/
    ├── __init__.py            # registers bundles at import time
    ├── skills.py              # SkillsBundle
    └── user_library.py        # UserLibraryBundle

backend/onyx/background/celery/tasks/sandbox_sync/                  NEW
├── propagate.py               # propagate_bundle_change, expires=60
└── refresh.py                 # refresh_pod_bundle, expires=120

backend/onyx/server/internal/sandbox_bundles.py                     NEW
└── GET /api/internal/sandbox/{sid}/bundles/{key}/tarball

backend/onyx/server/features/build/sandbox/router.py                +POST /api/sandbox/{sid}/refresh

backend/onyx/server/features/build/sandbox/kubernetes/
├── docker/refresh-bundle                                            NEW (in-pod script)
├── docker/entrypoint.sh                                             +refresh-bundle loop before exec'ing agent
└── kubernetes_sandbox_manager.py                                    -file-sync sidecar

# Frontend:
web/src/app/craft/...                                                +Refresh sandbox button in sandbox menu

# Wiring (small, per existing handler):
backend/onyx/server/admin/skills/*.py                                +enqueue_change(... "skills")
backend/onyx/server/user_files/*.py (or current sync call site)      +enqueue_change(... "user_library", user_id=...)

# Doc updates:
docs/craft/features/skills/skills_plan.md                            §9.7 points at this abstraction
```

No alembic migration. No new pod labels. The one new Redis usage is the write-through tarball cache under the `bundle:tar:` prefix — scoped, TTL-bounded, opt-in per bundle.
