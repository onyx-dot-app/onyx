# Part 1: Agent-First CLI Refactor — Implementation Plan

> **Status: IMPLEMENTED** — shipped as a single PR on branch `whuang/refactor-ax-onyx-cli`.
> Annotations marked *[Diverged]* or *[New]* note where the final implementation
> differs from or goes beyond the original plan.

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
- Non-TTY output truncated to 50000 bytes with full response in temp file (agents can read more if needed)
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

Agents use environment variables (`ONYX_SERVER_URL`, `ONYX_PAT`). Humans use `configure` or the config file. Env vars override the config file in both cases.

### Exit codes

| Code | Name | When |
|------|------|------|
| 0 | `Success` | |
| 1 | `General` | Generic/unknown error |
| 2 | `BadRequest` | Invalid args (convention from sysexits) |
| 3 | `NotConfigured` | Missing config/PAT |
| 4 | `AuthFailure` | Invalid PAT, 401/403 |
| 5 | `Unreachable` | Server unreachable |
| 6 | `RateLimited` | Server returns 429 |
| 7 | `Timeout` | Request exceeds deadline |
| 8 | `ServerError` | Server returns 5xx |
| 9 | `NotAvailable` | Feature/endpoint doesn't exist |

---

## Current State (for implementer reference)

*This section describes the pre-implementation state of the codebase.*

The CLI is a Go project at `cli/` (Go 1.26.1, Cobra + Bubble Tea), distributed as a Python wheel via PyPI.

- **Entry point**: `main.go` → `cmd.Execute()` → Cobra root command
- **Default command**: previously fell through to `chatCmd.RunE` unconditionally — crashes without TTY
- **TTY detection**: `golang.org/x/term.IsTerminal(fd)`, used inline in `ask.go` (stdout) and `configure.go` (stdin)
- **`ask` output**: `overflow.Writer` truncates to 50000 bytes for non-TTY. `--json` emits NDJSON stream events.
- **`configure`**: Previously had both interactive wizard and non-interactive flag path (`--server-url`/`--api-key`)
- **`validate-config`**: Human-readable text only, no `--json`, no capability detection
- **Exit codes**: 0–5 previously defined in `internal/exitcodes/codes.go`. HTTP errors mostly fell through to `General = 1`.
- **Config**: `~/.config/onyx-cli/config.json` with env var overrides (`ONYX_SERVER_URL`, `ONYX_PAT`, `ONYX_PERSONA_ID`)
- **SKILL.md**: Embedded via `//go:embed` in `internal/embedded/embed.go`, describes `ask` only, frames CLI as human-first

---

## Implementation

### A. Behavior changes

**1. Default command without TTY** (`cmd/root.go`)

`root.go:104-109` unconditionally falls through to `chatCmd.RunE`. Change: when no TTY is present, print help and exit 0. When TTY is present, keep the current fallthrough to the TUI.

**2. Keep non-TTY output truncation (no change)** (`cmd/ask.go`, `internal/overflow/writer.go`)

The existing truncation behavior is correct for agents. Coding agents have tool call output limits — dumping a full LLM response into the agent's context window wastes tokens. The current design handles this well: full response goes to a temp file, first 50000 bytes go to stdout, and the agent gets the file path to read more if needed. No changes required.

**3. Remove `configure` non-interactive path** (`cmd/configure.go`)

Remove the `--server-url`, `--api-key`, `--api-key-stdin`, and `--dry-run` flags and the `configureNonInteractive()` function. `configure` becomes the interactive wizard only. Agents use env vars — there's no scripted configure path.

**4. Add exit codes** (`internal/exitcodes/codes.go`)

Add `RateLimited = 6`, `Timeout = 7`, `ServerError = 8`, `NotAvailable = 9`. Update `internal/api/errors.go` and `internal/api/stream.go` to map HTTP status codes to these instead of falling through to `General = 1`. Also added `ForHTTPStatus()` mapping function, `ExitError` type, and `New()`/`Newf()` constructors.

**5. Standardize output across agent-usable commands** (`cmd/agents.go`, `cmd/ask.go`, `cmd/validate.go`)

Audit and fix:
- stdout for results only, stderr for progress/warnings/errors
- No ANSI escape codes in stdout when no TTY
- `--json` available on every agent-usable command (already exists on `ask` and `agents`; adding to `validate-config` above)

