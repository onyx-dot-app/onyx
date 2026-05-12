---
name: onyx-cli
description: Query the Onyx knowledge base using the onyx-cli command. Use when the user wants to search company documents, ask questions about internal knowledge, query connected data sources, or look up information stored in Onyx.
---

# Onyx CLI — Agent Tool

`onyx-cli` is an agent's interface to the Onyx enterprise knowledge platform. It connects to company documents, apps, and people. Use it to answer questions that require internal knowledge — policies, docs, processes, data from connected sources (Confluence, Google Drive, Slack, etc.).

## Prerequisites

### 1. Check if installed

```bash
which onyx-cli
```

### 2. Install (if needed)

```bash
pip install onyx-cli
```

### 3. Check if configured

If a human has already run `onyx-cli chat` (which includes first-time setup), the CLI is ready — no additional setup needed. The config file at `~/.config/onyx-cli/config.json` (or `$XDG_CONFIG_HOME/onyx-cli/config.json` if set) is read automatically.

Environment variables override the config file and can be used as an alternative when no config file exists:

```bash
export ONYX_SERVER_URL="https://your-onyx-server.com/api"  # default: https://cloud.onyx.app/api
export ONYX_PAT="your-pat"
```

| Variable          | Required | Description                                              |
| ----------------- | -------- | -------------------------------------------------------- |
| `ONYX_SERVER_URL` | No       | Onyx server base URL (default: `https://cloud.onyx.app/api`) |
| `ONYX_PAT`    | Yes      | Personal access token for authentication (unless config file exists) |
| `ONYX_PERSONA_ID` | No       | Default agent/persona ID                                 |
| `ONYX_STREAM_MARKDOWN` | No | Enable/disable progressive markdown rendering (true/false) |

If neither a config file nor environment variables are set, tell the user that `onyx-cli` needs to be configured and ask them to either:
- Run `onyx-cli chat` to complete first-time setup interactively, or
- Set `ONYX_SERVER_URL` and `ONYX_PAT` environment variables (ONYX_PAT holds your PAT)

### 4. Verify configuration

```bash
onyx-cli validate-config
```

Exit code 0 on success. Non-zero with a descriptive error on failure (see exit codes below).

## Commands

### Search documents

```bash
onyx-cli search "What is our deployment process?"
```

Returns ranked, cited documents from the Onyx knowledge base as JSON. The default output is the LLM-facing format — `{"results": [...]}` with citation IDs, titles, content, and source types. Use `--raw` for the full API response including document IDs, scores, links, and citation mapping.

```bash
# Filter by source
onyx-cli search --source slack,google_drive "auth migration status"

# Recent results only
onyx-cli search --days 30 --limit 5 "recent production incidents"

# Use a specific agent for scoped search
onyx-cli search --agent-id 5 "engineering roadmap"

# Full API response for programmatic use
onyx-cli search --raw "API documentation" | jq '.results[].title'

# Skip query expansion for exact matching
onyx-cli search --no-query-expansion "exact error message text"
```

| Flag                    | Type   | Description                                                      |
| ----------------------- | ------ | ---------------------------------------------------------------- |
| `--source`              | string | Filter by source type (comma-separated: slack,google_drive)      |
| `--days`                | int    | Only return results from the last N days                         |
| `--limit`               | int    | Maximum number of results (default: server decides)              |
| `--agent-id`            | int    | Agent ID for scoped search (inherits filters, document sets)     |
| `--raw`                 | bool   | Output full API response (results with scores, links, document IDs, citation mapping) |
| `--no-query-expansion`  | bool   | Skip LLM query expansion (faster, less comprehensive)           |
| `--max-output`          | int    | Max bytes to print before truncating (0 to disable, default 4096 for non-TTY, ignored with --raw) |

### Ask a question

```bash
onyx-cli ask "What is our company's PTO policy?"
```

Streams an LLM-generated answer as plain text to stdout. Use `search` instead when you need the source documents rather than a synthesized answer. When stdout is not a TTY, output is truncated to 4096 bytes and the full response is saved to a temp file (path printed at the end). Use `--max-output 0` to disable truncation.

```bash
# Use a specific agent
onyx-cli ask --agent-id 5 "Summarize our Q4 roadmap"

# Pipe context in with the question
cat error.log | onyx-cli ask --prompt "Find the root cause"

# Structured NDJSON output
onyx-cli ask --json "List all active API integrations"
```

| Flag           | Type | Description                                                  |
| -------------- | ---- | ------------------------------------------------------------ |
| `--agent-id`   | int  | Agent ID to use (overrides default)                          |
| `--json`       | bool | Output NDJSON stream events instead of plain text (bypasses truncation) |
| `--quiet`      | bool | Buffer output and print once at end (no streaming)           |
| `--prompt`     | str  | Question text (use with piped stdin context)                 |
| `--max-output` | int  | Max bytes to print before truncating (0 to disable, default 4096 for non-TTY) |

### List available agents

```bash
onyx-cli agents
onyx-cli agents --json
```

Prints a table of agent IDs, names, and descriptions. Use `--json` for structured JSON output. Use agent IDs with `search --agent-id` or `ask --agent-id`.

### Validate configuration

```bash
onyx-cli validate-config
```

Checks config exists, PAT is present, server is reachable, and credentials are valid. Use before `search`, `ask`, or `agents` to confirm the CLI is properly set up.

## Output Conventions

- **stdout**: Results only (answer text, agent list, status)
- **stderr**: Progress indicators, warnings, errors
- **Non-TTY**: No ANSI escape codes, no interactive prompts
- **Truncation**: When stdout is not a TTY, `search` and `ask` output is truncated to 4096 bytes. Full response is saved to a temp file whose path is printed. Read the temp file for more.

## Exit Codes

| Code | Name           | Meaning                          |
| ---- | -------------- | -------------------------------- |
| 0    | Success        | Command completed successfully   |
| 1    | General        | Unknown or unclassified error    |
| 2    | BadRequest     | Invalid arguments                |
| 3    | NotConfigured  | Missing config or PAT            |
| 4    | AuthFailure    | Invalid PAT (401/403)            |
| 5    | Unreachable    | Server unreachable               |
| 6    | RateLimited    | Server returned 429              |
| 7    | Timeout        | Request timed out                |
| 8    | ServerError    | Server returned 5xx              |
| 9    | NotAvailable   | Feature/endpoint does not exist  |

## Statelessness

Each invocation is independent. `search` does not create a chat session. `ask` creates a one-shot chat session. There is no way to chain context across multiple invocations — every call starts fresh.

## When to Use

Use `onyx-cli search` when:
- You need to find specific documents or gather context for a task
- You want to reason over multiple source documents yourself
- The user asks you to look up or find information in company knowledge
- You need cited, structured results (document IDs, source types, content)

Use `onyx-cli ask` when:
- The user wants a direct answer, summarization, or synthesis
- A human-readable response is more useful than raw documents
- You need the LLM to reason across sources and produce an answer

Do NOT use either when:
- The question is about general programming knowledge (use your own knowledge)
- The user is asking about code in the current repository (use grep/read tools)
- The user hasn't mentioned Onyx and the question doesn't require internal company data

## Examples

```bash
# Search for documents
onyx-cli search "What is our deployment process?"
onyx-cli search --source slack "auth migration status"
onyx-cli search --raw "API documentation" | jq '.results[].title'

# Ask for an answer
onyx-cli ask "What are the steps to deploy to production?"
onyx-cli ask --agent-id 3 "What were the action items from last week's standup?"
cat error.log | onyx-cli ask --prompt "What does this error mean?"
```
