# Run all Onyx services from the CLI (k8s mode)

`scripts/run-all-k8s.sh` is the command-line equivalent of the **Run All Onyx
Services (k8s)** compound launch config in `.vscode/launch.json`. Use it when
you want to bring up the full stack without VS Code — for example from a
plain terminal, a tmux session, or another agent's shell.

For the VS Code debugger path, use `local-kubernetes.md` instead.

## What it runs

The script does what the compound launch does: the
`k8s: telepresence intercept api_server` preLaunchTask, then 10 services in
parallel:

- `web_server` — `bun run dev` in `web/`
- `api_server` — `uvicorn onyx.main:app --reload --port 8080`
- `celery_primary`, `celery_light`, `celery_heavy`,
  `celery_docfetching`, `celery_docprocessing`,
  `celery_user_file_processing`, `celery_scheduled_tasks`,
  `celery_beat` — each via `backend/scripts/dev_celery_reload.py`

Each service writes to `log/<service>.log` at the repo root (gitignored).
`Ctrl-C` kills them all.

## Prerequisites

Same as `local-kubernetes.md`:

- `kind-onyx-dev` kubectl context exists and the cluster is up
  (`deployment/helm/dev/k8s-up.sh`)
- Telepresence installed and either passwordless sudo configured or already
  connected via `telepresence connect -n onyx`
- `.venv` exists at the repo root (`uv sync`)
- `.vscode/.env.k8s` exists (copied from `.vscode/.env.k8s.template` with
  `GEN_AI_API_KEY` filled in)

The script auto-injects `OPENSEARCH_ADMIN_PASSWORD` into `.env.k8s` by
reading the `onyx-opensearch` Secret, the same way the VS Code preLaunchTask
does.

## Usage

```bash
ods k8s up
```

Equivalent to running `scripts/run-all-k8s.sh` directly — `ods k8s up` is a
thin wrapper around it.

Watch logs in another terminal:

```bash
ods k8s logs                 # tail all 10 service logs
ods k8s logs api_server      # tail just one
```

Stop everything (useful when the "up" terminal was killed and orphaned
the services):

```bash
ods k8s down
```

## Differences vs. the VS Code launch

- **No debugpy attach.** Services run as plain processes — no breakpoints,
  no debugger. If you need to debug one service, run it via VS Code and the
  others via this script (or just don't start the duplicate process in the
  script).
- **No per-service terminal pane.** Output is redirected to log files. Use
  `ods k8s logs` to tail them.

## Worktree setup

If you're running this from a git worktree that doesn't have its own
`.venv` or `.env.k8s`, symlink them from the main repo:

```bash
ln -s ~/Documents/code/onyx/.venv         <worktree>/.venv
ln -s ~/Documents/code/onyx/.vscode/.env.k8s <worktree>/.vscode/.env.k8s
```

The script resolves `ROOT` from its own location (`$(dirname $0)/..`), so
copy or symlink the script into each worktree where you want to run it, or
just invoke it by absolute path from anywhere.

### Stale `.next/` after symlinking `node_modules`

If you also symlink `web/node_modules` between repos/worktrees, Next.js's
`.next/` dev cache can reference hashed module names from the *other* repo's
last build. Symptom in `log/web_server.log`:

```
Error: Cannot find module 'require-in-the-middle-<hash>'
error: script "dev" exited with code 1
```

Fix once, before running the script:

```bash
rm -rf web/.next
```

## Why this exists

VS Code does not expose compound launch configurations to the `code` CLI —
there's no `code --launch "<name>"` flag, and `vscode://` URIs don't accept
launch config names. The only way to bring up the full stack outside of the
VS Code Debug menu is to replicate the configs in a script.
