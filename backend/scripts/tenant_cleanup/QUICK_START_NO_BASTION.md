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
2. **You MUST wait** between Step 2 and Step 3 for deletion to complete (can take 6+ hours)
3. **Monitor deletion progress** with: `kubectl logs -f <celery-worker-pod>`
4. **All scripts verify tenant status** - they'll refuse to process active (non-GATED_ACCESS) tenants

## Files Generated

- `gated_tenants_no_query_3mo_YYYYMMDD_HHMMSS.csv` - List of tenants to clean
- `cleaned_tenants.csv` - Successfully cleaned tenants with timestamps

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
