---
name: onyx-dev-stack
description: Start, inspect, restart, or stop an Onyx development stack with ODS. Prefer frontend-only previews for frontend-only diffs, shared infrastructure for ordinary work, and explicit isolation for independent datasets. Do not use for Kubernetes development.
---

# Onyx dev stack

Run from the worktree that contains the code being tested. ODS owns processes, ports, state, and logs.

## Select ODS

Check for `uv`, `bun`, and a running Docker daemon. Use the repository-pinned ODS when it provides the stack command:

```bash
uv run --frozen --only-group ods ods stack --help
```

Check `ods web dev --help` and `ods --help` too. If the pinned package lacks the shared-stack behavior, build ODS from this checkout. This requires Go:

```bash
ODS_BUILD_DIR="$(mktemp -d "$(git rev-parse --path-format=absolute --git-path ods-stack-bin).XXXXXX")"
ODS="$ODS_BUILD_DIR/ods"
go -C tools/ods build -o "$ODS" .
"$ODS" stack --help
```

Use the selected command for the remaining steps. Examples below use `"$ODS"`; replace that prefix with the pinned invocation when available.

## Start and discover

For frontend-only diffs on macOS or Linux, run the frontend against an existing healthy managed API:

```bash
"$ODS" web dev
```

This foreground command starts only the web server. Keep its terminal running.
It requires a healthy managed API. Ctrl-C stops a newly launched preview.
If a matching frontend already runs in this checkout, ODS attaches instead;
Ctrl-C then only detaches. `stack status` does not list standalone previews.
Ctrl-C also cancels dependency installation and library builds during startup.
It does not run migrations, start workers, or start containers. If no healthy API
exists, start the default stack first. Use a full stack for backend changes and
OAuth callback testing, because the reused API retains its original web origin.
Other `ods web` scripts, including build and test, remain package-script commands.

On Windows, `web dev` and `backend` use portable foreground launchers and
configured connection variables. Managed stacks, API discovery, and attachment
are macOS/Linux behavior. Check the frontend URL directly after a Windows launch.

For ordinary work, start the default profile with shared infrastructure:

```bash
"$ODS" stack up --timeout 12m
"$ODS" stack status --json
```

Use the reported web URL for browser tests and HTTP requests. Do not assume port `3000` or call a backend port directly.

`up` prepares local environment files and dependencies, reuses shared infrastructure, applies migrations, and reconciles background application services. Existing secrets stay private. Ask for a model key only when the requested test needs one.
Pending migrations stop managed application services before changing the schema.
If the database is already at head, unchanged healthy services keep running.

Run a slow startup in a background terminal when available. Wait for its exit and inspect status before reporting success.

Read `"$ODS" stack up --help` before choosing a different profile:

- `minimal` runs web and API for UI/API work.
- `default` adds the workers needed for ordinary indexing and background tasks.
- `full` runs the full launch compound for integration work.

Use `--local-model-server` only when changing model-server code. Other profiles use Compose inference and avoid a duplicate local model process.
Repeat the profile and local-model flag with `start` or `restart`. Use `up` to change model mode or recover infrastructure.

## Multiple agents

- Agents in the same worktree share one stack. Reuse a healthy stack through `up` and `status`.
- By default, worktrees share infrastructure and one active application checkout. Running `up` elsewhere stops the prior managed app before migrations.
- Use `ods --isolated stack up` for separate state, ports, Compose projects, databases, queues, indexes, and object storage. Repeat `--isolated` for later commands.
- Use `ods web dev` for frontend-only diffs with a healthy managed API. Its Ctrl-C behavior leaves the reused API running.
- Shared status reports the active checkout. Run stop, down, start, and restart there. Only up transfers ownership.
- Legacy datasets are preserved. If several exist at first shared startup, select the intended one with `--project`; never choose by timestamps. Stop its legacy stack with `--isolated` before adoption.
- Project ownership is durable. An explicit project collision fails, including in isolated mode. Select a different project for independent infrastructure.
- ODS persists port assignments and changes them only when necessary. Read status again after a restart.
- The selected stack lock coordinates lifecycle changes. Shared handoffs serialize; isolated stacks can start independently.
- Foreground services and full stacks use the same service specifications and process launchers. A full stack replaces a same-checkout preview and retains its port.
- Database operations target exact project containers and use state/project locks. Do not work around a target conflict or another checkout's ownership guard.
- Stop managed services before manual `db upgrade` or `db downgrade`. Use `stack up` for pending-aware upgrades.
- An explicit loopback database port resolves to its actual managed owner. `ods env` leaves dotenv files unchanged if the selected Postgres container has no published port.
- Do not stop another worktree's services or kill unrelated processes to free a port.
- Keep `.vscode/.env` and `.vscode/.env.web` untracked. Do not print their contents.

Use shared mode for sequential development and frontend previews. Use isolated mode for simultaneous backend branches, incompatible schemas, destructive tests, or independent datasets.

## Inspect and recover

```bash
"$ODS" stack status --json
"$ODS" stack logs
```

Inspect the reported phase, failed services, and logs when startup is incomplete. Re-run `up` to recover a partial start. Preserve healthy services and report optional integrations that remain unavailable.

Run `"$ODS" stack logs --help` to select a service or follow logs. Follow logs in a background terminal when continued observation is needed.

Successful startup requires the readiness check through the reported frontend URL. A process that exists is insufficient evidence.

## Validate changes

For lifecycle, concurrency, browser, or real worker validation, read [the ODS integration guide](../../../tools/ods/integration/README.md).
Use disposable worktrees with `ods --isolated stack up` for these tests. They create accounts, change the default test LLM provider, and stop services.
The browser smoke configuration supports an unlicensed local deployment. Its chat checks use a scripted local LLM, not a paid model key.
Never reset a developer database to satisfy a test fixture.
Database restore errors fail the command; SQL restores stop on SQL errors.

## Stop

Stop managed application processes while keeping infrastructure available:

```bash
"$ODS" stack stop
```

Stop the worktree's application processes and infrastructure:

```bash
"$ODS" stack down
```

Normal shutdown preserves volumes. Delete database, index, or object-store data only when the user explicitly requests a reset.

After shutdown, inspect status to confirm the targeted stack stopped. Check that another running worktree remains available when testing isolation.