*[Diverged] `--json` was NOT added to `validate-config` as planned. The stdout/stderr separation and ANSI cleanup were done.*

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

*[Diverged] The 3-PR strategy below was not followed. All changes were shipped as a single PR.*

```
PR 1: Behavior  ──►  PR 2: Error contract  ──►  PR 3: Docs
(steps 1-3)          (steps 4-5)                 (steps 6-8)
```

1. **Core behavior** — default command fix, truncation removal, configure simplification
2. **Error contract** — exit codes, output standardization
3. **Documentation** — SKILL.md rewrite, README update, help text

---

## Tests

*[Diverged] The plan only described Go unit tests. The implementation added Python integration tests and trimmed Go unit tests to avoid redundancy.*

### Unit tests (Go `_test.go` files)

- **Exit code mapping**: `exitcodes/codes_test.go` tests `ForHTTPStatus()` — HTTP 429 to `RateLimited`, 5xx to `ServerError`, 401 to `AuthFailure`, etc.
- Go unit tests were kept minimal to avoid duplicating coverage with the integration tests below.

### Integration tests (Python, against real backend) *[New — not in original plan]*

`backend/tests/integration/tests/cli/test_cli_commands.py` — 17 tests that build the Go binary and run it against a real Onyx deployment. These test the actual CLI behavior end-to-end: configuration validation, exit codes, agent listing, ask command, error handling, and output format.

### CI workflow *[New — not in original plan]*

`.github/workflows/pr-integration-tests.yml` — added a Go build step that cross-compiles the CLI binary (`GOARCH=arm64 GOOS=linux`) and mounts it into the Docker test container via a volume mount. The binary path is passed as `ONYX_CLI_BINARY` env var.

### Smoke test (manual)

1. `onyx-cli` with TTY -> launches TUI (unchanged)
2. `echo "" | onyx-cli` -> prints help, exits 0
3. `onyx-cli ask "test" | cat` -> truncated response with temp file path (existing behavior, unchanged)
4. `onyx-cli ask --json "test" | head -1 | jq .type` -> NDJSON events (unchanged)

---

## Implementation Notes

This section summarizes what was actually built, including items not covered by the original plan.

### IOStreams pattern *[New — not in original plan]*

Added `internal/iostreams/iostreams.go` following the gh/kubectl convention. The struct bundles `In`, `Out`, `ErrOut`, `IsStdinTTY`, `IsStdoutTTY`, and an `IsInteractive()` method. This is threaded through all commands to provide consistent TTY detection and testable I/O.

### Server URL design *[New — not in original plan]*

The default server URL is `https://cloud.onyx.app/api` (includes the `/api` path). All CLI API paths are relative (e.g. `/me`, `/persona`, `/chat/send-chat-message`). A shared utility `config.WebOrigin(serverURL string) string` strips the `/api` (or `/api/v1`) suffix to produce browser-suitable URLs. This is used by `commands.go`, `sshauth.go`, and `onboarding.go`.

### Shared command helpers *[New — not in original plan]*

`cmd/common.go` provides three helpers that standardize config/client initialization and error mapping across all commands:
- `requireConfig()` — loads config, returns `NotConfigured` exit error if no PAT is set
- `requireClient()` — calls `requireConfig()` then creates an API client
- `apiErrorToExit()` — maps `AuthError` and `OnyxAPIError` to the appropriate exit code

`internal/api/client.go` provides:
- `checkResponse()` — converts non-2xx HTTP responses to `OnyxAPIError`
- `wrapTimeoutError()` — wraps `net.Error` timeouts as HTTP 408 `OnyxAPIError`
- `ClientAPI` interface — allows mocking the client in tests

### `is_listed` bug fix *[Not in original plan]*

Discovered during implementation: the backend renamed the `is_visible` JSON field to `is_listed`, but the CLI's Go struct tag was stale (`json:"is_visible"`). Fixed the tag in `internal/models/models.go` to `json:"is_listed"` (Go field remains `IsVisible`).

### PAT terminology *[Not in original plan]*

The env var is `ONYX_PAT` and all user-facing text says "personal access token (PAT)" -- the `configure` wizard prompt, error messages, SKILL.md, and README.

### Items deferred or skipped

- `--json` flag for `validate-config` was not added (planned but skipped).
- The 3-PR strategy was collapsed into a single PR.
