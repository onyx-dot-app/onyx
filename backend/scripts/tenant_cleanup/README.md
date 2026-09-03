## How to Tenant Cleanup

Three steps. Every script talks to the databases through `kubectl exec` on running pods. There is
no bastion host, so no SSH keys and no environment variables are necessary.

Read [QUICK_START_NO_BASTION.md](./QUICK_START_NO_BASTION.md) before step 2 or step 3. It records
the operational limits. The most important one: the database writer is the constraint, not the
pods.

### Before you start

Pod discovery runs `kubectl get po` without `-n`. Each context must therefore set the namespace
that holds its pods. If the namespace is wrong, the script reports that it found no pod.

```
kubectl config set-context <data_plane_context> --namespace=<data_plane_namespace>
kubectl config set-context <control_plane_context> --namespace=<control_plane_namespace>
```

### 1. Build a list of tenants to clean up

```
cd onyx/backend
PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_analyze_tenants.py \
    --data-plane-context <data_plane_context> \
    --control-plane-context <control_plane_context>
```

This writes `gated_tenants_inactive_<N>d_<datetime>.csv` to the current directory, where N is
the cutoff that was applied.

A tenant is eligible only when both conditions hold:

- the control plane gives it the status `GATED_ACCESS`, and
- its last chat query and its last Craft session are both older than the cutoff.

The cutoff is 60 days. Use `--inactive-days` to change it. The script ignores cached tenant data
from before Craft activity was collected.

The run also writes `tenant_data_<datetime>.json`. That file holds real user chat text. Keep it out
of the repo and off shared storage.

### 2. Delete all documents within these tenants

```
PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_mark_connectors.py \
    --csv gated_tenants_inactive_<N>d_<datetime>.csv \
    --data-plane-context <data_plane_context> \
    --control-plane-context <control_plane_context> \
    --force
```

This cancels all index attempts and marks all connectors for deletion. Celery then deletes the
documents in the background. Tenants with no documents drain in minutes. Tenants with many
documents can take more than six hours.

The work is handed to Celery because it reuses the existing deletion code and the existing
infrastructure for long parallel jobs. A script cannot hold these jobs open.

### 3. Clean up the tenants

Wait for step 2 to finish. Then run:

```
PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_cleanup_tenants.py \
    --csv gated_tenants_inactive_<N>d_<datetime>.csv \
    --inactive-days <N> \
    --data-plane-context <data_plane_context> \
    --control-plane-context <control_plane_context> \
    --force
```

Give `--inactive-days` the same N used in step 1. If the two disagree, the re-check uses a
different window than the one that selected the tenants.

Before it drops anything, this re-reads each tenant's chat and Craft activity and refuses any
tenant that has become active since the CSV was made. The CSV can be days old, and the control
plane status alone does not show renewed use. Use `--inactive-days` to match the value given to
the analyze step; it defaults to 60.

This then drops each tenant schema from the data plane, deletes the `public.user_tenant_mapping`
rows, and deletes the control plane rows for the tenant.

Tenants that still hold documents raise an exception. That means step 2 has not finished.

Successful tenants are appended to `cleaned_tenants.csv`. Keep that file. It is the only record of
what was deleted, and a later sweep of orphaned search-index chunks needs it.

### Verify the result

Check the databases, not the summary the scripts print. A tenant counted as successful can still
leave rows behind if a later step failed. Reconcile three sources: `pg_namespace`,
`public.user_tenant_mapping`, and the control plane `tenant` table.
