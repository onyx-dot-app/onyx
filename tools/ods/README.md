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

- **GitHub CLI** (`gh`) - Required for `run-ci` and `cherry-pick` commands
  - Install from [cli.github.com](https://cli.github.com/)
  - Authenticate with `gh auth login`

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
