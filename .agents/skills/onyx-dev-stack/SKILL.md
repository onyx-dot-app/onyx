---
name: onyx-dev-stack
description: Start, inspect, restart, or stop an isolated local Onyx development stack with ODS. Use for empty worktree setup, background services, dynamic ports, migrations, and coordinating agents across worktrees. Do not use for Kubernetes development.
---

# Onyx dev stack

Run from the worktree that contains the code being tested. ODS owns processes, ports, state, and logs.

## Select ODS

Check for `uv`, `bun`, and a running Docker daemon. Use the repository-pinned ODS when it provides the stack command:

```bash
uv run --frozen --only-group ods ods stack --help
```

If the pinned package predates `ods stack`, build the command from this checkout. This requires Go:

```bash
ODS_BUILD_DIR="$(mktemp -d "$(git rev-parse --path-format=absolute --git-path ods-stack-bin).XXXXXX")"
ODS="$ODS_BUILD_DIR/ods"
go -C tools/ods build -o "$ODS" .
"$ODS" stack --help
```

Use the selected command for the remaining steps. Examples below use `"$ODS"`; replace that prefix with the pinned invocation when available.

## Start and discover

Start the default profile:

```bash
"$ODS" stack up --timeout 12m
"$ODS" stack status --json
```

Use the reported web URL for browser tests and HTTP requests. Do not assume port `3000` or call a backend port directly.

`up` prepares local environment files and dependencies, starts isolated infrastructure, applies migrations, and reconciles background application services. Existing secrets stay private. Ask for a model key only when the requested test needs one.

Run a slow startup in a background terminal when available. Wait for its exit and inspect status before reporting success.

Read `"$ODS" stack up --help` before choosing a different profile:

- `minimal` runs web and API for UI/API work.
- `default` adds the workers needed for ordinary indexing and background tasks.
- `full` runs the full launch compound for integration work.

Use `--local-model-server` only when changing model-server code. Other profiles use Compose inference and avoid a duplicate local model process.
Repeat the profile and local-model flag with `start` or `restart`. Use `up` to change model mode or recover infrastructure.

## Multiple agents

- Agents in the same worktree share one stack. Reuse a healthy stack through `up` and `status`.
- Different worktrees get separate state, ports, Compose projects, databases, queues, indexes, and object storage.
- ODS persists port assignments and changes them only when necessary. Read status again after a restart.
- A worktree lock coordinates lifecycle changes within that worktree. Other worktrees can start independently.
- Do not stop another worktree's services or kill unrelated processes to free a port.
- Keep `.vscode/.env` and `.vscode/.env.web` untracked. Do not print their contents.

Do not share writable databases or queues between branches. Treat shared model services as an explicit option, never an automatic fallback.

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
Use disposable worktrees for these tests. They create accounts, change the default test LLM provider, and stop services.
The browser smoke configuration supports an unlicensed local deployment. Its chat checks use a scripted local LLM, not a paid model key.
Never reset a developer database to satisfy a test fixture.

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
