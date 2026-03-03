# Onyx CLI

A terminal interface for chatting with your [Onyx](https://github.com/onyx-dot-app/onyx) assistant. Built with Go using [Bubble Tea](https://github.com/charmbracelet/bubbletea) for the TUI framework.

## Installation

```bash
# From source
cd cli
go build -o onyx-cli .

# Or install directly
go install github.com/onyx-dot-app/onyx/cli@latest
```

## Usage

```bash
# Launch interactive chat (default)
./onyx-cli

# First-run setup
./onyx-cli configure

# One-shot question
./onyx-cli ask "What is Onyx?"
./onyx-cli ask --persona-id 5 "Summarize this topic"
./onyx-cli ask --json "Hello"
```

## Commands

| Command | Description |
|---------|-------------|
| `chat` | Launch the interactive chat TUI (default) |
| `ask` | Ask a one-shot question (non-interactive) |
| `configure` | Configure server URL and API key |

## Slash Commands (in TUI)

| Command | Description |
|---------|-------------|
| `/help` | Show help message |
| `/new` | Start a new chat session |
| `/persona` | List and switch assistants |
| `/attach <path>` | Attach a file to next message |
| `/sessions` | List recent chat sessions |
| `/resume <id>` | Resume a previous session |
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

## Configuration

Config is stored at `~/.config/onyx-cli/config.json`. Environment variables override file values:

| Variable | Description |
|----------|-------------|
| `ONYX_SERVER_URL` | Server URL |
| `ONYX_API_KEY` | API key |
| `DANSWER_API_KEY` | Legacy API key (fallback) |
| `ONYX_PERSONA_ID` | Default persona ID |

## Development

```bash
# Run tests
go test ./...

# Build
go build -o onyx-cli .
```
