---
name: verify
description: Verify a backend change through the running Onyx app before committing. Save HTTP, service log, and integration test evidence for the PR.
---

# Verify a backend change

1. Check `git status --short` for untracked paths. Read `git diff HEAD` or
   `git show <commit>` for the diff.
   Use [PATHS.md](../../feature-map/PATHS.md) and
   [VERIFYING.md](../../feature-map/VERIFYING.md) to find affected features.
   Pick the API entry point, expected result, service logs, and narrowest integration test.
2. Follow the [ODS skill](../onyx-dev-stack/SKILL.md). Use `stack status --json`
   to check the checkout, services, and web URL. Reuse healthy services in this checkout.
   Use the minimal profile for an API-only probe and default for a worker or connector probe.
   Use full if the integration test needs more services. Use an isolated stack if the test
   resets data or another checkout needs its stack. Read fixture setup before running the test.
   If the frontend build hits a temporary directory quota, set `TMPDIR` to an
   ignored directory in this worktree and retry.
   Restart affected services if they have old code. Check readiness at `/api/auth/type`.
3. Log in through the web URL from ODS. The usual URL is `http://localhost:3000`.
   Use the local test account from [AGENTS.md](../../../AGENTS.md).

   ```bash
   umask 077
   scratch=$(mktemp -d)
   evidence=$(mktemp "${TMPDIR:-/tmp}/onyx-verify.XXXXXX.md")
   web=http://localhost:3000  # Set this to the ODS web URL.
   curl --fail --silent --show-error --max-time 15 -c "$scratch/cookies" \
     --data-urlencode 'username=admin_user@example.com' \
     --data-urlencode 'password=TestPassword123!' \
     "$web/api/auth/login" -o /dev/null
   ```

   If the account is absent, register it on the local signup page and retry.
   The first user becomes admin. For admin routes, confirm the account has admin access.
4. Note the current time and log positions. Call the changed route with the cookie jar.
   For a worker or connector change, call the route that starts work.
   Poll for a terminal state with a deadline. Record the last status on timeout.
   If cleanup removes successful jobs, check for the output by job ID too.
   Use local test data. Seed the data the change needs before you start the probe.
   For browser steps, use the [Playwright skill](../playwright/SKILL.md).

   ```bash
   route=/api/persona  # Replace this with the route under test.
   printf 'GET %s\n' "$route" >> "$evidence"
   curl --silent --show-error --max-time 30 -b "$scratch/cookies" \
     -o "$scratch/response" -w 'HTTP %{http_code}\n' "$web$route" >> "$evidence"
   ```

   Check the status and response against the expected result. Add a safe response excerpt.
   Read new lines in `backend/log/<service>_debug.log`. Match them by request path,
   task ID, or connector ID and add the matching lines. Use `ods stack logs` to locate
   service output if the path is missing. Record missing log evidence.
5. Run the selected test per [backend/AGENTS.md](../../../backend/AGENTS.md).
   The integration runner provides its own in-process API and workers.
   Use isolated ODS infrastructure for the test workers.
   If you started that stack for the probe, stop its app services and keep its
   infrastructure. If you reused a shared app, keep it running and use a separate
   isolated stack for the test.
   If the test resets data, confirm the isolated Postgres host and port.
   Set `POSTGRES_DB` to the database name in that stack, normally `postgres`.
   Read [integration setup](../../../backend/tests/integration/README.md) for
   dependencies and Enterprise tests. For Enterprise checks, upload the local
   license to the isolated app. Pass the license to the test process with
   `ONYX_DEV_LICENSE` if the test needs to reseed it.

   ```bash
   (cd backend && uv run --frozen --env-file ../.vscode/.env pytest -xv '<test node ID relative to backend/>') > "$scratch/test.log" 2>&1
   ```

   Save test output to a private file, check the exit code, and add a safe excerpt.
6. Record the revision, expected result, actual result, checks you could not run,
   and elapsed time in the evidence file. Include setup time separately if you started ODS.
   Exclude cookies, tokens, licenses, and private data. Remove the scratch directory.
   Put the evidence path in your report and paste safe excerpts into the PR.

## Stamp the commit

Use Git's `--trailer` option. Record the strongest check that passed for the change.

- `Verified-by: e2e` for a live check through the app.
- `Verified-by: integration` for an integration test.
- `Verified-by: unit` for a unit test.
- `Verified-by: none (short reason)` if no check passed.

```bash
git commit -m 'fix: describe the change' --trailer 'Verified-by: e2e'
```
