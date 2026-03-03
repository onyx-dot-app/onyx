# Onyx CLI

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
onyx configure
```

This prompts for your Onyx server URL and API key, tests the connection, and saves config to `~/.config/onyx-cli/config.json`.

Environment variables override config file values:

| Variable | Required | Description |
|----------|----------|-------------|
| `ONYX_SERVER_URL` | No | Server base URL (default: `http://localhost:3000`) |
| `ONYX_API_KEY` | Yes | API key for authentication |
| `DANSWER_API_KEY` | No | Legacy fallback for `ONYX_API_KEY` |
| `ONYX_PERSONA_ID` | No | Default agent/persona ID |

## Usage

### Interactive chat (default)

```shell
onyx
```

### One-shot question

```shell
onyx ask "What is our company's PTO policy?"
onyx ask --agent-id 5 "Summarize this topic"
onyx ask --json "Hello"
```

| Flag | Description |
|------|-------------|
| `--agent-id <int>` | Agent ID to use (overrides default) |
| `--json` | Output raw NDJSON events instead of plain text |

### List agents

```shell
onyx agents
onyx agents --json
```

## Commands

| Command | Description |
|---------|-------------|
| `chat` | Launch the interactive chat TUI (default) |
| `ask` | Ask a one-shot question (non-interactive) |
| `agents` | List available agents |
| `configure` | Configure server URL and API key |

## Slash Commands (in TUI)

| Command | Description |
|---------|-------------|
| `/help` | Show help message |
| `/new` | Start a new chat session |
| `/agent` | List and switch agents |
| `/attach <path>` | Attach a file to next message |
| `/sessions` | List recent chat sessions |
| `/clear` | Clear the chat display |
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
go build -o onyx .
```

## Development

```shell
# Run tests
go test ./...

# Build
go build -o onyx .

# Lint
staticcheck ./...
```
