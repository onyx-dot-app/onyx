# Chart migration guide

Breaking changes between Onyx Helm chart versions and what to do about them.

## chart 0.4.x → 0.5.x

### What changed

Chart 0.5.0 removed the bundled `charts/vespa/` subchart. Earlier chart
versions installed Vespa as a `da-vespa` StatefulSet alongside the rest of
Onyx; the api-server connected to it on `localhost:19071` (Vespa application
deploy port) and the chart-managed PV held the indexed corpus.

The 0.5.x line assumes you are running Vespa **outside** the chart — either
managed Vespa, Vespa Cloud, or a separately-managed deployment in another
namespace.

### Why this matters

A naive `helm upgrade` from 0.4.x to 0.5.x will delete the `da-vespa`
StatefulSet (no template renders it anymore). The PV underneath the
StatefulSet's PVC will be orphaned but the data inside is unreachable
until you reattach it manually. Meanwhile the api-server will crash-loop
trying to deploy its Vespa application package:

```
ConnectionRefusedError: [Errno 111] Connection refused
HTTPConnection(host='localhost', port=19071): Failed to establish a new
connection
```

The chart now ships a guard that detects this situation at install/upgrade
time and fails fast with a clear message instead of silently breaking. See
`templates/legacy-vespa-check.yaml`.

### How to upgrade safely

1. **Stand up an external Vespa cluster.** Vespa Cloud or a self-hosted
   deployment outside this chart, whichever fits your operational model.
2. **Re-index is automatic.** Vespa data does not roundtrip directly
   between releases (chunk schemas have changed over time anyway). No
   manual action here; Onyx connectors will reindex on their own once
   the api-server can reach the new endpoint (after the upgrade in
   step 5).
3. **Update your values** to point Onyx at the external Vespa endpoint
   (the api-server respects `VESPA_HOST` / `VESPA_PORT` env vars; set
   them through your `configMap:` block).
4. **Delete the old StatefulSet** once you no longer need it. The PV
   reclaim policy determines whether the underlying disk goes with it —
   verify before you delete anything.
5. **Run `helm upgrade`** with chart 0.5.x. If the old StatefulSet is
   already gone the legacy check passes automatically.

If you need to bypass the check (e.g. you've already migrated and only
have a stale PV lingering), set in your values:

```yaml
legacyVespaCheck:
  acknowledged: true
```

or disable the check entirely with `legacyVespaCheck.enabled: false`.

### `celery-worker-scheduled-tasks` deployment

Chart 0.5.x added a `celery-worker-scheduled-tasks` Deployment that runs
the `onyx.background.celery.versioned_apps.scheduled_tasks` celery app.
That app exists only in `onyxdotapp/onyx-backend` images cut after the
"scheduled tasks v1" change. If you upgrade the chart without bumping the
backend image, the deployment will crash-loop with:

```
Error: Unable to load celery application.
The module onyx.background.celery.versioned_apps.scheduled_tasks was not
found.
```

The deployment is already gated on its `replicaCount`. If your image is
too old, disable it explicitly in your values:

```yaml
celery_worker_scheduled_tasks:
  replicaCount: 0
```

The scheduled-tasks worker is only required if you use Onyx's craft /
sandbox feature; otherwise it is safe to leave disabled.
