---
name: onyx-dev-stack
description: Start, inspect, restart, or stop the local Onyx development stack from a source checkout. Use for clean worktree setup, local Compose infrastructure, environment files, migrations, and background services. Do not use for Kubernetes development.
---

# Onyx dev stack

Run commands from the current worktree root. Do not open an editor to launch services.

The helper uses `ods` for setup, Compose, migrations, and the web server. It reads Python service commands from `.vscode/launch.json`.

## Rules

- Keep `.vscode/.env` and `.vscode/.env.web` untracked.
- Never print, commit, or replace an existing secret.
- Use the current worktree's Compose project.
- Preserve database and index volumes during a normal stop.
- Do not delete volumes unless the user explicitly requests a data reset.
- Do not kill a process that the helper did not start.
- Use this helper on macOS or Linux. It fails closed on Windows.
- Select available application ports and leave unrelated processes running.

Set the helper path once:

```bash
DEV_STACK=.agents/skills/onyx-dev-stack/scripts/dev_stack.py
```

## Start from an empty worktree

Check the required system tools:

```bash
command -v uv
command -v bun
command -v docker
docker info >/dev/null
```

Stop and report the missing prerequisite if a command fails. Do not install system software without a user request.

Start the stack:

```bash
python3 "$DEV_STACK" up
```

`up` performs these actions:

1. It creates missing environment files from the tracked templates.
2. It converts environment symlinks into worktree-local files before `ods env` updates ports.
3. It runs `uv sync --frozen` so backend dependencies match the lockfile.
4. It starts isolated infrastructure with `ods compose dev --infra`.
5. It writes the current Compose ports with `ods env`.
6. It applies migrations with `ods db upgrade`.
7. It starts the application processes in the background.
8. It waits for `/api/auth/type` on the selected web port to return HTTP 200.

The helper keeps process state and logs inside this worktree's Git metadata. Multiple agents in one worktree share that state.

A host lock prevents concurrent lifecycle operations across worktrees. Each worktree also gets a unique Compose project name.

The helper selects available web, API, MCP, and model ports after infrastructure starts. It stores them in worktree state.

It updates the frontend proxy, model connection, MCP connection, and login callback URL for these ports. Read `status` for the actual URL.

The Slack bot has a hardcoded metrics port at `8000`. The helper skips this optional process if that port is occupied.

Add a model key only when the task needs model-backed behavior. Prefer `GEN_AI_API_KEY` in `.vscode/.env`. Never echo its value.

## Inspect a running stack

Show process and readiness state:

```bash
python3 "$DEV_STACK" status
```

Show recent logs for all services:

```bash
python3 "$DEV_STACK" logs
```

Follow one service log:

```bash
python3 "$DEV_STACK" logs --service "API Server" --follow
```

Use the exact launch configuration name with `--service`.

Print the resolved background commands without starting them:

```bash
python3 "$DEV_STACK" print-commands
```

## Stop or restart

Stop only the background application processes. Keep infrastructure running for a quick restart:

```bash
python3 "$DEV_STACK" stop
```

Stop the application processes and Compose infrastructure:

```bash
python3 "$DEV_STACK" down
```

`down` uses `ods compose dev --down`. It preserves named volumes.

Restart only the application processes:

```bash
python3 "$DEV_STACK" restart
```

## Diagnose failures

- Run `status`, then inspect the failed service log.
- Report skipped optional services. Do not kill unrelated processes to free ports.
- Run `up` again after an interrupted setup. It replaces a partial managed start.
- Run `up` after Compose recreates containers or after pulling migrations.
- Ask for a required secret. Do not skip the affected verification.

The full launch compound includes the Slack bot. Missing Slack credentials can stop that process while the web application remains usable. Report that state instead of fabricating credentials.
