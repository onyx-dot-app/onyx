# Sandbox File Sync — Generic Bundle Abstraction

**Status**: design · **Owner**: Roshan · **Date**: 2026-05-12

A reusable abstraction for pushing files from S3 (or the database) into one or more Craft sandbox pods. Skills, user_library, and future admin-uploaded org-wide files all flow through the same machinery. Replaces the `file-sync` sidecar and supersedes the bespoke push pipeline in `skills_plan.md` §9.7.

## Issues to Address

1. **The `file-sync` sidecar is going away.** `user_library` currently relies on a per-pod `s5cmd sync` sidecar triggered by `kubectl exec`. Without it there is no path for files in S3 to reach sandbox pods.
2. **Skills, user_library, and org-wide admin files all reinvent the same plumbing.** Each feature would otherwise grow its own tarball endpoint, targeting logic, Celery fan-out, and in-pod refresh script. `skills_plan.md` §9.7 already designed one such pipeline; without an abstraction the next two consumers copy it.
3. **No shared event hook.** Feature mutations (skill upload, doc index complete, admin file upload) have no shared API for saying "the bundle at scope X changed, get it to the pods."

## Important Notes

- **Single delivery shape.** Each consumer's payload is delivered as a tarball materialized on demand by the api_server. No incremental/delta path in v1. Sources of files (admin-uploaded zips, individual file uploads, indexed docs) are normalized at the ingest boundary, not the delivery boundary.
- **Push + poll, not push xor poll.** Every bundle gets both. Mutations enqueue an immediate push; an in-pod cron polls every 2 minutes as a safety net for the push-failure tail (~5% — overwhelmingly kubectl-exec into not-Ready pods).
- **`If-Modified-Since` makes polling cheap.** Each bundle exposes `last_modified()` (an indexed `MAX(updated_at)` query). The tarball endpoint returns `304` when nothing changed, so the steady-state poll cost is one DB query per pod per 2 minutes.
- **Anti-storm via Redis debounce.** A burst of mutations (e.g. 1000 doc-index events) collapses to one fan-out via `SET NX` with a short TTL at `enqueue_change()`.
- **Server-side tarball cache absorbs tenant fan-out.** For tenant-scoped bundles (skills) the first pod's request materializes; the rest hit a Redis-backed blob cache keyed by `(tenant, bundle, scope, last_modified)`. Materialization collapses from N→1 per change.
- **Two architectural assumptions.** (a) Each user has at most one active sandbox, so user-scoped bundles have no fan-out within a scope and don't need shared distribution. (b) Sandbox pods and the api_server / S3 live in the same region, so intra-region egress is free on AWS and isn't a cost driver.
- **Builds on the K8s label work from `skills_plan.md` §9.7.** `onyx.app/tenant-id` and `onyx.app/sandbox-id` already planned there are all the labels v1 needs. No new pod labels.
- **Per-bundle ingest is each feature's problem.** Skills accepts a zip (unpacks to S3 as individual files). user_library accepts individual files. The abstraction only governs delivery from S3 → pod.

## Distribution Model

The system needs to land identical content on many pods (tenant-scoped bundles like skills) without doing N× the work per change. The cost structure breaks into three pieces:

| Cost component | Driven by | v1 answer |
|---|---|---|
| **Materialization** (DB queries + S3 reads + tar packing) | api_server CPU | Server-side tarball cache, keyed by `(tenant, bundle, scope, last_modified)`. N pods on the same change → 1 materialization + N-1 cache hits. Cache lives in Redis with a small TTL; bundles over a size threshold (~10 MB) skip the cache and re-materialize (rare in v1). |
| **Network egress** (api_server → pod) | Pod count × tarball size | No special handling. Same-region AWS makes intra-cluster transfer free; the cache and 304s keep per-event volume bounded. |
| **In-pod work** (extract + atomic swap) | Pod count | Unavoidable. One pod, one extract — at our scale this is fine. |

### Why not a shared ReadOnlyMany volume per tenant?

That's the textbook k8s answer for shared content (one EFS/Filestore filesystem, mounted RO by every sandbox pod). It's strictly more efficient: one materialization, no per-pod transfer, instant visibility on the pod. We're deferring it because:

- v1 bundles are small (skills: KBs–MBs) or per-user (user_library: 1 sandbox per user, no fan-out to optimize).
- EFS/Filestore adds real infrastructure: provisioning, mount targets per AZ, mount-failure modes at pod boot, per-GB-month cost.
- The bundle interface tolerates a transport swap later. Bundle authors write `materialize()`; the transport between `materialize()` and the pod's mount path is internal. If `OrgFilesBundle` (admin-uploaded org-wide files — picture multi-GB policy archives) lands and tenant-fan-out costs become measurable, we promote tenant-scoped bundles to a shared-volume transport without changing any bundle implementation.

