---
name: onyx-cli
description: Query the Onyx knowledge base using the onyx-cli command. Use when the user wants to search company documents, ask questions about internal knowledge, query connected data sources, or look up information stored in Onyx.
---

# Onyx CLI — Agent Tool

Onyx is an enterprise search and Gen-AI platform that connects to company documents, apps, and people. The `onyx-cli` CLI provides non-interactive commands to query the Onyx knowledge base and list available agents.

## Prerequisites

### 1. Check if installed

```bash
which onyx-cli
```

### 2. Install (if needed)

**Primary — pip:**

```bash
pip install onyx-cli
```

**From source (Go):**

```bash
cd cli && go build -o onyx-cli . && sudo mv onyx-cli /usr/local/bin/
```

### 3. Check if configured

```bash
onyx-cli validate-config
```

This checks the config file exists, API key is present, and tests the server connection via `/api/me`. Exit code 0 on success, non-zero with a descriptive error on failure.

If unconfigured, you have two options:

**Option A — Interactive setup (requires user input):**

```bash
onyx-cli configure
```

This prompts for the Onyx server URL and API key, tests the connection, and saves config.

**Option B — Environment variables (non-interactive, preferred for agents):**

```bash
export ONYX_SERVER_URL="https://your-onyx-server.com"  # default: https://cloud.onyx.app
export ONYX_API_KEY="your-api-key"
```

Environment variables override the config file. If these are set, no config file is needed.

| Variable | Required | Description |
|----------|----------|-------------|
| `ONYX_SERVER_URL` | No | Onyx server base URL (default: `https://cloud.onyx.app`) |
| `ONYX_API_KEY` | Yes | API key for authentication |
| `ONYX_PERSONA_ID` | No | Default agent/persona ID |

If neither the config file nor environment variables are set, tell the user that `onyx-cli` needs to be configured and ask them to either:
- Run `onyx-cli configure` interactively, or
- Set `ONYX_SERVER_URL` and `ONYX_API_KEY` environment variables

## Commands

### Validate configuration

```bash
onyx-cli validate-config
```

Checks config file exists, API key is present, and tests the server connection. Use this before `ask` or `agents` to confirm the CLI is properly set up.

### List available agents

```bash
onyx-cli agents
```

Prints a table of agent IDs, names, and descriptions. Use `--json` for structured output:

```bash
onyx-cli agents --json
```

Use agent IDs with `ask --agent-id` to query a specific agent.

### Basic query (plain text output)

```bash
onyx-cli ask "What is our company's PTO policy?"
```

Streams the answer as plain text to stdout. Exit code 0 on success, non-zero on error.

### JSON output (structured events)

```bash
onyx-cli ask --json "What authentication methods do we support?"
```

Outputs JSON-encoded parsed stream events (one object per line). Key event objects include message deltas, stop, errors, search-start, and citation payloads.

Each line is a JSON object with this envelope:

```json
{"type": "<event_type>", "event": { ... }}
```

| Event Type | Description |
|------------|-------------|
| `message_delta` | Content token — concatenate all `content` fields for the full answer |
| `stop` | Stream complete |
| `error` | Error with `error` message field |
| `search_tool_start` | Onyx started searching documents |
| `citation_info` | Source citation — see shape below |

`citation_info` event shape:

```json
{
  "type": "citation_info",
  "event": {
    "citation_number": 1,
    "document_id": "abc123def456",
    "placement": {"turn_index": 0, "tab_index": 0, "sub_turn_index": null}
  }
}
```

`placement` is metadata about where in the conversation the citation appeared and can be ignored for most use cases.

### Specify an agent

```bash
onyx-cli ask --agent-id 5 "Summarize our Q4 roadmap"
```

Uses a specific Onyx agent/persona instead of the default.

### All flags

| Flag | Type | Description |
|------|------|-------------|
| `--agent-id` | int | Agent ID to use (overrides default) |
| `--json` | bool | Output raw NDJSON events instead of plain text |

## Statelessness

Each `onyx-cli ask` call creates an independent chat session. There is no built-in way to chain context across multiple `ask` invocations — every call starts fresh. If you need multi-turn conversation with memory, use the interactive TUI (`onyx-cli` or `onyx-cli chat`) instead.

## When to Use

Use `onyx-cli ask` when:

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
onyx-cli ask "What are the steps to deploy to production?"

# Get structured output for parsing
onyx-cli ask --json "List all active API integrations"

# Use a specialized agent
onyx-cli ask --agent-id 3 "What were the action items from last week's standup?"

# Pipe the answer into another command
onyx-cli ask "What is the database schema for users?" | head -20
```
