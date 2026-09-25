# Chart migration guide

Breaking changes between Onyx Helm chart versions and what to do about them.

## chart 0.8.x → 0.9.x

### What changed

MinIO no longer publishes images, so chart 0.9.0 adds `objectStore`, an
in-cluster S3 store that runs SeaweedFS. It replaces the bundled MinIO. When
`minio.enabled` is true, the chart runs both stores during the move:

- The app writes new files to the object store and to MinIO. A failed MinIO
  write only logs a warning, so MinIO trouble never blocks an upload.
- A read that misses the object store falls back to MinIO.
- A delete removes the file from both stores.
- The `<fullname>-legacy-minio-copy-<hash>` Job copies every MinIO object into
  the object store. It never replaces a file the app wrote. It replaces an
  object only when a 0.8.x pod wrote a newer version after a rollback.

The MinIO subchart only gains a keep annotation on its PVC, so its pod does not
restart. The app pods roll out as in a normal upgrade. There is no downtime and
every file stays readable during the copy.

Installs with `minio.enabled: false` (external S3, GCS or Azure) do not change.
`objectStore.enabled` follows `minio.enabled` when you do not set it.

### Before you upgrade

- **Image version:** chart 0.9.0 needs the Onyx release that ships it. With
  `--reuse-values`, set `global.version` to that release as well. An older
  image cannot read MinIO files through the object store.
- **Air-gapped registries:** mirror `chrislusf/seaweedfs` (the tag and digest
  are in `objectStore.image`) and set `objectStore.image.repository`.
- **Storage:** the new PVC `<fullname>-object-store` uses the size and storage
  class of `minio.persistence` by default. It must hold all MinIO data. Set
  `objectStore.persistence` to change this.
- **Pod security:** the object store runs as UID 1000 with a read-only root
  file system and no capabilities, so it passes the `restricted` Pod Security
  Standard. On OpenShift, set `objectStore.podSecurityContext: {}` so the
  cluster assigns the UID.
- **Credentials:** the object store uses the `s3_aws_access_key_id` and
  `s3_aws_secret_access_key` keys of `auth.objectstorage` as its admin keys.
  You do not need new secrets.

### Upgrade

Run `helm upgrade` as usual. `--reuse-values`, ArgoCD, Flux and rendered
manifests all work. The copy is a plain Job rather than a Helm hook, so
`helm upgrade` does not wait for it to finish.

Watch the copy:

```bash
kubectl logs -f -n <namespace> -l app=legacy-minio-copy
```

The Job ends with `Legacy MinIO copy complete`. It finishes only after a pass
copies nothing and `objectStore.legacyCopy.settleSeconds` (600 by default) have
passed, so it also copies files from pods that were still on 0.8.x. If objects
fail to copy, the Job retries and then fails with the keys in its log. The app
keeps serving from both stores in the meantime. After fixing the cause, delete
the failed Job and upgrade again to rerun it. A chart upgrade that changes the
Job's spec runs the copy again, which skips every object already copied.

### Rollback

`helm rollback` to 0.8.x points the app back at MinIO. MinIO has every file,
including files uploaded after the upgrade, because 0.9.x writes to both
stores. The `<fullname>-object-store` PVC stays, and the next upgrade continues
the move.

One exception: a file written or deleted while MinIO was unavailable reaches
MinIO only when the copy Job next runs. If MinIO had an outage after the Job
completed, delete the Job and upgrade again before you roll back, and wait for
it to complete.

### Retire MinIO

You can stop using MinIO once the copy Job completes, without waiting for a
later release. After that, a rollback to 0.8.x no longer sees files uploaded
since.

1. Once no pod runs 0.8.x, retire MinIO from an API server pod:

   ```bash
   kubectl exec -n <namespace> deploy/<fullname>-api-server -- \
     python -m onyx.file_store.legacy_copy --retire
   ```

   It copies anything left, waits a quiet minute, and checks that nothing
   reached MinIO alone in that time. If something did, a 0.8.x pod is still
   running, so it fails and MinIO stays in use. Otherwise it writes a marker to
   the object store, and within a minute every pod stops writing to MinIO,
   with no restart.
2. Make sure Helm keeps the MinIO PVC. Chart 0.9.0 marks it
   `helm.sh/resource-policy: keep`, but an upgrade with `--reuse-values` keeps
   the old values, which lack that annotation. Check it, and add it if it is
   missing:

   ```bash
   kubectl annotate pvc -n <namespace> <fullname>-minio \
     helm.sh/resource-policy=keep --overwrite
   ```
3. Set `minio.enabled: false` and `objectStore.enabled: true`, then upgrade.
   MinIO stops and the app pods roll out without downtime. The MinIO PVC
   stays. Delete it when you no longer need that data.

New installs set `minio.enabled: false` and `objectStore.enabled: true`.

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
