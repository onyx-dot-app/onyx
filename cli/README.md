# Onyx CLI

[![Release CLI](https://github.com/onyx-dot-app/onyx/actions/workflows/release-cli.yml/badge.svg)](https://github.com/onyx-dot-app/onyx/actions/workflows/release-cli.yml)
[![PyPI](https://img.shields.io/pypi/v/onyx-cli.svg)](https://pypi.org/project/onyx-cli/)

A CLI for querying enterprise knowledge from [Onyx](https://github.com/onyx-dot-app/onyx). Includes an interactive chat TUI for humans and non-interactive commands for AI agents and scripts.

## Installation

```shell
pip install onyx-cli
```

Or with uv:

```shell
uv pip install onyx-cli
```

Standalone binaries for Linux, macOS, and Windows (amd64/arm64) are also attached
to each [`cli/v*` GitHub release](https://github.com/onyx-dot-app/onyx/releases?q=cli%2Fv).

## Setup

Run the interactive chat TUI — on first launch it will guide you through setup:

```shell
onyx-cli chat
```

This prompts for your Onyx server URL and personal access token (PAT), tests the connection, and saves config to `~/.config/onyx-cli/config.json` (or `$XDG_CONFIG_HOME/onyx-cli/config.json` if set). To reconfigure later, use the `/configure` command inside the TUI.

Environment variables override config file values:

| Variable | Required | Description |
|----------|----------|-------------|
| `ONYX_SERVER_URL` | No | Server origin or already-prefixed API base (default: `https://cloud.onyx.app`) |
| `ONYX_API_PREFIX` | No | API path prefix (default: `/api`); set to empty for direct backend access |
| `ONYX_PAT` | No | Personal access token for authentication (required if no config file) |
| `ONYX_PERSONA_ID` | No | Default agent/persona ID |
| `ONYX_STREAM_MARKDOWN` | No | Enable/disable progressive markdown rendering (true/false) |
| `ONYX_SSH_HOST_KEY` | No | Path to SSH host key for `serve` command |

## Usage

### Interactive chat

```shell
onyx-cli chat
onyx-cli chat --no-stream-markdown
onyx-cli chat --agent-name "Support Agent"
```

| Flag | Description |
|------|-------------|
| `--no-stream-markdown` | Disable progressive markdown rendering during streaming |
| `--agent-id <int>` | Agent ID to use for this session |
| `--agent-name <string>` | Agent name to use for this session (exact or unique substring; mutually exclusive with `--agent-id`) |

### One-shot question

```shell
onyx-cli ask "What is our company's PTO policy?"
onyx-cli ask --agent-id 5 "Summarize this topic"
onyx-cli ask --agent-name "Support Agent" "hello"
onyx-cli ask --json "Hello"
```

| Flag | Description |
|------|-------------|
| `--agent-id <int>` | Agent ID to use (overrides default) |
| `--agent-name <string>` | Agent name to use (exact or unique substring; mutually exclusive with `--agent-id`) |
| `--json` | Output NDJSON stream events instead of plain text |
| `--prompt <string>` | Question text (use with piped stdin context) |
| `--quiet` | Buffer output and print once at end |
| `--max-output <int>` | Max bytes before truncating (0 to disable) |

### List agents

```shell
onyx-cli agents
onyx-cli agents --json
```

### Serve over SSH

```shell
# Start a public SSH endpoint for the CLI TUI
onyx-cli serve --host 0.0.0.0 --port 2222

# Connect as a client
ssh your-host -p 2222
```

Clients can either:
- paste a personal access token (PAT) at the login prompt, or
- skip the prompt by sending `ONYX_PAT` over SSH:

```shell
export ONYX_PAT=your-pat
ssh -o SendEnv=ONYX_PAT your-host -p 2222
```

Useful hardening flags:
- `--host-key` (default `~/.config/onyx-cli/host_ed25519`)
- `--idle-timeout` (default `15m`)
- `--max-session-timeout` (default `8h`)
- `--rate-limit-per-minute` (default `20`)
- `--rate-limit-burst` (default `40`)
- `--rate-limit-cache` (default `4096`)

## Commands

| Command | Mode | Description |
|---------|------|-------------|
| `chat` | Interactive | Launch the interactive chat TUI (requires terminal) |
| `ask` | Agent / Script | Ask a question and print the answer to stdout |
| `agents` | Agent / Script | List available agents (ID, name, description) |
| `validate-config` | Agent / Script | Check CLI configuration and server connectivity |
| `install-skill` | Agent / Script | Install the Onyx CLI agent skill file |
| `experiments` | Agent / Script | List experimental features and their status |
| `serve` | Interactive | Serve the Onyx TUI over SSH |

### Global Flags

| Flag | Description |
|------|-------------|
| `--version`, `-v` | Print client and server version information |
| `--debug` | Run in debug mode (verbose logging) |

## Agent / Non-Interactive Use

When called without a TTY (e.g., by an AI agent or piped into another command), onyx-cli adjusts its behavior:

- **No subcommand**: prints help and exits 0 (instead of launching the TUI)
- **Results to stdout**, progress/errors to stderr
- **No ANSI codes** or interactive prompts
- **`ask` output truncated** to 50000 bytes by default; full response saved to a temp file. Use `--max-output 0` to disable.
- **`search` stdout stays valid JSON**: over the limit, whole results are dropped and a `truncation` object carries metadata plus the temp file path of the full response.

### Configuration

If a human has already run `onyx-cli chat` (which includes first-time setup), the CLI works out of the box — no additional setup needed. Environment variables can override the config file or serve as an alternative when no config file exists:

```shell
export ONYX_SERVER_URL="https://your-onyx-server.com"
export ONYX_PAT="your-pat"
```

### Exit Codes

| Code | Name | When |
|------|------|------|
| 0 | Success | Command completed |
| 1 | General | Unknown error |
| 2 | BadRequest | Invalid arguments |
| 3 | NotConfigured | Missing config/PAT |
| 4 | AuthFailure | Invalid PAT (401/403) |
| 5 | Unreachable | Server unreachable |
| 6 | RateLimited | Server returned 429 |
| 7 | Timeout | Request timed out |
| 8 | ServerError | Server returned 5xx |
| 9 | NotAvailable | Feature/endpoint doesn't exist |

### Skill File

Install the bundled SKILL.md so AI coding agents can discover the CLI:

```shell
onyx-cli install-skill
onyx-cli install-skill --global
onyx-cli install-skill --copy
onyx-cli install-skill --agent claude-code
```

| Flag | Description |
|------|-------------|
| `--global`, `-g` | Install to home directory instead of project |
| `--copy` | Copy files instead of symlinking |
| `--agent`, `-a` | Target specific agents (e.g. `claude-code`; can be repeated) |

## Slash Commands (in TUI)

| Command | Description |
|---------|-------------|
| `/help` | Show help message |
| `/clear` | Clear chat and start a new session |
| `/agent` | List and switch agents (by ID or name) |
| `/attach <path>` | Attach a file to next message |
| `/sessions` | List recent chat sessions |
| `/configure` | Re-run connection setup |
| `/connectors` | Open connectors in browser |
| `/settings` | Open settings in browser |
| `/quit` | Exit Onyx CLI |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Escape` | Cancel current generation |
| `Ctrl+O` | Toggle source citations |
| `Ctrl+D` | Quit (press twice) |
| `Scroll` / `Shift+Up/Down` | Scroll chat history |
| `Page Up` / `Page Down` | Scroll half page |

## Building from Source

Requires [Go 1.24+](https://go.dev/dl/).

```shell
cd cli
go build -o onyx-cli .
```

## Development

```shell
# Run tests
go test ./...

# Build
go build -o onyx-cli .

# Lint
golangci-lint run ./...
```

## Publishing to PyPI

The CLI is distributed as a Python package via [PyPI](https://pypi.org/project/onyx-cli/). The build system uses [hatchling](https://hatch.pypa.io/) with [manygo](https://github.com/nicholasgasior/manygo) to cross-compile Go binaries into platform-specific wheels.

### CI release (recommended)

Tag a release and push — the `release-cli.yml` workflow builds wheels for all platforms and publishes to PyPI automatically. `ods release cli` calculates and pushes the next tag for you:

```shell
ods release cli              # bumps the patch version
ods release cli --bump minor
ods release cli --version 1.5.0
ods release cli --dry-run    # computes the version, tags nothing
```

To do this manually:

```shell
git tag cli/v0.1.0
git push origin cli/v0.1.0
```

> [!IMPORTANT]
> `ods release` tags **`HEAD`**, not `main`, and does not check which branch you
> are on. Compare `git rev-parse HEAD` with `git rev-parse origin/main` first.
> Tagging from a stale branch publishes that branch under the new version.

The workflow builds wheels for:

- linux/amd64 manylinux
- linux/amd64 musllinux
- linux/arm64 manylinux
- linux/arm64 musllinux
- darwin/amd64
- darwin/arm64
- windows/amd64
- windows/arm64

### Manual release

Build a wheel locally with `uv`. Set `GOOS` and `GOARCH` to cross-compile for other platforms (Go handles this natively — no cross-compiler needed):

```shell
# Build for current platform
uv build --wheel

# Cross-compile for a different platform
GOOS=linux GOARCH=amd64 uv build --wheel

# Build a musllinux-tagged Linux wheel for Alpine/musl environments
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 \
  ONYX_CLI_WHEEL_PLATFORM_TAG=musllinux_1_2_x86_64 \
  uv build --wheel

# Upload to PyPI
uv publish
```

### Build constraints

The release workflows build every wheel against
`tools/requirements/build-constraints.txt`, shared by `cli`, `tools/ods` and
`tools/ods-audit`. They pass it as `UV_BUILD_CONSTRAINT` with
`UV_REQUIRE_HASHES`, so the build environment (hatchling, `go-bin`, manygo and
their dependencies) is pinned and verified.

A plain local `uv build` resolves those dependencies freely. Set the same
variables to build against the pinned closure:

```shell
UV_BUILD_CONSTRAINT="$(git rev-parse --show-toplevel)/tools/requirements/build-constraints.txt" \
  UV_REQUIRE_HASHES=true GOTOOLCHAIN=local \
  uv build --wheel
```

`tools/requirements/build-constraints.txt` is compiled from its `.in` by the
`pip-compile` pre-commit hook, so a plain `pre-commit run pip-compile` refreshes
it. To upgrade a pinned build dependency, edit `build-constraints.in` and the
matching `[build-system] requires` in all three `pyproject.toml` files; the
`build-constraints-drift` hook fails if they disagree.

`go-bin` ships the Go toolchain used to compile the binary. Bumping Go means
moving it everywhere at once: the `go` directive in `go.mod`, `cli/Dockerfile`,
the `setup-go` and `GO_VERSION` pins across `.github/workflows/`,
`.devcontainer/Dockerfile`, the `go-bin` pin in all three `pyproject.toml` files
and in `tools/requirements/build-constraints.in`, and the compiled `build-constraints.txt`.

### Versioning

Versions are derived from git tags with the `cli/` prefix (e.g. `cli/v0.1.0`). The tag is parsed by `internal/_version.py` and injected into the Go binary via `-ldflags` at build time.
