# Part 1: Agent-First CLI Refactor — Implementation Plan

> Parent design: [search-design.md](search-design.md) (Part 1)

## Objective

Reposition onyx-cli as an **agent experience (AX) tool** — designed first for agent consumption, with the interactive TUI preserved for human users. The CLI uses TTY detection to determine which mode it's in. This refactor prepares the foundation that the search command (Part 3) will build on.

---

## End State

After this refactor, onyx-cli has two modes determined by TTY detection:

### Agent path (no TTY)

| Command | Purpose | Output |
|---------|---------|--------|
| `ask` | One-shot question → LLM answer | Markdown text to stdout, no truncation |
| `agents` | List available personas | Table to stdout; `--json` for JSON array |
| `validate-config` | Health check (config, auth, connectivity) | Status text to stdout; exit code indicates failure type |
| `install-skill` | Install SKILL.md for agent harnesses | Status message |
| `experiments` | List feature flags | Status text |
| *(no subcommand)* | Prints help and exits 0 | Help text to stdout |

Conventions for all agent-usable commands:
- Results to stdout, progress/errors to stderr
- Non-TTY output truncated to 4096 bytes with full response in temp file (agents can read more if needed)
- No ANSI codes, no interactive prompts
- Every failure has a distinct exit code and an actionable error message on stderr

### Human path (TTY present)

| Command | Purpose |
|---------|---------|
| `chat` | Bubble Tea TUI (default when no subcommand) |
| `configure` | Interactive setup wizard (interactive-only — no scripted flags) |
| `serve` | SSH server wrapping the TUI |

These already fail naturally without a TTY (Bubble Tea crashes, prompts fail). No explicit guards needed.

### Configuration

Agents use environment variables (`ONYX_SERVER_URL`, `ONYX_API_KEY`). Humans use `configure` or the config file. Env vars override the config file in both cases.

### Exit codes

| Code | Name | When |
|------|------|------|
| 0 | `Success` | *(existing)* |
| 1 | `General` | *(existing)* Generic/unknown error |
| 2 | `BadRequest` | *(existing)* Invalid args |
| 3 | `NotConfigured` | *(existing)* Missing config/API key |
| 4 | `AuthFailure` | *(existing)* Invalid API key, 401/403 |
| 5 | `Unreachable` | *(existing)* Server unreachable |
| 6 | `RateLimited` | **New.** Server returns 429 |
| 7 | `Timeout` | **New.** Request exceeds deadline |
| 8 | `ServerError` | **New.** Server returns 5xx |
| 9 | `NotAvailable` | **New.** Feature/endpoint doesn't exist |

---

## Current State (for implementer reference)

The CLI is a Go project at `cli/` (Go 1.26.1, Cobra + Bubble Tea), distributed as a Python wheel via PyPI.

- **Entry point**: `main.go` → `cmd.Execute()` → Cobra root command
- **Default command**: `root.go:104-109` falls through to `chatCmd.RunE` unconditionally — crashes without TTY
- **TTY detection**: `golang.org/x/term.IsTerminal(fd)`, used inline in `ask.go` (stdout) and `configure.go` (stdin)
- **`ask` output**: `overflow.Writer` truncates to 4096 bytes for non-TTY (`ask.go:22,90-91`). `--json` emits NDJSON stream events.
- **`configure`**: Has both interactive wizard and non-interactive flag path (`--server-url`/`--api-key`)
- **`validate-config`**: Human-readable text only, no `--json`, no capability detection
- **Exit codes**: 0–5 defined in `internal/exitcodes/codes.go`. HTTP errors mostly fall through to `General = 1`.
- **Config**: `~/.config/onyx-cli/config.json` with env var overrides (`ONYX_SERVER_URL`, `ONYX_API_KEY`, `ONYX_PERSONA_ID`)
- **SKILL.md**: Embedded via `//go:embed` in `internal/embedded/embed.go`, describes `ask` only, frames CLI as human-first

---

## Implementation

### A. Behavior changes

**1. Default command without TTY** (`cmd/root.go`)

`root.go:104-109` unconditionally falls through to `chatCmd.RunE`. Change: when no TTY is present, print help and exit 0. When TTY is present, keep the current fallthrough to the TUI.

**2. Keep non-TTY output truncation (no change)** (`cmd/ask.go`, `internal/overflow/writer.go`)

The existing truncation behavior is correct for agents. Coding agents have tool call output limits — dumping a full LLM response into the agent's context window wastes tokens. The current design handles this well: full response goes to a temp file, first 4096 bytes go to stdout, and the agent gets the file path to read more if needed. No changes required.

**3. Remove `configure` non-interactive path** (`cmd/configure.go`)

Remove the `--server-url`, `--api-key`, `--api-key-stdin`, and `--dry-run` flags and the `configureNonInteractive()` function. `configure` becomes the interactive wizard only. Agents use env vars — there's no scripted configure path.

**4. Add exit codes** (`internal/exitcodes/codes.go`)

Add `RateLimited = 6`, `Timeout = 7`, `ServerError = 8`, `NotAvailable = 9`. Update `internal/api/errors.go` and `internal/api/stream.go` to map HTTP status codes to these instead of falling through to `General = 1`.

**5. Standardize output across agent-usable commands** (`cmd/agents.go`, `cmd/ask.go`, `cmd/validate.go`)

Audit and fix:
- stdout for results only, stderr for progress/warnings/errors
- No ANSI escape codes in stdout when no TTY
- `--json` available on every agent-usable command (already exists on `ask` and `agents`; adding to `validate-config` above)

### B. Documentation changes

**6. Rewrite SKILL.md** (`internal/embedded/SKILL.md`)

Reframe as agent-first:
- onyx-cli is an agent's interface to Onyx knowledge
- Document the agent-usable command surface (leave placeholder for search command from Part 3)
- Configuration via env vars, not `configure`
- No truncation when piped
- Exit codes and stderr error messages
- Keep and refine the "when to use / when not to use" guidance

**7. Update README** (`README.md`)

- Add "Agent / Non-Interactive Use" section covering env var config, output behavior, exit codes
- Update command reference to indicate agent-usable vs interactive-only
- Note breaking changes

**8. Update `--help` text** (all `cmd/*.go`)

- Root `Short`: "CLI for Onyx knowledge and search" (not "Terminal UI for chatting with Onyx")
- `chat` `Short`: "Launch the interactive chat TUI (requires terminal)"
- `configure` `Short`: "Configure server URL and API key (requires terminal)"
- Agent-usable commands: describe what the command returns and how, not just what it does

---

## PR Strategy

```
PR 1: Behavior  ──►  PR 2: Error contract  ──►  PR 3: Docs
(steps 1-3)          (steps 4-5)                 (steps 6-8)
```

1. **Core behavior** — default command fix, truncation removal, configure simplification
2. **Error contract** — exit codes, output standardization
3. **Documentation** — SKILL.md rewrite, README update, help text

---

## Tests

### Unit tests (Go `_test.go` files)

- **Default command**: bare `onyx-cli` without TTY prints help, exits 0
- **Exit code mapping**: HTTP 429 → `RateLimited`, 5xx → `ServerError`, 401 → `AuthFailure`, etc.
Extend existing test files: `exitcodes/codes_test.go`, `overflow/writer_test.go`, `config/config_test.go`.

### Smoke test

1. `onyx-cli` with TTY → launches TUI (unchanged)
2. `echo "" | onyx-cli` → prints help, exits 0
3. `onyx-cli ask "test" | cat` → truncated response with temp file path (existing behavior, unchanged)
4. `onyx-cli ask --json "test" | head -1 | jq .type` → NDJSON events (unchanged)
