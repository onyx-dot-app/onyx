# Part 1: Agent-First CLI Refactor — Implementation Plan

> Parent design: [search-design.md](search-design.md) (Part 1)

## Objective

Reposition onyx-cli from a human-first TUI with a non-interactive sidecar (`ask`) into an **agent experience (AX) tool** — a CLI designed first for agent consumption, with the TUI as an extension for human users. When an agent or script invokes onyx-cli (no TTY), it gets structured output, clean exit codes, no truncation, and no interactive prompts. When a human invokes it (TTY present), current interactive behavior is preserved.

## End State

After this refactor, onyx-cli has two modes determined by TTY detection:

**Non-interactive (no TTY) — the agent path, and the primary path:**

| Command | What it does | Output |
|---------|-------------|--------|
| `ask` | One-shot question → LLM answer | Markdown to stdout; `--json` unchanged (NDJSON stream events) |
| `agents` | List available personas | Table to stdout; `--json` for JSON array |
| `validate-config` | Check config, auth, connectivity, capabilities | Status text to stdout; `--json` for machine-readable status |
| `install-skill` | Install SKILL.md for agent harnesses | Status message |
| `experiments` | List feature flags | Status text |
| *(no subcommand)* | Prints help and exits 0 | Help text to stdout |

All agent-usable commands: no truncation, no ANSI codes, no interactive prompts. Results to stdout, progress/errors to stderr. Every failure has a distinct exit code and an actionable error message on stderr.

**Interactive (TTY present) — the human path:**

| Command | What it does |
|---------|-------------|
| `chat` | Bubble Tea TUI (default when TTY present and no subcommand) |
| `configure` | Interactive setup wizard |
| `serve` | SSH server wrapping the TUI |

These commands fail with a clear error and exit code when called without a TTY, suggesting the non-interactive alternative (e.g., "use environment variables instead of `configure`").

**Configuration:** Agents use environment variables (`ONYX_SERVER_URL`, `ONYX_API_KEY`). No config file needed. Humans use `configure` or the config file. Env vars override the config file in both cases.

**Exit codes:** Distinct codes for every failure class — not configured, auth failure, server unreachable, rate limited, timeout, server error, feature not available. Agents use exit codes to branch; the stderr message tells them what to do about it.

**`--json` behavior:** Existing `--json` flags are unchanged. On `ask`, `--json` emits NDJSON stream events (one JSON object per line). On `agents`, `--json` emits a JSON array. Agents primarily consume the default plain-text stdout — `--json` is for programmatic consumers that want structured event data.

## Important Notes

### Current architecture (what exists today)

- **Entry point**: `cli/main.go` → `cmd.Execute()` → Cobra root command
- **Commands**: `chat` (TUI, default), `ask` (one-shot), `agents` (list), `configure`, `validate-config`, `serve` (SSH), `install-skill`, `experiments`
- **TTY detection**: `golang.org/x/term.IsTerminal(fd)` — used in `ask.go` (stdout FD) and `configure.go` (stdin FD) independently
- **Config**: `~/.config/onyx-cli/config.json` with env var overrides (`ONYX_SERVER_URL`, `ONYX_API_KEY`, `ONYX_PERSONA_ID`)
- **Auth**: Bearer token in `Authorization` + `X-Onyx-Authorization` headers
- **Exit codes**: `exitcodes.ExitError` wrapping, unwrapped in `main.go` for `os.Exit()`
- **Output**: `overflow.Writer` handles truncation; NDJSON streaming via `api/stream.go`; Glamour markdown rendering in TUI only
- **SKILL.md**: Embedded via `//go:embed` in `internal/embedded/embed.go`, installed by `install-skill` to `.agents/skills/onyx-cli/`

### Key files

| File | What it does | What changes |
|------|-------------|-------------|
| `cli/cmd/root.go` | Root command, default → chat | Add global TTY state, change default behavior |
| `cli/cmd/ask.go` | One-shot query | Remove 4096 truncation, improve JSON output |
| `cli/cmd/chat.go` | TUI launcher | Gate behind TTY |
| `cli/cmd/configure.go` | Config setup | Gate behind TTY |
| `cli/cmd/serve.go` | SSH server | Gate behind TTY |
| `cli/cmd/agents.go` | List agents | Add consistency (stderr/stdout, --json improvements) |
| `cli/cmd/validate.go` | Config validation | Add --json, feature detection |
| `cli/internal/exitcodes/codes.go` | Exit code definitions | Add new codes |
| `cli/internal/overflow/writer.go` | Output truncation | Change default for non-TTY |
| `cli/internal/config/config.go` | Config loading | No structural changes needed |
| `cli/internal/embedded/SKILL.md` | Agent skill description | Full rewrite |
| `cli/README.md` | User documentation | Update for agent-first framing |

