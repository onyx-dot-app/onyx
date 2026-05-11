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

If a human has already run `onyx-cli configure`, the CLI is ready — no additional setup needed. The config file at `~/.config/onyx-cli/config.json` (or `$XDG_CONFIG_HOME/onyx-cli/config.json` if set) is read automatically.

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
- Run `onyx-cli configure` interactively, or
- Set `ONYX_SERVER_URL` and `ONYX_PAT` environment variables (ONYX_PAT holds your PAT)

### 4. Verify configuration

```bash
onyx-cli validate-config
```

Exit code 0 on success. Non-zero with a descriptive error on failure (see exit codes below).

## Commands

### Ask a question

```bash
onyx-cli ask "What is our company's PTO policy?"
```

Streams the answer as plain text to stdout. When stdout is not a TTY, output is truncated to 4096 bytes and the full response is saved to a temp file (path printed at the end). Use `--max-output 0` to disable truncation.

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

Prints a table of agent IDs, names, and descriptions. Use `--json` for structured JSON output. Use agent IDs with `ask --agent-id`.

### Validate configuration

```bash
onyx-cli validate-config
```

Checks config exists, PAT is present, server is reachable, and credentials are valid. Use before `ask` or `agents` to confirm the CLI is properly set up.

## Output Conventions

- **stdout**: Results only (answer text, agent list, status)
- **stderr**: Progress indicators, warnings, errors
- **Non-TTY**: No ANSI escape codes, no interactive prompts
- **Truncation**: When stdout is not a TTY, `ask` output is truncated to 4096 bytes. Full response is saved to a temp file whose path is printed. Read the temp file for more.

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

Each `onyx-cli ask` call creates an independent chat session. There is no way to chain context across multiple invocations — every call starts fresh.

## When to Use

Use `onyx-cli ask` when:
- The user asks about company-specific information (policies, docs, processes)
- You need to search internal knowledge bases or connected data sources
- The user references Onyx or wants to query their documents
- You need context from company wikis, Confluence, Google Drive, Slack, or other connected sources

Do NOT use when:
- The question is about general programming knowledge (use your own knowledge)
- The user is asking about code in the current repository (use grep/read tools)
- The user hasn't mentioned Onyx and the question doesn't require internal company data

## Examples

```bash
# Simple question
onyx-cli ask "What are the steps to deploy to production?"

# Use a specialized agent
onyx-cli ask --agent-id 3 "What were the action items from last week's standup?"

# Pipe context with a question
cat error.log | onyx-cli ask --prompt "What does this error mean?"

# Read the full response when truncated
onyx-cli ask "Describe the full onboarding process" 2>/dev/null
# If truncated, read the temp file path from the last line of output
```
