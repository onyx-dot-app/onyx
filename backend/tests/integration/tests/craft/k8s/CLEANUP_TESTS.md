# Cleanup and recovery integration tests

The resource checks in `cleanup/` use real Kubernetes API calls in disposable namespaces.
They cover partial deletion, actual RBAC denial, pagination, tenant ownership, and stale resource identity.
See `cleanup/README.md` for the command. These checks do not change application users or database rows.

The full deployment checks are separate files:

- `test_cleanup_checkpoint_failure.py` preserves a runtime after workspace discovery or SQLite history capture fails.
- `test_cleanup_reconciliation.py` collects orphaned resources and abandoned provisioning, including when no RUNNING rows exist.
  It also verifies that a failed database inventory read cannot authorize orphan deletion.
- `test_cleanup_snapshot_commit.py` uses a deferred PostgreSQL constraint trigger to reject a real snapshot commit.
  The previous committed archive must remain readable.
- `test_cleanup_recovery.py` restores two sessions after idle cleanup and restores a FAILED runtime after a worker restart.

These tests enqueue the real Celery task and observe its completion in the worker log.
They do not call the task locally or mock the Kubernetes manager.
Archive teardown includes uploaded files that have no committed snapshot reference.

## Isolation requirements

Run fault tests only in the dedicated, disposable Kubernetes CI deployment.
They refuse collection without `SANDBOX_TEST_ISOLATED_DEPLOYMENT=true`.
Before a test runs, its app namespace must have `onyx.app/cleanup-test-run` matching `SANDBOX_TEST_RUN_ID`.
The CI workflow supplies both values and enables DEBUG logs for the heavy worker.

The tests change only test accounts, but database fault injection temporarily renames the sandbox table.
The recovery test also replaces the isolated deployment's cleanup worker pod.
Do not enable these tests against shared Craft Dev.

Resource reconciliation observes the real 15-minute creation grace period.
The FAILED checkpoint test clears only its own resource retry keys after repairing the injected failure.
It does not shorten the creation grace period or change the production clock.