### Constraints

- **Go codebase.** All changes are in `cli/` (Go 1.26.1, Cobra, Bubble Tea).
- **Backwards compatibility is not a design constraint.** This is a breaking change. The changelog should call it out but we are not designing around it.
- **The `search` command does not exist yet.** Part 3 adds it. This refactor prepares the foundation (TTY gating, output conventions, exit codes) that the search command will follow.
- **PyPI distribution.** The CLI ships as a Python wheel with a Go binary. The build process (`hatch_build.py`, `pyproject.toml`) should not need changes unless version metadata changes.

---

## Implementation Strategy

### 1. Gate human-only commands behind TTY

**Where:** `cli/cmd/chat.go`, `cli/cmd/configure.go`, `cli/cmd/serve.go`

Add a guard at the top of each command's `RunE`:

```
if !IsInteractive() {
    return exitcodes.New(exitcodes.BadRequest,
        "the <command> command requires an interactive terminal\n  ...")
}
```

For each:
- **`chat`**: Error message suggests using `ask` instead.
- **`configure`**: Becomes interactive-only (TTY required). The current non-interactive path (`--server-url`/`--api-key` flags) is removed — agents don't configure, they use env vars. Without a TTY, the error message says to set `ONYX_SERVER_URL` and `ONYX_API_KEY` environment variables.
- **`serve`**: Error message says SSH server requires a terminal.

**Default command behavior** (`root.go:104-109`): Change the fallthrough. When `!IsInteractive()`, print the help text and exit 0 instead of launching the TUI. When interactive, keep the current `chatCmd.RunE` fallthrough.

### 2. Remove non-TTY output truncation

**Where:** `cli/cmd/ask.go`

Change the truncation default (lines 85–92):

- **Current**: non-TTY → `truncateAt = 4096`
- **New**: non-TTY → `truncateAt = 0` (no truncation)
- The `--max-output` flag still works as an explicit override in either direction.

Remove the `defaultMaxOutputBytes` constant. The default is now "no truncation" everywhere, with `--max-output N` as the opt-in.

### 3. Extend exit codes

**Where:** `cli/internal/exitcodes/codes.go`

Add codes for failure modes agents will encounter:

| Code | Name | When |
|------|------|------|
| 6 | `RateLimited` | Server returns 429 |
| 7 | `Timeout` | Request exceeds deadline |
| 8 | `ServerError` | Server returns 5xx |
| 9 | `NotAvailable` | Requested feature/endpoint doesn't exist (404 on capability check) |

Keep room for Part 3 to add search-specific codes if needed. The exact values are an implementation decision — what matters is that each failure mode has a distinct code and the full set is documented.

Update `internal/api/errors.go` and `internal/api/stream.go` to map HTTP status codes to the new exit codes where they currently fall through to `General = 1`.

### 4. Enhance `validate-config` for capability discovery

**Where:** `cli/cmd/validate.go`

Add a `--json` flag that outputs machine-readable status:

```json
{
  "configured": true,
  "authenticated": true,
  "server_reachable": true,
  "client_version": "0.3.1",
  "server_version": "3.2.0",
  "capabilities": {
    "search": true
  }
}
```

**Capability detection**: After the existing auth check, probe the search endpoint (e.g., `OPTIONS` or a lightweight `GET` on `/api/search`) to determine if the search API is deployed. This is a boolean — "is this backend version new enough to have the search endpoint?" — not a health check.

The human-readable output format stays as the default. `--json` is for Craft session setup (Part 4, R4.6) and agent tooling.

### 5. Standardize output conventions across agent-usable commands

**Where:** `cli/cmd/agents.go`, `cli/cmd/ask.go`, `cli/cmd/validate.go`

Ensure all agent-usable commands follow the same conventions:

