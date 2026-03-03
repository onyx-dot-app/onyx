---
name: onyx-cli
description: Query the Onyx knowledge base using the onyx command. Use when the user wants to search company documents, ask questions about internal knowledge, query connected data sources, or look up information stored in Onyx.
---

# Onyx CLI — Agent Tool

Onyx is an enterprise search and Gen-AI platform that connects to company documents, apps, and people. The `onyx` CLI provides non-interactive commands to query the Onyx knowledge base and list available agents.

## Prerequisites

### 1. Check if installed

```bash
which onyx
```

### 2. Install (if needed)

**Primary — pip:**

```bash
pip install onyx-cli
```

**From source (Go):**

```bash
cd cli && go build -o onyx . && sudo mv onyx /usr/local/bin/
```

### 3. Check if configured

The CLI is configured when `~/.config/onyx-cli/config.json` exists and contains an `api_key`. Check with:

```bash
cat ~/.config/onyx-cli/config.json 2>/dev/null
```

If unconfigured, you have two options:

**Option A — Interactive setup (requires user input):**

```bash
onyx configure
```

This prompts for the Onyx server URL and API key, tests the connection, and saves config.

**Option B — Environment variables (non-interactive, preferred for agents):**

```bash
export ONYX_SERVER_URL="https://your-onyx-server.com"  # default: http://localhost:3000
export ONYX_API_KEY="your-api-key"
```

Environment variables override the config file. If these are set, no config file is needed.

| Variable | Required | Description |
|----------|----------|-------------|
| `ONYX_SERVER_URL` | No | Onyx server base URL (default: `http://localhost:3000`) |
| `ONYX_API_KEY` | Yes | API key for authentication |
| `DANSWER_API_KEY` | No | Legacy fallback for `ONYX_API_KEY` |
| `ONYX_PERSONA_ID` | No | Default agent/persona ID |

If neither the config file nor environment variables are set, tell the user that `onyx` needs to be configured and ask them to either:
- Run `onyx configure` interactively, or
- Set `ONYX_SERVER_URL` and `ONYX_API_KEY` environment variables

## Commands

### List available agents

```bash
onyx agents
```

Prints a table of agent IDs, names, and descriptions. Use `--json` for structured output:

```bash
onyx agents --json
```

Use agent IDs with `ask --agent-id` to query a specific agent.

### Basic query (plain text output)

```bash
onyx ask "What is our company's PTO policy?"
```

Streams the answer as plain text to stdout. Exit code 0 on success, non-zero on error.

### JSON output (structured events)

```bash
onyx ask --json "What authentication methods do we support?"
```

Outputs NDJSON (one JSON object per line). Key event types:

| Event Type | Description |
|------------|-------------|
| `MessageDeltaEvent` | Content token — concatenate all `content` fields for the full answer |
| `StopEvent` | Stream complete |
| `ErrorEvent` | Error with `error` message field |
| `SearchStartEvent` | Onyx started searching documents |
| `CitationEvent` | Source citation with `citation_number` and `document_id` |

### Specify an agent

```bash
onyx ask --agent-id 5 "Summarize our Q4 roadmap"
```

Uses a specific Onyx agent/persona instead of the default.

### All flags

| Flag | Type | Description |
|------|------|-------------|
| `--agent-id` | int | Agent ID to use (overrides default) |
| `--json` | bool | Output raw NDJSON events instead of plain text |

## When to Use

Use `onyx ask` when:

- The user asks about company-specific information (policies, docs, processes)
- You need to search internal knowledge bases or connected data sources
- The user references Onyx, asks you to "search Onyx", or wants to query their documents
- You need context from company wikis, Confluence, Google Drive, Slack, or other connected sources

Do NOT use when:

- The question is about general programming knowledge (use your own knowledge)
- The user is asking about code in the current repository (use grep/read tools)
- The user hasn't mentioned Onyx and the question doesn't require internal company data

## Examples

```bash
# Simple question
onyx ask "What are the steps to deploy to production?"

# Get structured output for parsing
onyx ask --json "List all active API integrations"

# Use a specialized agent
onyx ask --agent-id 3 "What were the action items from last week's standup?"

# Pipe the answer into another command
onyx ask "What is the database schema for users?" | head -20
```
