# Onyx CLI

[![Release CLI](https://github.com/onyx-dot-app/onyx/actions/workflows/release-cli.yml/badge.svg)](https://github.com/onyx-dot-app/onyx/actions/workflows/release-cli.yml)
[![PyPI](https://img.shields.io/pypi/v/onyx-cli.svg)](https://pypi.org/project/onyx-cli/)

A terminal interface for chatting with your [Onyx](https://github.com/onyx-dot-app/onyx) agent. Built with Go using [Bubble Tea](https://github.com/charmbracelet/bubbletea) for the TUI framework.

## Installation

```shell
pip install onyx-cli
```

Or with uv:

```shell
uv pip install onyx-cli
```

## Setup

Run the interactive setup:

```shell
onyx-cli configure
```

This prompts for your Onyx server URL and API key, tests the connection, and saves config to `~/.config/onyx-cli/config.json`.

Environment variables override config file values:

| Variable | Required | Description |
|----------|----------|-------------|
| `ONYX_SERVER_URL` | No | Server base URL (default: `https://cloud.onyx.app`) |
| `ONYX_API_KEY` | Yes | API key for authentication |
| `ONYX_PERSONA_ID` | No | Default agent/persona ID |

## Usage

### Interactive chat (default)

```shell
onyx-cli
```

### One-shot question

```shell
onyx-cli ask "What is our company's PTO policy?"
onyx-cli ask --agent-id 5 "Summarize this topic"
onyx-cli ask --json "Hello"
```

| Flag | Description |
|------|-------------|
| `--agent-id <int>` | Agent ID to use (overrides default) |
| `--json` | Output raw NDJSON events instead of plain text |

### List agents

```shell
onyx-cli agents
onyx-cli agents --json
```

## Commands

| Command | Description |
|---------|-------------|
| `chat` | Launch the interactive chat TUI (default) |
| `ask` | Ask a one-shot question (non-interactive) |
| `agents` | List available agents |
| `configure` | Configure server URL and API key |
| `validate-config` | Validate configuration and test connection |

## Slash Commands (in TUI)

| Command | Description |
|---------|-------------|
| `/help` | Show help message |
| `/clear` | Clear chat and start a new session |
| `/agent` | List and switch agents |
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
staticcheck ./...
```

## Publishing to PyPI

The CLI is distributed as a Python package via [PyPI](https://pypi.org/project/onyx-cli/). The build system uses [hatchling](https://hatch.pypa.io/) with [manygo](https://github.com/nicholasgasior/manygo) to cross-compile Go binaries into platform-specific wheels.

### CI release (recommended)

Tag a release and push — the `release-cli.yml` workflow builds wheels for all platforms and publishes to PyPI automatically:

```shell
tag --prefix cli
```

To do this manually:

```shell
git tag cli/v0.1.0
git push origin cli/v0.1.0
```

The workflow builds wheels for: linux/amd64, linux/arm64, darwin/amd64, darwin/arm64, windows/amd64, windows/arm64.

### Manual release

Build a wheel locally with `uv`. Set `GOOS` and `GOARCH` to cross-compile for other platforms (Go handles this natively — no cross-compiler needed):

```shell
# Build for current platform
uv build --wheel

# Cross-compile for a different platform
GOOS=linux GOARCH=amd64 uv build --wheel

# Upload to PyPI
uv publish
```

### Versioning

Versions are derived from git tags with the `cli/` prefix (e.g. `cli/v0.1.0`). The tag is parsed by `internal/_version.py` and injected into the Go binary via `-ldflags` at build time.
