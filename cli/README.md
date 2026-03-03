# Onyx CLI

Terminal UI for chatting with [Onyx](https://onyx.app) - your AI-powered enterprise search platform.

```
   ██████╗ ███╗   ██╗██╗   ██╗██╗  ██╗
  ██╔═══██╗████╗  ██║╚██╗ ██╔╝╚██╗██╔╝
  ██║   ██║██╔██╗ ██║ ╚████╔╝  ╚███╔╝
  ██║   ██║██║╚██╗██║  ╚██╔╝   ██╔██╗
  ╚██████╔╝██║ ╚████║   ██║   ██╔╝ ██╗
   ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝
```

## Install

```bash
pip install onyx-cli
```

Or run from source:

```bash
cd cli
uv sync
uv run onyx-cli
```

## Quick Start

```bash
# Launch the interactive TUI
onyx-cli

# Configure connection settings
onyx-cli configure

# One-shot question (non-interactive)
onyx-cli ask "What is our company's PTO policy?"
```

On first launch, Onyx CLI will guide you through connecting to your Onyx server.

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/new` | Start a new conversation |
| `/persona` | List and switch assistants |
| `/attach <path>` | Attach a file |
| `/sessions` | List recent sessions |
| `/resume <id>` | Resume a previous session |
| `/configure` | Change connection settings |
| `/connectors` | Open connectors page in browser |
| `/settings` | Open Onyx settings in browser |
| `/quit` | Exit |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Escape` | Cancel current generation |
| `Ctrl+D` | Quit (press twice) |

## Configuration

Config is stored at `~/.config/onyx-cli/config.json`. Environment variables override file values:

| Variable | Description |
|----------|-------------|
| `ONYX_SERVER_URL` | Server URL (default: `http://localhost:3000`) |
| `ONYX_API_KEY` | API key or Personal Access Token |
| `DANSWER_API_KEY` | Legacy API key (fallback) |
| `ONYX_PERSONA_ID` | Default assistant ID |

## Development

```bash
cd cli
uv sync
uv run pytest tests/unit -xv
```
