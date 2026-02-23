# Onyx Developer Script

[![Deploy Status](https://github.com/onyx-dot-app/onyx/actions/workflows/release-devtools.yml/badge.svg)](https://github.com/onyx-dot-app/onyx/actions/workflows/release-devtools.yml)
[![PyPI](https://img.shields.io/pypi/v/onyx-devtools.svg)](https://pypi.org/project/onyx-devtools/)

`ods` is [onyx.app](https://github.com/onyx-dot-app/onyx)'s devtools utility script.
It is packaged as a python [wheel](https://packaging.python.org/en/latest/discussions/package-formats/) and available from [PyPI](https://pypi.org/project/onyx-devtools/).

## Installation

A stable version of `ods` is provided in the default [python venv](https://github.com/onyx-dot-app/onyx/blob/main/CONTRIBUTING.md#backend-python-requirements)
which is synced automatically if you have [pre-commit](https://github.com/onyx-dot-app/onyx/blob/main/CONTRIBUTING.md#formatting-and-linting)
hooks installed.

While inside the Onyx repository, activate the root project's venv,

```shell
source .venv/bin/activate
```

### Prerequisites

Some commands require external tools to be installed and configured:

- **Docker** - Required for `compose`, `logs`, and `pull` commands
  - Install from [docker.com](https://docs.docker.com/get-docker/)

- **GitHub CLI** (`gh`) - Required for `run-ci` and `cherry-pick` commands
  - Install from [cli.github.com](https://cli.github.com/)
  - Authenticate with `gh auth login`

- **AWS CLI** - Required for `screenshot-diff` commands (S3 baseline sync)
  - Install from [aws.amazon.com/cli](https://aws.amazon.com/cli/)
  - Authenticate with `aws sso login` or `aws configure`

### Autocomplete

`ods` provides autocomplete for `bash`, `fish`, `powershell` and `zsh` shells.

For more information, see `ods completion <shell> --help` for your respective `<shell>`.

#### zsh

_Linux_

```shell
ods completion zsh | sudo tee "${fpath[1]}/_ods" > /dev/null
```

_macOS_

```shell
ods completion zsh > $(brew --prefix)/share/zsh/site-functions/_ods
```

#### bash

```shell
ods completion bash | sudo tee /etc/bash_completion.d/ods > /dev/null
```

_Note: bash completion requires the [bash-completion](https://github.com/scop/bash-completion/) package be installed._

## Commands

### `compose` - Launch Docker Containers

Launch Onyx docker containers using docker compose.

```shell
ods compose [profile]
```

**Profiles:**

- `dev` - Use dev configuration (exposes service ports for development)
- `multitenant` - Use multitenant configuration

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--down` | `false` | Stop running containers instead of starting them |
| `--wait` | `true` | Wait for services to be healthy before returning |
| `--force-recreate` | `false` | Force recreate containers even if unchanged |
| `--tag` | | Set the `IMAGE_TAG` for docker compose (e.g. `edge`, `v2.10.4`) |

**Examples:**

```shell
# Start containers with default configuration
ods compose

# Start containers with dev configuration
ods compose dev

# Start containers with multitenant configuration
ods compose multitenant

# Stop running containers
ods compose --down
ods compose dev --down

# Start without waiting for services to be healthy
ods compose --wait=false

# Force recreate containers
ods compose --force-recreate

# Use a specific image tag
ods compose --tag edge
```

### `logs` - View Docker Container Logs

View logs from running Onyx docker containers. Service names are available as
arguments to filter output, with tab-completion support.

```shell
ods logs [service...]
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--follow` | `true` | Follow log output |
| `--tail` | | Number of lines to show from the end of the logs |

**Examples:**

```shell
# View logs from all services (follow mode)
ods logs

# View logs for a specific service
ods logs api_server

# View logs for multiple services
ods logs api_server background

# View last 100 lines and follow
ods logs --tail 100 api_server

# View logs without following
ods logs --follow=false
```

### `pull` - Pull Docker Images

Pull the latest images for Onyx docker containers.

```shell
ods pull
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--tag` | | Set the `IMAGE_TAG` for docker compose (e.g. `edge`, `v2.10.4`) |

**Examples:**

```shell
# Pull images
ods pull

# Pull images with a specific tag
ods pull --tag edge
```

### `db` - Database Administration

Manage PostgreSQL database dumps, restores, and migrations.

```shell
ods db <subcommand>
```

**Subcommands:**

- `dump` - Create a database dump
- `restore` - Restore from a dump
- `upgrade`/`downgrade` - Run database migrations
- `drop` - Drop a database

Run `ods db --help` for detailed usage.

### `openapi` - OpenAPI Schema Generation

Generate OpenAPI schemas and client code.

```shell
ods openapi all
```

### `check-lazy-imports` - Verify Lazy Import Compliance

Check that specified modules are only lazily imported (used for keeping backend startup fast).

```shell
ods check-lazy-imports
```

### `run-ci` - Run CI on Fork PRs

Pull requests from forks don't automatically trigger GitHub Actions for security reasons.
This command creates a branch and PR in the main repository to run CI on a fork's code.

```shell
ods run-ci <pr-number>
```

**Example:**

```shell
# Run CI for PR #7353 from a fork
ods run-ci 7353
```

### `cherry-pick` - Backport Commits to Release Branches

Cherry-pick one or more commits to release branches and automatically create PRs.

```shell
ods cherry-pick <commit-sha> [<commit-sha>...] [--release <version>]
```

**Examples:**

```shell
# Cherry-pick a single commit (auto-detects release version)
ods cherry-pick abc123

# Cherry-pick to a specific release
ods cherry-pick abc123 --release 2.5

# Cherry-pick to multiple releases
ods cherry-pick abc123 --release 2.5 --release 2.6

# Cherry-pick multiple commits
ods cherry-pick abc123 def456 ghi789 --release 2.5
```

### `screenshot-diff` - Visual Regression Testing

Compare Playwright screenshots against baselines and generate visual diff reports.
Baselines are stored per-project and per-revision in S3:

```
s3://<bucket>/baselines/<project>/<rev>/
```

This allows storing baselines for `main`, release branches (`release/2.5`), and
version tags (`v2.0.0`) side-by-side. Revisions containing `/` are sanitised to
`-` in the S3 path (e.g. `release/2.5` → `release-2.5`).

```shell
ods screenshot-diff <subcommand>
```

**Subcommands:**

- `compare` - Compare screenshots against baselines and generate a diff report
- `upload-baselines` - Upload screenshots to S3 as new baselines

The `--project` flag provides sensible defaults so you don't need to specify every path.
When set, the following defaults are applied:

| Flag | Default |
|------|---------|
| `--baseline` | `s3://onyx-playwright-artifacts/baselines/<project>/<rev>/` |
| `--current` | `web/output/screenshots/` |
| `--output` | `web/output/screenshot-diff/<project>/index.html` |
| `--rev` | `main` |

The S3 bucket defaults to `onyx-playwright-artifacts` and can be overridden with the
`PLAYWRIGHT_S3_BUCKET` environment variable.

**`compare` Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--project` | | Project name (e.g. `admin`); sets sensible defaults |
| `--rev` | `main` | Revision baseline to compare against |
| `--from-rev` | | Source (older) revision for cross-revision comparison |
| `--to-rev` | | Target (newer) revision for cross-revision comparison |
| `--baseline` | | Baseline directory or S3 URL (`s3://...`) |
| `--current` | | Current screenshots directory or S3 URL (`s3://...`) |
| `--output` | `screenshot-diff/index.html` | Output path for the HTML report |
| `--threshold` | `0.2` | Per-channel pixel difference threshold (0.0–1.0) |
| `--max-diff-ratio` | `0.01` | Max diff pixel ratio before marking as changed |

**`upload-baselines` Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--project` | | Project name (e.g. `admin`); sets sensible defaults |
| `--rev` | `main` | Revision to store the baseline under |
| `--dir` | | Local directory containing screenshots to upload |
| `--dest` | | S3 destination URL (`s3://...`) |
| `--delete` | `false` | Delete S3 files not present locally |

**Examples:**

```shell
# Compare local screenshots against the main baseline (default)
ods screenshot-diff compare --project admin

# Compare against a release branch baseline
ods screenshot-diff compare --project admin --rev release/2.5

# Compare two revisions directly (both sides fetched from S3)
ods screenshot-diff compare --project admin --from-rev v1.0.0 --to-rev v2.0.0

# Compare with explicit paths
ods screenshot-diff compare \
  --baseline ./baselines \
  --current ./web/output/screenshots/ \
  --output ./report/index.html

# Upload baselines for main (default)
ods screenshot-diff upload-baselines --project admin

# Upload baselines for a release branch
ods screenshot-diff upload-baselines --project admin --rev release/2.5

# Upload baselines for a version tag
ods screenshot-diff upload-baselines --project admin --rev v2.0.0

# Upload with delete (remove old baselines not in current set)
ods screenshot-diff upload-baselines --project admin --delete
```

The `compare` subcommand writes a `summary.json` alongside the report with aggregate
counts (changed, added, removed, unchanged). The HTML report is only generated when
visual differences are detected.

### Testing Changes Locally (Dry Run)

Both `run-ci` and `cherry-pick` support `--dry-run` to test without making remote changes:

```shell
# See what would happen without pushing
ods run-ci 7353 --dry-run
ods cherry-pick abc123 --release 2.5 --dry-run
```

## Upgrading

To upgrade the stable version, upgrade it as you would any other [requirement](https://github.com/onyx-dot-app/onyx/tree/main/backend/requirements#readme).

## Building from source

Generally, `go build .` or `go install .` are sufficient.

`go build .` will output a `tools/ods/ods` binary which you can call normally,

```shell
./ods --version
```

while `go install .` will output to your [GOPATH](https://go.dev/wiki/SettingGOPATH) (defaults `~/go/bin/ods`),

```shell
~/go/bin/ods --version
```

_Typically, `GOPATH` is added to your shell's `PATH`, but this may be confused easily during development
with the pip version of `ods` installed in the Onyx venv._

To build the wheel,

```shell
uv build --wheel
```

To build and install the wheel,

```shell
uv pip install .
```

## Deploy

Releases are deployed automatically when git tags prefaced with `ods/` are pushed to [GitHub](https://github.com/onyx-dot-app/onyx/tags).

The [release-tag](https://pypi.org/project/release-tag/) package can be used to calculate and push the next tag automatically,

```shell
tag --prefix ods
```

See also, [`.github/workflows/release-devtools.yml`](https://github.com/onyx-dot-app/onyx/blob/main/.github/workflows/release-devtools.yml).
