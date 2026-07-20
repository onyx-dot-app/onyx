# Quick Start: Tenant Cleanup Without Bastion

## TL;DR - The Commands You Need

```bash
# Navigate to backend directory
cd onyx/backend

# Step 1: Generate CSV of tenants to clean (5-10 min)
PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_analyze_tenants.py

# Step 2: Mark connectors for deletion (1-2 min)
PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_mark_connectors.py \
  --csv gated_tenants_no_query_3mo_*.csv \
  --force \
  --concurrency 16

# ⏰ WAIT 6+ hours for background deletion to complete

# Step 3: Final cleanup (1-2 min)
PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_cleanup_tenants.py \
  --csv gated_tenants_no_query_3mo_*.csv \
  --force
```

## What Changed?

Instead of the original scripts that require bastion access:
- `analyze_current_tenants.py` → `no_bastion_analyze_tenants.py`
- `mark_connectors_for_deletion.py` → `no_bastion_mark_connectors.py`
- `cleanup_tenants.py` → `no_bastion_cleanup_tenants.py`

**No environment variables needed!** All queries run directly from pods.

## What You Need

✅ `kubectl` access to your cluster
✅ Running `celery-worker-user-file-processing` pods
✅ Permission to exec into pods

❌ No bastion host required
❌ No SSH keys required
❌ No environment variables required

## Test Your Setup

```bash
# Check if you can find worker pods
kubectl get po | grep celery-worker-user-file-processing | grep Running

# If you see pods, you're ready to go!
```

## Important Notes

1. **Step 2 triggers background deletion** - the actual document deletion happens asynchronously via Celery workers
2. **You MUST wait** between Step 2 and Step 3 for deletion to complete (can take 6+ hours).
   Tenants with no documents drain within minutes, since there is nothing to delete.
3. **Monitor deletion progress** with: `kubectl logs -f <celery-worker-pod>`
4. **All scripts verify tenant status** - they'll refuse to process active (non-GATED_ACCESS) tenants
5. **Pods are resolved once per run.** If that pod restarts mid-run, every remaining tenant fails.
   Prefer batches of ~1000 over one enormous run.
6. **Set the namespace on your kubectl contexts.** Pod discovery runs `kubectl get po` with no
   `-n`, so it only sees the context's default namespace.
7. **Verify against the database afterwards, not against the summary.** A tenant counted as
   successful can still leave rows behind if a later step failed. Check `pg_namespace`,
   `public.user_tenant_mapping`, and the control plane `tenant` table.
8. **Search indices are not cleaned up.** In multi-tenant deployments all tenants share indices
   and are separated by a `tenant_id` field, so dropping a schema leaves that tenant's chunks
   behind. They can be swept later by selecting on `tenant_id` - keep `cleaned_tenants.csv`.
9. **To go faster, spread across pods - do not just raise `--concurrency`.** Every operation is a
   `kubectl exec` against the one pod the run picked, so that pod is the bottleneck. Running two
   batches at once without pinning gains nothing: pod selection is random over a small set, so
   both runs usually land on the same pod, and it ends up saturated while its replicas idle.
   Pin distinct pods per run instead:

   ```bash
   # terminal 1
   ... --csv batch_a.csv --concurrency 8 \
       --data-plane-pod <worker-pod-1> --control-plane-pod <control-pod-1>
   # terminal 2
   ... --csv batch_b.csv --concurrency 8 \
       --data-plane-pod <worker-pod-2> --control-plane-pod <control-pod-2>
   ```

   Measured on a real cleanup: one run at `--concurrency 12` reached ~34 tenants/min and pinned a
   worker at ~2 cores while its replica sat idle. Two pinned runs at `--concurrency 8` reached
   ~67 tenants/min with neither worker above ~1.2 cores. Remember these are live workers doing
   real work, so prefer spreading load over concentrating it.

## Files Generated

- `tenant_data_YYYYMMDD_HHMMSS.json` - Raw per-tenant data. **Contains real user chat message
  text** (`last_query_text`); keep it out of the repo and off shared storage.
- `gated_tenants_no_query_3mo_YYYYMMDD_HHMMSS.csv` - List of tenants to clean
- `cleaned_tenants.csv` - Successfully cleaned tenants with timestamps. Appended across runs, and
  the only record of what was deleted - needed for any later search-index sweep.

## Safety First

The scripts include multiple safety checks:
- ✅ Verifies tenant status before any operation
- ✅ Checks documents are deleted before dropping schemas
- ✅ Prompts for confirmation on dangerous operations (unless `--force`)
- ✅ Records all successful operations in real-time

## Need More Details?

See [NO_BASTION_README.md](./NO_BASTION_README.md) for:
- Detailed explanations of each step
- Troubleshooting guide
- How it works under the hood
- Performance characteristics
