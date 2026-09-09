# Seafile Connector E2E

Run the Seafile connector E2E suite through its local runner:

```sh
python backend/tests/integration/connector_job_tests/seafile/run_seafile_e2e.py
```

The runner starts and verifies the host-reachable services required by this suite:

- `relational_db` on `localhost:5432`
- `cache` on `localhost:6379`
- `opensearch` on `localhost:9200`
- `minio` on `localhost:9004`
- `inference_model_server` on `localhost:9000`

It then runs the Seafile E2E file from `backend/` with the required integration
environment:

```sh
INTEGRATION_TESTS_MODE=true \
USER_AUTH_SECRET=test-secret \
POSTGRES_DB=postgres \
FILE_STORE_BACKEND=s3 \
S3_ENDPOINT_URL=http://localhost:9004 \
S3_AWS_ACCESS_KEY_ID=minioadmin \
S3_AWS_SECRET_ACCESS_KEY=minioadmin \
uv run pytest -q tests/integration/connector_job_tests/seafile/test_seafile_e2e.py
```

Pass extra pytest arguments after `--`:

```sh
python backend/tests/integration/connector_job_tests/seafile/run_seafile_e2e.py -- -k multiple_libraries
```

By default, the runner owns the local dependency lifecycle. After pytest exits,
including failure exits, it runs:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v --remove-orphans
```

That removes the containers and compose volumes so the next run starts from a
clean state.

Use `--keep-services` to leave containers and volumes running for debugging.
Use `--no-up` to skip compose startup when the services are already running; in
that mode the runner does not clean up by default because it did not create the
stack. Add `--cleanup-existing` with `--no-up` when you also want the existing
compose stack removed after pytest completes.