### Why polling is cheap (recap)

The in-pod 2-min cron only does an indexed `MAX(updated_at)` comparison via `If-Modified-Since` when nothing changed. A pod that polls all day during a quiet period costs us one DB query every 2 minutes — no S3, no tar, no cache, no transfer.

## Implementation Strategy

### Bundle interface

A small ABC under `backend/onyx/sandbox_sync/bundle.py`. Each consumer provides one implementation.

```python
class SandboxBundle(ABC):
    bundle_key: ClassVar[str]          # "skills" | "user_library" | "org_files"
    mount_path: ClassVar[str]          # in-pod absolute path

    @abstractmethod
    def materialize(self, db: Session, ctx: SandboxContext) -> Iterator[BundleEntry]: ...

    @abstractmethod
    def pod_label_selector(self, scope_key: str) -> str: ...

    @abstractmethod
    def last_modified(self, db: Session, ctx: SandboxContext) -> datetime: ...
```

- `BundleEntry` is `(rel_path, content_stream, mode)` — lazy, so materializing a large bundle doesn't load every file into memory.
- `SandboxContext` carries `tenant_id`, `sandbox_id`, and (resolved at request time from the sandbox row) `user_id` if relevant. Bundles read what they need.
- `pod_label_selector(scope_key)` returns a K8s label selector string. Skills: `onyx.app/tenant-id={tenant}`. user_library: `onyx.app/tenant-id={tenant}` (server filters per-pod by user_id at materialize time).
- `last_modified` returns the max source-row timestamp under this scope — used by the tarball endpoint for `If-Modified-Since`.

Registration happens at import time in `backend/onyx/sandbox_sync/bundles/__init__.py`:

```python
BundleRegistry.register(SkillsBundle())
BundleRegistry.register(UserLibraryBundle())
```

### Mutation → push flow

```
[ event site ]                          [ Celery worker ]                       [ pod ]
enqueue_change(t, b, s)  ───debounce──► propagate_bundle_change(t, b, s)
                                         │ resolve pods via
                                         │ bundle.pod_label_selector(s)
                                         ▼
                                         fan-out refresh_pod_bundle(pod, b)
                                         ───────────────────────────────────►  /usr/local/bin/refresh-bundle <key>
                                                                                ├ flock
                                                                                ├ curl tarball-endpoint (If-Modified-Since)
                                                                                ├ 304 → exit; 200 → extract to sibling dir
                                                                                ├ atomic mv-swap mount_path
                                                                                └ write /etc/sandbox/<key>.last-modified
```

- **`enqueue_change(tenant_id, bundle_key, scope_key)`** lives in `backend/onyx/sandbox_sync/enqueue.py`. Uses `redis.set(key, "1", nx=True, ex=5)`; if the SET succeeds, enqueues `propagate_bundle_change` with `countdown=2`, `expires=60`. A burst collapses to one propagation per 5-second window per scope.
- **`propagate_bundle_change(tenant_id, bundle_key, scope_key)`** (Celery, in `backend/onyx/background/celery/tasks/sandbox_sync/propagate.py`):
  - Deletes the debounce key first thing so further mutations re-enqueue.
  - Calls `core_v1.list_namespaced_pod(namespace=NS, label_selector=bundle.pod_label_selector(scope_key))`.
  - Fans out `refresh_pod_bundle.delay(pod_name, bundle_key)` per pod. `expires=60`.
- **`refresh_pod_bundle(pod_name, bundle_key)`** (Celery, in `.../refresh.py`): single `kubectl exec` invoking `/usr/local/bin/refresh-bundle <bundle_key>`. Non-zero exit logged; the cron picks up. `expires=120`.

### In-pod refresh

Single script `backend/onyx/server/features/build/sandbox/kubernetes/docker/refresh-bundle`, installed at `/usr/local/bin/refresh-bundle`:

```
refresh-bundle <bundle_key>
  ├ flock /var/lock/bundle-<key>.lock
  ├ curl -fS -H "Authorization: Bearer $(cat /etc/sandbox/sandbox-token)" \
  │       -H "If-Modified-Since: $(cat /etc/sandbox/<key>.last-modified 2>/dev/null)" \
  │       "$API_URL/api/internal/sandbox/$SANDBOX_ID/bundles/$1/tarball" \
  │       -o /tmp/$1.tar -w '%{http_code}\n'
  ├ if 304 → exit 0
  ├ mkdir /tmp/$1.new && tar -x -C /tmp/$1.new -f /tmp/$1.tar
  ├ mv $MOUNT_PATH $MOUNT_PATH.old.$$ && mv /tmp/$1.new $MOUNT_PATH
  ├ rm -rf $MOUNT_PATH.old.* /tmp/$1.*
  └ store new Last-Modified response header into /etc/sandbox/<key>.last-modified
```

