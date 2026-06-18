# Sandbox snapshot worker ↔ NetworkPolicy

How Craft snapshot creation reaches sandbox pods, what access the snapshot worker
needs, and where this is headed.

## Background

opencode-history and per-session workspace snapshots are created by the
`cleanup_idle_sandboxes` Celery task, which POSTs to the in-pod **sidecar
(port 8731)** to produce the archive. That task runs on whichever worker consumes
the **`sandbox` Celery queue** — currently `celery-worker-heavy`.

Sandbox pods are guarded by the `onyx-sandbox-push` NetworkPolicy
(`templates/network-policy-sandbox-push.yaml`), which allow-lists who may reach the
sidecar (`:8731`), opencode serve (`:4096`), and the per-session Next.js dev
servers. A NetworkPolicy only takes effect on clusters whose CNI enforces
NetworkPolicies; where it isn't enforced the policy is inert (a pod can reach the
sidecar even if it isn't allow-listed). Keep the allow-list correct so behavior is
the same regardless of enforcement.

## Current state (as of 2026-06-17)

The `sandbox` queue runs on `celery-worker-heavy`, so that worker needs sidecar
access to create snapshots. It is granted a dedicated, least-privilege ingress rule
(sidecar port only), separate from the full api-server / scheduled-tasks block:

```
ingress:
  # api-server + scheduled-tasks (full sandbox driving)
  - from: [api-server, celery-worker-scheduled-tasks, (ambassador local-dev)]
    ports: [8731, 4096, 3010–3099]
  # heavy worker — snapshot creation only
  - from: [celery-worker-heavy]
    ports: [8731]
```

- `api-server` and `celery-worker-scheduled-tasks` drive sandboxes end-to-end
  (provision, restore, opencode serve, dev-server preview), so they get the full
  port set.
- `celery-worker-heavy` only POSTs to the sidecar for snapshot creation, so it gets
  the sidecar port (`:8731`) only.

Network access alone isn't enough: snapshot POSTs are **signed**
(`SidecarClient._signed_headers` → `get_push_key_pair`), so the worker also needs
`ONYX_SANDBOX_PUSH_PRIVATE_KEY`. With the default `sandboxPushSecret.allPods=false`
that key is emitted only via `onyx.envSecretsRestricted`, so `celery-worker-heavy`
must include that block (as `api-server` and `celery-worker-scheduled-tasks` do) —
otherwise `get_push_key_pair` raises before the request is even sent. Both the
allow-list rule and the restricted secret must point at whatever worker runs the
`sandbox` queue.

If a cluster enforces NetworkPolicy and the worker that runs the `sandbox` queue is
not in this allow-list, snapshot creates connect-time-out
(`Snapshot create request failed: timed out`) and no snapshots are produced — so
this allow-list must track wherever the `sandbox` queue runs.

## Future direction: a dedicated sandbox/craft worker

`celery-worker-heavy` also runs the heavy connector queues (`connector_pruning`,
`connector_doc_permissions_sync`, `connector_external_group_sync`,
`csv_generation`), so Craft snapshotting currently shares a worker with bursty
connector load. A cleaner setup is a dedicated worker (e.g. `celery-worker-sandbox`)
that:

- consumes only the `sandbox` queue (isolated from connector/indexing load),
- is the one granted in `onyx-sandbox-push` (replacing `celery-worker-heavy`),
- carries the sandbox RBAC, and
- is sized / HPA'd for bursty snapshot I/O (tar+gzip of webapp source + attachments;
  `node_modules`/`.next` are excluded, so it's MB-scale, not GB).

That keeps `celery-worker-scheduled-tasks` lean for timely cron dispatch and keeps
Craft snapshotting off the contended connector worker. When it lands, point the
`onyx-sandbox-push` allow-list at the new worker instead of heavy.

## NetworkPolicy enforcement is a cluster/CNI concern

Whether NetworkPolicies are enforced at all is a property of the cluster's CNI,
configured at the infrastructure layer — not something the Onyx app chart can
toggle. The chart's job is to keep the allow-list correct so the policy behaves the
same whether or not enforcement is on. Enforcement should be consistent across
environments so connectivity gaps surface everywhere, not only on enforcing
clusters.

## Monitoring

`celery-worker-heavy` is the prime suspect when snapshotting breaks:

1. **Connectivity** — if it can't reach the sidecar (allow-list missing it, or
   enforcement turned on without the allow-list), snapshot creates connect-time-out
   and no snapshots are produced. Detect: `Snapshot create request failed: timed out`
   in the heavy worker logs; missing/stale
   `sandbox-snapshots/.../opencode-history.tar.gz` objects in the file store; or a
   session's `opencode_session_id` absent from its sandbox snapshot.
2. **Contention** — heavy also runs the connector queues above; a large connector
   job can saturate it and starve/slow the `sandbox` sweep. Watch
   `onyx_celery_task_duration_seconds` / queue wait for the `sandbox` queue and the
   heavy worker's active-task mix.
