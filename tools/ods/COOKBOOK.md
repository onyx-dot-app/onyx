# `ods` Cookbook

Task-oriented recipes for the Onyx Developer Script (`ods`). Where the
[README](./README.md) is the command reference ("what does this flag do?"), this
cookbook is the answer to "how do I _do_ X?". Each recipe is a short, copy-pasteable
workflow built from one or more commands.

> **Prerequisites.** Most recipes assume you have `ods` on your `PATH` (activate the
> repo venv with `source .venv/bin/activate`) and Docker running. Recipes that touch
> GitHub, S3, or Kubernetes call out the extra tooling (`gh`, `aws`, `kubectl`) they
> need. See the [README Prerequisites](./README.md#prerequisites) for install links.

---

## Table of contents

- [Spinning up a local stack](#spinning-up-a-local-stack)
- [Running backend & frontend outside Docker](#running-backend--frontend-outside-docker)
- [Working in the devcontainer](#working-in-the-devcontainer)
- [Database recipes](#database-recipes)
- [Reading logs & debugging](#reading-logs--debugging)
- [Running multiple worktrees side-by-side](#running-multiple-worktrees-side-by-side)
- [Cherry-picking & release work](#cherry-picking--release-work)
- [Running CI on a fork PR](#running-ci-on-a-fork-pr)
- [Debugging Playwright failures](#debugging-playwright-failures)
- [Visual regression testing](#visual-regression-testing)
- [OpenAPI schema & client](#openapi-schema--client)
- [Deployments](#deployments)
- [Operations & lookups](#operations--lookups)
- [Project housekeeping](#project-housekeeping)
- [Troubleshooting](#troubleshooting)

---

## Spinning up a local stack

### Recipe: First-time local startup (everything in Docker)

```bash
ods compose dev        # start all services with the dev profile (ports exposed)
```

The `dev` profile layers `docker-compose.dev.yml` on top of the base file, which
exposes each service's port on the host and starts MinIO (the `s3-filestore`
profile). Enterprise Edition features are on by default. `ods` waits for every
service to report healthy before returning.

Want to disable EE features?

```bash
ods compose dev --no-ee
```

### Recipe: Start only the infrastructure (DB, cache, search, model server)

Useful when you plan to run the API server and/or web frontend yourself (see the
[next section](#running-backend--frontend-outside-docker)):

```bash
ods compose dev --infra
```

### Recipe: Run a specific image tag

```bash
ods pull --tag edge      # pull the edge images
ods compose --tag edge   # start them
```

### Recipe: Recreate containers after a config change

```bash
ods compose --force-recreate
```

### Recipe: Tear down

```bash
ods compose dev --down   # stop the dev-profile containers
```

---

## Running backend & frontend outside Docker

Running the API server, model server, or web app **on the host** (rather than in a
container) gives you hot-reload and a debugger. The pattern is: start infra in
Docker, sync ports into `.vscode/.env`, then launch the process.

### Recipe: Run the API server with hot-reload

```bash
ods compose dev --infra   # 1. infra only
ods env                   # 2. sync container host-ports into .vscode/.env
ods backend api           # 3. uvicorn onyx.main:app --reload on :8080
```

`ods backend api` reads `.vscode/.env` (creating it from `.vscode/env_template.txt`
on first run) and merges it with your shell env — **shell vars win**. Pick a
different port with `--port 9090`; if the port is taken, `ods` auto-increments.

### Recipe: Run the model server

```bash
ods backend model_server          # uvicorn model_server.main:app --reload on :9000
ods backend model_server --port 9001
```

### Recipe: Run the Next.js dev server

```bash
ods web dev               # bun run dev in web/
```

`ods web` runs any script from `web/package.json` via `bun` (and runs
`bun install --frozen-lockfile` first if `node_modules` is missing). Other handy
scripts:

```bash
ods web lint
ods web test --watch      # args after the script name are forwarded
```

### Recipe: Run the Electron desktop app

```bash
ods desktop dev           # npm run dev in desktop/
ods desktop build:dmg     # build a macOS DMG
```

`ods desktop` is the `npm` analogue of `ods web`, scoped to `desktop/package.json`.

---

## Working in the devcontainer

The `ods dev` group (alias `ods dc`) wraps the `devcontainer` CLI with
workspace-aware defaults (SSH-agent forwarding, worktree `.git` mounts, rootless
Docker detection). Requires the
[`devcontainer` CLI](https://github.com/devcontainers/cli).

### Recipe: Start and enter the devcontainer

```bash
ods dev up                # start (pulls the image if needed)
ods dev into              # open a zsh shell inside it
```

### Recipe: Run a one-off command inside the container

```bash
ods dev exec bun test
ods dev exec -- ls -la /workspace   # use -- when the command has its own flags
```

### Recipe: Pick the right reset

| You want to…                                              | Use               | What it does                           |
| --------------------------------------------------------- | ----------------- | -------------------------------------- |
| apply `devcontainer.json` changes / get a clean container | `ods dev restart` | recreate container, reuse cached image |
| pick up the newest published image                        | `ods dev rebuild` | `docker pull` then recreate            |
| stop for now                                              | `ods dev stop`    | stop without removing                  |

### Recipe: Reach a port inside the devcontainer from the host

The devcontainer denies inbound connections by default. Tunnel through it with
`socat`:

```bash
ods dev tunnel 8080         # expose container :8080 on host :8080
ods dev tunnel 9000:8080    # expose container :8080 on host :9000
```

Runs in the foreground; Ctrl-C tears the tunnel down.

---

## Database recipes

All `ods db` subcommands locate the running Postgres container automatically by
project name (see [worktrees](#running-multiple-worktrees-side-by-side)).

### Recipe: Reset the database from scratch

```bash
ods db drop               # terminate connections, drop & recreate (asks first)
ods db upgrade            # re-run all Alembic migrations to head
```

Skip the prompt with `--yes`. Drop just one schema with `--schema public`.

### Recipe: Snapshot and restore

```bash
ods db dump                       # → ~/.local/share/onyx-dev/snapshots/onyx_<ts>.dump
ods db dump mybackup.dump         # named file in the snapshots dir
ods db dump /tmp/backup.sql --format sql

ods db restore mybackup.dump      # auto-detects format from extension
ods db restore backup.dump --clean  # drop existing objects before restoring
```

Bare filenames resolve against the snapshots dir first, then the current directory.

### Recipe: Load the shared pre-seeded database

```bash
ods db restore --fetch-seeded     # download s3://onyx-internal-tools/seeded.dump & restore
ods db restore --fetch-seeded --yes
```

### Recipe: Apply / roll back migrations

```bash
ods db upgrade                    # to head
ods db upgrade +1                 # one step forward
ods db downgrade -1               # one step back
ods db downgrade base             # all the way back

ods db current                    # which revision am I on?
ods db history --verbose          # full migration history
```

For the multi-tenant private schema, add `--schema private` to any of these.

> `ods db upgrade` auto-detects the container's IP when Postgres isn't exposed on a
> host port, so it works against `ods compose` (no `--infra`/`ods env` needed) as
> well as host-run setups.

---

## Reading logs & debugging

### Recipe: Tail logs

```bash
ods logs                          # stream every service
ods logs api_server               # one service
ods logs api_server background    # several services
ods logs --tail 100 api_server    # last 100 lines, then stream
ods logs --follow=false api_server  # dump and exit
```

> When running live tests (curl / Playwright) or writing integration tests, the
> Onyx services also tail to `backend/log/<service>_debug.log`.

### Recipe: Verbose `ods` output

Any command accepts the global `--debug` flag to log what `ods` is doing under the
hood (the exact `docker` / `git` / `gh` invocations):

```bash
ods compose dev --debug
```

---

## Running multiple worktrees side-by-side

`ods` derives the Docker Compose **project name** from the basename of your git
worktree root (lowercased, normalized). Two worktrees at `~/onyx` and
`~/onyx-feature-x` therefore get distinct project names (`onyx` and
`onyx-feature-x`) and **distinct container sets** — they don't collide.

When starting a `dev`/`multitenant` stack, `ods` scans for free host ports per
service and writes them to the compose `.env`. To point host-run processes at the
right ports for a given worktree:

```bash
ods env                       # sync ports for the current worktree's containers
ods env --dry-run             # preview the changes to .vscode/.env first
```

Override the project name explicitly with the global `--project` flag if you need
to target another worktree's stack:

```bash
ods logs --project onyx-feature-x api_server
ods db dump --project onyx-feature-x
```

---

## Cherry-picking & release work

`ods cherry-pick` (alias `ods cp`) stashes your working changes, creates a
`hotfix/<sha>-<version>` branch off `origin/release/<version>`, applies the
commits, pushes, and opens a labeled PR — then switches you back. Requires an
authenticated `gh`.

### Recipe: Cherry-pick a commit to a release

```bash
ods cherry-pick abc123 --release 2.5
```

### Recipe: Cherry-pick a merged PR (by number)

Numeric args under 6 digits are treated as PR numbers and resolved to their merge
commit automatically:

```bash
ods cp 1234 --release 2.5
```

### Recipe: Multiple commits and/or multiple releases

```bash
ods cherry-pick abc123 def456 --release 2.5 --release 2.6
```

### Recipe: Resume after a conflict

```bash
# ods stops on a conflict. Resolve it, then:
git add <resolved-files>
ods cherry-pick --continue
```

State is persisted in `.git/ods-cherry-pick-state`, so `--continue` knows the
branch, releases, and assignees from the original invocation.

### Recipe: Dry run first

```bash
ods cherry-pick abc123 --release 2.5 --dry-run   # all local steps, no push/PR
```

If you omit `--release`, `ods` auto-detects the nearest stable tag and asks for
confirmation. Set a default assignee with `--assignee you` or
`CHERRY_PICK_ASSIGNEE`.

---

## Running CI on a fork PR

GitHub Actions doesn't run the full suite on cross-repo (fork) PRs by default.
`ods run-ci` mirrors a fork's branch to an `origin` branch and opens an internal PR
so CI runs:

```bash
ods run-ci 7353            # mirror fork PR #7353 and open a CI PR
ods run-ci 7353 --rerun    # force-push latest fork changes to re-trigger CI
ods run-ci 7353 --dry-run  # everything except push + PR creation
```

---

## Debugging Playwright failures

`ods trace` downloads `trace.zip` artifacts from a GitHub Actions run and opens them
in the Playwright trace viewer. Requires `gh`.

```bash
ods trace                  # latest run for the current branch
ods trace --pr 9500        # latest run for a PR
ods trace --branch main    # latest run for a branch
ods trace 12345678         # a specific run ID
ods trace https://github.com/onyx-dot-app/onyx/actions/runs/12345678
```

Narrow and inspect:

```bash
ods trace --pr 9500 --project admin   # only the 'admin' test project
ods trace --pr 9500 --list            # list traces, don't open
```

When there are several traces, `ods` shows an interactive picker (arrows/`j`/`k` to
move, `space` to toggle, `a`/`n` select/deselect all, `Enter` to confirm). Downloads
are cached under `/tmp/ods-traces/<run-id>`.

---

## Visual regression testing

`ods screenshot-diff` compares Playwright screenshots against S3 baselines and
produces a self-contained HTML report plus a machine-readable `summary.json`.
Requires `aws` (`aws sso login`).

### Recipe: Compare local screenshots against the `main` baseline

```bash
ods screenshot-diff compare --project admin
```

`--project` sets sensible defaults: baseline from
`s3://<bucket>/baselines/admin/main/`, current from `web/output/screenshots/`,
report to `web/output/screenshot-diff/admin/index.html`.

### Recipe: Compare against a release baseline, or across two revisions

```bash
ods screenshot-diff compare --project admin --rev release/2.5
ods screenshot-diff compare --project admin --from-rev v1.0.0 --to-rev v2.0.0
```

Tune sensitivity with `--threshold` (per-channel, default `0.2`) and
`--max-diff-ratio` (default `0.01`).

### Recipe: Promote current screenshots to new baselines

```bash
ods screenshot-diff upload-baselines --project admin
ods screenshot-diff upload-baselines --project admin --rev release/2.5 --delete
```

---

## OpenAPI schema & client

Generate the FastAPI schema (without booting the server) and a Python client.
Requires the backend venv; client generation also needs `openapi-generator-cli`.

```bash
ods openapi schema        # → backend/generated/openapi.json
ods openapi client        # → backend/generated/onyx_openapi_client
ods openapi all           # both in one step
```

Override paths with `-o` / `-i` / `--client-output`.

---

## Deployments

`ods deploy` triggers ad-hoc deploys to Onyx-managed environments. Requires `gh`.
First run prompts for target repo/workflow and saves them to
`~/.config/onyx-dev/config.json`.

### Recipe: Deploy edge (off `origin/main`)

```bash
ods deploy edge                 # force-push edge tag, wait for build, dispatch deploy
ods deploy edge --dry-run       # preview
ods deploy edge --no-wait-deploy  # fire-and-forget the deploy step
```

### Recipe: Deploy the agent-wiki nightly

```bash
ods deploy wiki                 # build nightly image, deploy to dev-wiki.onyx.app
ods deploy wiki --no-build      # deploy today's existing image without rebuilding
```

A status message lands in `#monitor-deployments` on Slack.

---

## Operations & lookups

### Recipe: Find a user or tenant in the data plane

Requires AWS SSO login and `kubectl` access. The cluster connection comes from a
`KUBE_CTX_<NAME>` env var set to a `"cluster region namespace"` tuple.

```bash
ods whois chris                       # users whose email matches 'chris'
ods whois tenant_abcd1234-...         # list ADMIN emails for a tenant
ods whois chris -c control_plane      # use the KUBE_CTX_CONTROL_PLANE context
```

---

## Project housekeeping

### Recipe: Lint for eager heavy imports

Enforces that heavy modules (`openai`, `tiktoken`, `transformers`, `litellm`, …) are
imported lazily (inside functions), not at module top-level:

```bash
ods check-lazy-imports                # all of backend/
ods check-lazy-imports onyx/llm/      # scope to a subtree
```

Exits non-zero on a violation — suitable for pre-commit / CI.

### Recipe: Install the Onyx Claude Code skills

```bash
ods install-skill --clone        # clone onyx-llm-context from GitHub and install
ods install-skill --source /path/to/onyx-llm-context
ods install-skill --copy         # copy instead of symlink
```

Writes `@import` lines for enforced skills into `.claude/CLAUDE.md` and symlinks
manual skills into `~/.claude/skills/`.

### Recipe: Print the latest stable tag

```bash
ods latest-stable-tag             # highest non-pre-release semver tag
```

---

## Troubleshooting

**"Port 5432 is in use by … using available port 5433 instead."**
Not an error. `ods` found the default port busy, picked the next free one, and wrote
it into the compose and app `.env` files. Run `ods env` to sync host-run processes
to the new port.

**`ods db` / `ods compose` can't find the Postgres container.**
`ods` locates containers by project name (the worktree basename). If you started the
stack from a different directory or worktree, pass `--project <name>` to match, or
re-run from the right worktree.

**An `aws s3 …` step fails with a credentials error.**
Authenticate first: `aws sso login` (or `aws configure sso`). Affects
`screenshot-diff` and `db restore --fetch-seeded`.

**A `gh`-backed command fails.**
Ensure the GitHub CLI is installed and authenticated: `gh auth login`. Affects
`cherry-pick`, `run-ci`, `trace`, and `deploy`.

**`ods openapi` / `ods db upgrade` can't find `alembic`/`python`.**
Both prefer the repo's `.venv` (`.venv/bin/...`) and fall back to your `PATH`.
Activate the venv (`source .venv/bin/activate`) or create it per the project README.

**See exactly what `ods` is running.**
Add `--debug` to any command to log the underlying `docker` / `git` / `gh` calls.