- **stdout**: Results only (the answer, the agent list, the config status).
- **stderr**: Progress, warnings, and errors. All stderr output gated on `IsInteractive()` (not just per-command TTY checks).
- **`--json`**: Available on every agent-usable command. Produces parseable JSON to stdout.
- **`--help`**: Rewrite `Long` descriptions to be useful to an LLM reader. Describe what the command returns, not just what it does. Example: "Prints the full LLM response to stdout. In --json mode, each line is a JSON event object..." rather than "Launch the interactive terminal UI."
- **No ANSI codes when `!IsInteractive()`**: The `agents` command currently uses `tabwriter` (fine — no ANSI), but audit all stdout paths.

### 6. Rewrite SKILL.md

**Where:** `cli/internal/embedded/SKILL.md`

Full rewrite to reflect the agent-first positioning. Key changes:

- **Framing**: onyx-cli is an agent's interface to Onyx knowledge, not a human TUI with an agent sidecar.
- **Commands section**: Document the agent-usable command surface. Include the search command as "coming soon" or leave a placeholder that Part 3 will fill.
- **TTY behavior**: Explain that the CLI auto-detects non-interactive mode. No configuration step is needed when env vars are set.
- **Output format**: Document that default output is markdown/text to stdout, `--json` for structured output. No truncation when piped.
- **Error handling**: Document exit codes and that stderr contains actionable error messages.
- **When to use / when not to use**: Keep and refine the existing guidance.
- **Remove**: References to `onyx-cli configure` as a setup step for agents. Agents use env vars.

### 7. Update README

**Where:** `cli/README.md`

- Add an "Agent / Non-Interactive Use" section near the top, covering env var configuration, output behavior, and exit codes.
- Update the command reference table to indicate which commands are agent-usable vs interactive-only.
- Note the breaking change: default command without TTY no longer launches the TUI.

### 8. Update `--help` text for agent discoverability

**Where:** All `cli/cmd/*.go` files

- Root command `Short`: Change from "Terminal UI for chatting with Onyx" to something like "CLI for Onyx knowledge and search" — reflects agent-first, not TUI-first.
- Root command `Long`: Describe the agent-usable surface, mention TTY auto-detection.
- `chat` `Short`: "Launch the interactive chat TUI (requires terminal)"
- `configure` `Short`: "Configure server URL and API key (requires terminal)"
- Agent-usable commands: Ensure `Long` text describes inputs, outputs, and exit behavior in a way an LLM can parse.

---

## Order of Implementation

Steps 1–2 together (TTY gating + truncation fix). Steps 3–4 together (exit codes + validate). Steps 5–8 are documentation/polish that can be done last.

```
[1-2] Gate commands + fix output  ──►  [3-4] Exit codes + validate  ──►  [5-8] Docs
```

Ideally 2–3 PRs:
1. **Core behavior**: Command gating, truncation fix (steps 1–2)
2. **Error contract**: Exit codes, validate-config enhancements (steps 3–4)
3. **Documentation**: SKILL.md rewrite, README update, help text (steps 5–8)

---

## Tests

### Unit tests (`cli/` — Go tests)

- **TTY gating**: Verify `chat`, `configure`, `serve` return `BadRequest` exit code when stdout/stdin is not a TTY.
- **Exit code mapping**: Verify that HTTP 429 → `RateLimited`, 5xx → `ServerError`, 401 → `AuthFailure`, etc.
- **Output truncation**: Verify that non-TTY no longer truncates by default. Verify `--max-output N` still works.
- **`validate-config --json`**: Verify JSON output shape matches the documented contract.

These are standard Go `_test.go` files in the `cli/` tree. Existing test files (`exitcodes/codes_test.go`, `overflow/writer_test.go`, `config/config_test.go`) should be extended.

### Manual smoke test

After the refactor, verify in a real terminal:
1. `onyx-cli` with TTY → launches TUI (unchanged)
2. `echo "" | onyx-cli` (no TTY) → prints help, exits 0
3. `onyx-cli ask "test" | cat` → full response, no truncation
4. `onyx-cli chat 2>&1 | cat` → clear error about requiring terminal
5. `ONYX_API_KEY=... onyx-cli validate-config --json` → valid JSON to stdout
6. `onyx-cli configure 2>&1 | cat` → clear error about requiring terminal, suggests env vars
7. `onyx-cli ask --json "test" | head -1 | jq .type` → valid NDJSON events (unchanged)