Bundle configuration mounted at `/etc/sandbox/bundles/<bundle_key>.json` (`mount_path`, `tarball_url_template`) via ConfigMap built from `BundleRegistry`. The pod doesn't need to know which bundles exist beyond what's in that directory.

**Cron loop** runs in a tiny supervisor process (existing sandbox supervisor or a sidecar shell loop — TBD during implementation, leaning toward the existing supervisor):

```
while true; do
  for key in $(ls /etc/sandbox/bundles | sed 's/\.json$//'); do
    refresh-bundle "$key" || true
  done
  sleep 120
done
```

**Boot:** initial sync is the same script invocation, run once per bundle before the agent starts. No separate init code path.

### Tarball endpoint

`GET /api/internal/sandbox/{sandbox_id}/bundles/{bundle_key}/tarball` in `backend/onyx/server/internal/sandbox_bundles.py`:

- Auth: existing sandbox bearer token (the same one already used by `skills_plan.md` §9.7's `/skills-tarball`).
- Resolves `tenant_id`, `user_id` from the sandbox row → `SandboxContext`.
- Computes `last_modified = bundle.last_modified(db, ctx)`.
- If `If-Modified-Since` ≥ `last_modified` → `304 Not Modified`. (~one indexed DB query, no S3, no tarring.)
- Else: look up Redis cache key `bundle:tar:{tenant}:{bundle_key}:{scope_key}:{last_modified_iso}`.
  - **Cache hit:** stream the cached bytes back; record metric.
  - **Cache miss:** materialize via `tar(bundle.materialize(db, ctx))` into a bounded buffer. If under the size threshold (~10 MB, configurable), write the buffer to Redis with a short TTL (e.g. 15 min) before streaming. Over threshold, skip the cache.
- Response always includes `Last-Modified` header.

For tenant-fan-out cases (skills) this means 100 pods on the same change → 1 materialization, 99 cache hits. The cache key includes `last_modified`, so it self-invalidates on any source mutation — no explicit cache busting needed.

**Operational notes for the cache:**

- All keys live under a single prefix (`bundle:tar:`) so they can be flushed independently of other Redis state (e.g. `SCAN MATCH bundle:tar:*` for ops).
- 10 MB per-entry cap + 15-min TTL means the steady-state memory budget is bounded: in the worst case a handful of distinct `(tenant, bundle, scope, last_modified)` keys hold ~tens of MB. Each `last_modified` advance retires the prior key naturally.
- A metric (`bundle_tarball_cache_hit_total{bundle_key}` / `_miss_total`) surfaces whether the cache is earning its keep. Skills should run >95% hit ratio after the first request post-mutation; user_library will run ~0% (expected — no fan-out within a user).

### v1 bundle implementations

**`SkillsBundle`** (`backend/onyx/sandbox_sync/bundles/skills.py`):

- `materialize`: walks built-in skills on disk + custom skills from Postgres/`FileStore`, applies template rendering for built-ins that declare a template. Replaces the rendering/discovery work currently in `skills_plan.md` §9.
- `pod_label_selector(scope_key)`: `onyx.app/tenant-id={tenant_id}`. `scope_key` is always `"_global"`.
- `last_modified`: `SELECT MAX(updated_at) FROM skill WHERE tenant_id=...`.

**`UserLibraryBundle`** (`backend/onyx/sandbox_sync/bundles/user_library.py`):

- `materialize`: lists enabled docs for the user from Postgres (`Document` table, filtering `sync_disabled`), streams each from S3.
- `pod_label_selector(scope_key)`: `onyx.app/tenant-id={tenant_id}` — server materializes per-sandbox using `SandboxContext.user_id`. (We don't need an `onyx.app/user-id` label because the tarball endpoint resolves user from the sandbox row.)
- `last_modified`: `SELECT MAX(updated_at) FROM document WHERE user_id=... AND sync_disabled=false`.

### Wiring at event sites

- Skills admin mutations (in `backend/onyx/server/admin/skills/*.py`): call `enqueue_change(tenant_id, "skills", "_global")` after successful commit.
- User library doc indexing: at the existing `sync_sandbox_files` call site (or its replacement), call `enqueue_change(tenant_id, "user_library", f"u:{user_id}")` after successful index.

Both replace bespoke push calls; no other changes to those handlers.

### Relationship to `skills_plan.md` §9.7

`skills_plan.md` §9.7 currently specifies `propagate_skill_change` + `refresh_pod_skills` + `/skills-tarball` + `refresh-skills` script. This design supersedes that section: skills becomes the first consumer of the generic bundle pipeline. The skills plan needs a small follow-up to point §9.7 at this abstraction; the in-pod paths and ConfigMap mounts described here are compatible with what skills_plan already calls for.

### What we are explicitly **not** doing in v1

- **No content_hash, no bundle-version table, no monotonic counter.** `If-Modified-Since` over `MAX(updated_at)` is sufficient. Cut for being over-engineered.
- **No delta / incremental push.** Full tarball every time. user_library at scale is fine because of the 304 short-circuit; if a real bundle gets large enough to hurt, add `materialize_delta` then.
- **No per-bundle delivery mode** (push vs poll). Every bundle does both.
- **No `onyx.app/user-id` pod label.** Server resolves user from the sandbox row.
- **No bundle author UI / marketplace / org_files endpoint.** The interface is ready for `OrgFilesBundle` but no consumer is shipping in v1.
- **No ReadOnlyMany / shared-volume transport.** Server-side cache is sufficient given v1 bundle sizes, 1-sandbox-per-user, and intra-region pod placement. Upgrade path exists if `OrgFilesBundle` or scale forces it.

## Tests

The dominant test type for this work is **integration**: a real Postgres + Redis + Celery + k8s pod, mutation → enqueue → pod state. The interface is small enough that a few **external dependency unit tests** cover the bundle implementations themselves.

### External dependency unit tests (`backend/tests/external_dependency_unit/sandbox_sync/`)

- `test_skills_bundle.py` — materialize a SkillsBundle against a real DB + FileStore; assert correct file set, template rendering, `last_modified` returns expected timestamp.
- `test_user_library_bundle.py` — materialize against a real DB + S3 (MinIO); assert `sync_disabled` files excluded, `last_modified` reflects most recent doc update.
- `test_enqueue_debounce.py` — call `enqueue_change` 1000× in a tight loop against real Redis; assert exactly one propagate task is queued in the 5s window, a second wave after expiry enqueues again.

### Integration tests (`backend/tests/integration/tests/sandbox_sync/`)

- `test_push_path.py` — provision a sandbox, mutate a skill, assert the pod's `/skills/` reflects the change within ~5s. Verify the kubectl exec actually happened (check propagate + refresh task logs).
- `test_poll_recovers_from_push_miss.py` — provision a sandbox, mutate a skill, simulate kubectl-exec failure (e.g. block the API or kill the worker mid-task), wait ≤2min, assert the cron tick reconciles.
- `test_304_short_circuit.py` — provision a sandbox, let it poll, mutate nothing, assert tarball endpoint returns 304 on the next poll and pod state is untouched.
- `test_tarball_cache_hit.py` — provision two sandboxes in the same tenant, mutate a skill, let both pods refresh. Assert the bundle's `materialize` runs exactly once for that `last_modified` (instrument via counter on the bundle), and the second pod served from cache.
- `test_user_library_per_user_isolation.py` — two users, two sandboxes; mutate user A's library; assert user A's pod gets the new file and user B's pod does not.

### Unit tests

None planned; the components are thin and have no isolated business logic worth mocking out.

## Files Touched / Added

```
backend/onyx/sandbox_sync/                                          NEW
├── bundle.py                  # SandboxBundle ABC, BundleEntry, SandboxContext
├── registry.py                # BundleRegistry
├── enqueue.py                 # enqueue_change()
├── tarball.py                 # streaming tar builder over BundleEntry iterator
├── cache.py                   # Redis-backed tarball cache (get/set by last_modified)
└── bundles/
    ├── __init__.py            # registers bundles at import time
    ├── skills.py              # SkillsBundle
    └── user_library.py        # UserLibraryBundle

backend/onyx/background/celery/tasks/sandbox_sync/                  NEW
├── propagate.py               # propagate_bundle_change, expires=60
└── refresh.py                 # refresh_pod_bundle, expires=120

backend/onyx/server/internal/sandbox_bundles.py                     NEW
└── GET /api/internal/sandbox/{sid}/bundles/{key}/tarball

backend/onyx/server/features/build/sandbox/kubernetes/
├── docker/refresh-bundle                                            NEW (in-pod script)
└── kubernetes_sandbox_manager.py                                    +bundle ConfigMap mount,
                                                                     -file-sync sidecar

# Wiring (small, per existing handler):
backend/onyx/server/admin/skills/*.py                                +enqueue_change(... "skills" ...)
backend/onyx/server/user_files/*.py (or current sync call site)      +enqueue_change(... "user_library" ...)

# Doc updates:
docs/craft/features/skills/skills_plan.md                            §9.7 points at this abstraction
```

No alembic migration. No new pod labels beyond what `skills_plan.md` §9.7 already adds.
