# Part 3: CLI Search Command & Agent Tool Surface — Implementation Plan

> Parent design: [search-design.md](search-design.md) (Part 3)

## Objective

Add a `search` command to onyx-cli that wraps the Part 2 `POST /api/search` endpoint. Rationalize the full CLI into a final agent tool surface: two complementary commands (`search` for retrieval, `ask` for answers), consistent flags, and updated documentation.

---

## End State

After this work, the CLI has two primary agent-usable commands:

| Command | Purpose | Backend | Output |
|---------|---------|---------|--------|
| `search` | Retrieve ranked, cited documents | `POST /api/search` (synchronous JSON) | `llm_facing_text` JSON to stdout |
| `ask` | Get an LLM-generated answer | `POST /chat/send-chat-message` (streaming NDJSON) | Answer text to stdout |

Both commands share:
- `--agent-id` for persona scoping
- Non-TTY truncation via `overflow.Writer` (4096 bytes default)
- Clean exit codes, stderr for progress, stdout for results
- No interactive prompts

### Command: `onyx-cli search`

```
onyx-cli search "what is the sales process for enterprise deals?"
onyx-cli search --source slack,google_drive "auth migration status"
onyx-cli search --days 30 --limit 5 "recent incidents"
onyx-cli search --agent-id 5 "engineering roadmap"
onyx-cli search --raw "deployment process" | jq '.results[].title'
onyx-cli search --no-query-expansion "exact phrase I want"
```

Default output is the `llm_facing_text` field from the API response — a JSON string containing `{"results": [...]}` where each result has `document` (citation ID), `title`, `content`, `source_type`, and other fields. This is the same format `SearchTool` produces for LLM consumption in chat. `--raw` prints the full `SearchAPIResponse` instead, which wraps `llm_facing_text` alongside the structured `results` array (with `document_id`, `score`, `link`, etc.) and `citation_mapping`.

Why `--raw` instead of `--json`: the default output is already JSON (the LLM-facing format), so `--json` would be misleading. `--raw` means "give me the raw API response" — the full structured output with scores, links, and document IDs that the default omits.

### Why two commands, not one

`search` and `ask` are different primitives with different backends, cost profiles, and output shapes:

- **`search`** returns documents. The agent (or user) decides what to do with them. One synchronous HTTP call. Cost: LLM query expansion + document selection (~2-3 LLM calls inside SearchTool). No chat session created.
- **`ask`** returns an LLM-generated answer. Streaming NDJSON protocol. Cost: full chat turn (search + reasoning + generation). Creates a chat session.

A single command with a mode flag (e.g., `search --answer`) would hide this distinction. An agent choosing between "find me documents" and "answer this question" benefits from the choice being explicit. The `ask` command already exists and works — adding `search` alongside it is the natural fit.

---

## Current State (for implementer reference)

### CLI codebase (`cli/`)

- **`cmd/ask.go`**: Streaming command using `client.SendMessageStream()`, `overflow.Writer` for truncation, signal handling for graceful stop. Flags: `--agent-id`, `--json`, `--quiet`, `--prompt`, `--max-output`. This is the closest pattern for `search`, except `search` is synchronous (no streaming).
- **`cmd/agents.go`**: Simple synchronous command using `client.ListAgents()` → `doJSON()`. Table output with `--json` alternative. The `search` command follows this pattern for the API call (synchronous JSON POST) but uses `overflow.Writer` like `ask` for output handling.
- **`cmd/root.go:96-104`**: Command registration via `rootCmd.AddCommand(...)`. The `search` command is added here.
- **`cmd/common.go`**: `requireClient()` returns `(config, client, error)`. `apiErrorToExit()` maps API/auth errors to exit codes. Both used by `search`.
- **`internal/api/client.go`**: `Client` struct with `doJSON()` for synchronous JSON requests (30s timeout). `search` needs a new `Search()` method using this pattern, but with `longHTTPClient` (5min timeout) because SearchTool runs LLM calls internally.
- **`internal/overflow/writer.go`**: Truncation writer. `search` uses this identically to `ask` — non-TTY output truncated at 4096 bytes, full response in temp file.
- **`internal/exitcodes/codes.go`**: Exit codes 0-9. No new codes needed — the existing set covers all search failure modes.
- **`internal/models/models.go`**: Go structs for API types. Needs new structs for `SearchAPIRequest`/`SearchAPIResponse`.
- **`internal/embedded/SKILL.md`**: Agent-facing documentation. Must be updated with the `search` command.

### Backend search API (Part 2, implemented)

- **`POST /api/search`** at `backend/onyx/server/features/search/api.py`
- **Request** (`SearchAPIRequest`): `query` (required), `sources`, `document_sets`, `tags`, `time_cutoff_days`, `num_results` (default 50, max 100), `persona_id`, `provider`+`model` (must be paired), `skip_query_expansion`, `message_history`
- **Response** (`SearchAPIResponse`): `results` (list of `SearchAPIResult`), `llm_facing_text` (JSON string — `{"results": [...]}` with citation IDs, titles, content, source types), `citation_mapping` (int → string)
- **`SearchAPIResult`**: `citation_id`, `document_id`, `chunk_ind`, `title`, `blurb`, `link`, `source_type`, `score`, `updated_at`
- Auth: `require_permission(Permission.BASIC_ACCESS)` — standard PAT auth
- Synchronous handler (no streaming)

---

## Implementation

### A. API client

**1. Add search request/response models** (`internal/models/models.go`)

```go
// SearchRequest is the request body for POST /api/search.
type SearchRequest struct {
    Query              string   `json:"query"`
    Sources            []string `json:"sources,omitempty"`
    DocumentSets       []string `json:"document_sets,omitempty"`
    TimeCutoffDays     *int     `json:"time_cutoff_days,omitempty"`
    NumResults         int      `json:"num_results,omitempty"`
    PersonaID          *int     `json:"persona_id,omitempty"`
    SkipQueryExpansion bool     `json:"skip_query_expansion,omitempty"`
}

// SearchResult is a single document result from the search API.
type SearchResult struct {
    CitationID int     `json:"citation_id"`
    DocumentID string  `json:"document_id"`
    ChunkInd   int     `json:"chunk_ind"`
    Title      string  `json:"title"`
    Blurb      string  `json:"blurb"`
    Link       *string `json:"link"`
    SourceType string  `json:"source_type"`
    Score      *float64 `json:"score"`
    UpdatedAt  *string `json:"updated_at"`
}

// SearchResponse is the response from POST /api/search.
type SearchResponse struct {
    Results         []SearchResult `json:"results"`
    LLMFacingText   string         `json:"llm_facing_text"`
    CitationMapping map[int]string `json:"citation_mapping"`
}
```

Parameters deliberately not exposed in the CLI:
- **`tags`**: Tag filtering requires knowing the tag schema. Agents don't have this context. If needed later, add `--tag key=value`.
- **`provider`/`model`**: LLM selection for the search pipeline. The deployment default or persona's LLM is correct for CLI use. Exposing this would require the agent to know provider names — not useful.
- **`document_sets`**: Document set filtering requires knowing set names. Persona scoping via `--agent-id` is the user-facing way to achieve this (personas already bind document sets). If needed later, add `--document-set`.
- **`message_history`**: Requires structured message objects. No CLI use case today — the query must be self-contained. Could be added later for multi-turn agent workflows.

These can all be added later without breaking changes. The CLI exposes the parameters that are useful to agents and discoverable from the command line.

**2. Add `Search()` method** (`internal/api/client.go`)

```go
// Search calls POST /api/search and returns the response.
func (c *Client) Search(ctx context.Context, req models.SearchRequest) (*models.SearchResponse, error) {
    var resp models.SearchResponse
    if err := c.doJSONLong(ctx, "POST", "/search", req, &resp); err != nil {
        return nil, err
    }
    return &resp, nil
}
```

This needs a `doJSONLong()` variant that uses `longHTTPClient` (5min timeout) instead of `httpClient` (30s). The search endpoint runs LLM calls internally (query expansion, document selection, context expansion) which can take 30-60 seconds on complex queries. The existing `doJSON()` with its 30s timeout would frequently time out.

`doJSONLong()` is a one-line clone of `doJSON()` that swaps `c.httpClient` for `c.longHTTPClient`:

```go
func (c *Client) doJSONLong(ctx context.Context, method, path string, reqBody any, result any) error {
    // Same as doJSON but uses longHTTPClient (5min timeout)
    ...
    resp, err := c.longHTTPClient.Do(req)
    ...
}
```

Update the `ClientAPI` interface to include `Search`:

```go
Search(ctx context.Context, req models.SearchRequest) (*models.SearchResponse, error)
```

### B. Search command

**3. Create `cmd/search.go`**

The command follows the `agents.go` pattern (synchronous JSON response) with `ask.go`'s output handling (overflow.Writer for truncation).

```go
func newSearchCmd(ios *iostreams.IOStreams) *cobra.Command {
    var (
        searchSources      string   // comma-separated
        searchDays         int
        searchLimit        int
        searchAgentID      int
        searchRaw          bool
        searchNoQueryExpansion  bool
        maxOutput          int
    )

    cmd := &cobra.Command{
        Use:   "search [query]",
        Short: "Search company knowledge and return ranked documents",
        ...
        RunE: func(cmd *cobra.Command, args []string) error { ... },
    }

    cmd.Flags().StringVar(&searchSources, "source", "", "Filter by source type (comma-separated: slack,google_drive)")
    cmd.Flags().IntVar(&searchDays, "days", 0, "Only return results from the last N days")
    cmd.Flags().IntVar(&searchLimit, "limit", 0, "Maximum number of results (default: server decides)")
    cmd.Flags().IntVar(&searchAgentID, "agent-id", 0, "Agent ID for scoped search (inherits filters, document sets)")
    cmd.Flags().BoolVar(&searchRaw, "raw", false, "Output full API response (results with scores, links, document IDs, citation mapping)")
    cmd.Flags().BoolVar(&searchNoQueryExpansion, "no-query-expansion", false, "Skip LLM query expansion (faster, less comprehensive)")
    cmd.Flags().IntVar(&maxOutput, "max-output", defaultMaxOutputBytes,
        "Max bytes to print before truncating (0 to disable, auto-enabled for non-TTY)")

    return cmd
}
```

**Flag design decisions:**

- **`--source`** not `--sources`: singular is the convention for comma-separated values in CLIs (`git log --author`, `docker run --network`). Parsed with `strings.Split(val, ",")`.
- **`--days`** not `--time-cutoff-days`: shorter, intuitive. Maps to `time_cutoff_days` in the API.
- **`--limit`** not `--num-results`: standard CLI convention (every paginated CLI uses `--limit`). Maps to `num_results`. When not set, don't send it — let the server use its default (50).
- **`--agent-id`** not `--persona-id`: consistency with `ask --agent-id`. From the CLI user's perspective, "persona" is an internal backend concept — they pick an "agent" to scope their search. The CLI maps `--agent-id` → `persona_id` in the API request.
- **`--no-query-expansion`**: Boolean flag (not `--skip-query-expansion`). Clearer than a double-negative `--skip-*` — the flag name says what happens ("no query expansion"), not what it skips.
- **No `--quiet` flag**: `search` is synchronous — no streaming to buffer. The response arrives in one shot. `--quiet` on `ask` exists because `ask` streams tokens. For `search`, the output is already "quiet" (one response, no incremental tokens).
- **No `--prompt` / stdin piping**: `search` takes a query string, not a conversation context. The query is always the positional argument. No stdin context concatenation — that's an `ask` pattern where you pipe a document and ask a question about it. For `search`, the query should be self-contained.

**RunE implementation:**

```go
RunE: func(cmd *cobra.Command, args []string) error {
    _, client, err := requireClient()
    if err != nil {
        return err
    }

    if len(args) == 0 {
        return exitcodes.New(exitcodes.BadRequest,
            "no query provided\n  Usage: onyx-cli search \"your query\"")
    }

    req := models.SearchRequest{
        Query: args[0],
    }

    if cmd.Flags().Changed("source") {
        req.Sources = strings.Split(searchSources, ",")
    }
    if cmd.Flags().Changed("days") {
        req.TimeCutoffDays = &searchDays
    }
    if cmd.Flags().Changed("limit") {
        req.NumResults = searchLimit
    }
    if cmd.Flags().Changed("agent-id") {
        req.PersonaID = &searchAgentID
    }
    if searchNoQueryExpansion {
        req.SkipQueryExpansion = true
    }

    ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
    defer stop()

    // Progress indicator on stderr (TTY only)
    isTTY := ios.IsStdoutTTY
    if isTTY {
        fmt.Fprintf(ios.ErrOut, "\033[2mSearching...\033[0m\n")
    }

    resp, err := client.Search(ctx, req)
    if err != nil {
        return apiErrorToExit(err, "search failed")
    }

    if searchRaw {
        data, err := json.MarshalIndent(resp, "", "  ")
        if err != nil {
            return fmt.Errorf("failed to marshal response: %w", err)
        }
        fmt.Fprintln(ios.Out, string(data))
        return nil
    }

    // Default: print llm_facing_text through overflow writer
    truncateAt := 0
    if cmd.Flags().Changed("max-output") {
        truncateAt = maxOutput
    } else if !isTTY {
        truncateAt = defaultMaxOutputBytes
    }

    ow := &overflow.Writer{Limit: truncateAt, Out: ios.Out, ErrOut: ios.ErrOut}
    ow.Write(resp.LLMFacingText)
    ow.Finish()

    return nil
}
```

**4. Register in root** (`cmd/root.go`)

Add `rootCmd.AddCommand(newSearchCmd(ios))` alongside the existing commands.

### C. Documentation

**5. Update SKILL.md** (`internal/embedded/SKILL.md`)

Add the `search` command documentation. The updated SKILL.md should:

- Add `search` as the primary command (listed before `ask`)
- Document all flags: `--source`, `--days`, `--limit`, `--agent-id`, `--raw`, `--no-query-expansion`, `--max-output`
- Explain the search/ask distinction: search returns cited document results (JSON), ask returns an LLM answer
- Update "When to Use" to distinguish search vs ask use cases:
  - Use `search` when: finding specific documents, gathering context for a task, the agent needs to reason over multiple sources
  - Use `ask` when: the user wants a direct answer, summarization, or synthesis

**6. Update help text** (`cmd/search.go`)

```go
Long: `Search the Onyx knowledge base and return ranked, cited documents.

Results are retrieved using the full search pipeline: LLM query expansion,
hybrid retrieval, document selection, and context expansion — the same
search quality as the Onyx chat interface.

By default, output is the LLM-facing JSON that SearchTool produces — a
{"results": [...]} object with citation IDs, titles, content, and source
types. Use --raw for the full API response including document IDs, scores,
links, and citation mapping.

When stdout is not a TTY, output is truncated to --max-output bytes and the
full response is saved to a temp file.`

Example: `  onyx-cli search "What is our deployment process?"
  onyx-cli search --source slack "auth migration status"
  onyx-cli search --days 30 --limit 5 "recent production incidents"
  onyx-cli search --agent-id 5 "engineering roadmap"
  onyx-cli search --raw "API documentation" | jq '.results[].title'
  onyx-cli search --no-query-expansion "exact error message text"`
```

### D. Consistency audit

**7. Flag consistency across agent commands**

Review and align flag conventions across `search`, `ask`, and `agents`:

| Flag | `search` | `ask` | `agents` | Notes |
|------|----------|-------|----------|-------|
| `--raw` | Yes | — | — | Full API response; `search`-only (default output is already JSON) |
| `--json` | — | Yes | Yes | Structured output; not on `search` because default is already JSON |
| `--max-output` | Yes | Yes | No | `agents` output is small, truncation not needed |
| `--agent-id` | Yes | Yes | — | Consistent name; maps to `persona_id` in API |
| `--quiet` | No | Yes | No | Not applicable to synchronous commands |
| `--prompt` | No | Yes | — | Not applicable to search |

---

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `cli/cmd/search.go` | `search` command (Cobra command, flag registration, RunE handler) |

### Modified Files

| File | Change |
|------|--------|
| `cli/cmd/root.go` | Add `rootCmd.AddCommand(newSearchCmd(ios))` |
| `cli/internal/api/client.go` | Add `Search()` method, `doJSONLong()` helper, update `ClientAPI` interface |
| `cli/internal/models/models.go` | Add `SearchRequest`, `SearchResult`, `SearchResponse` structs |
| `cli/internal/embedded/SKILL.md` | Add `search` command documentation, update "When to Use" guidance |

---

## PR Strategy

One PR. The surface area is small: one new command, one new API method, three new model structs, and a SKILL.md update. No refactoring of existing code — `search` is additive.

---

## Tests

### Unit tests (Go `_test.go` files)

**File:** `cli/cmd/search_test.go`

1. **No query → exit code 2.** `onyx-cli search` with no args returns `BadRequest`.
2. **Source parsing.** `--source slack,google_drive` produces `Sources: ["slack", "google_drive"]` in the request.
3. **Flags set correctly.** `--days 30 --limit 5 --agent-id 3 --no-query-expansion` maps to the right `SearchRequest` fields. Unset flags produce zero values / nil pointers (not sent in JSON).

These tests mock the API client (no server needed). They verify flag→request mapping and error paths.

**File:** `cli/internal/api/client_test.go` (extend existing)

4. **`Search()` returns `SearchResponse`.** Mock HTTP server returns a canned JSON response. Assert fields map correctly.
5. **`Search()` on 401 returns `OnyxAPIError` with `StatusCode: 401`.** Verify error propagation.

### Integration tests

**File:** `backend/tests/integration/tests/cli/test_cli_commands.py` (extend existing)

These tests run the real CLI binary against a real Onyx backend via `subprocess.run()`, using the existing `run_cli()` helper, `cli_binary` fixture, and `pat_token` fixture. They require `ONYX_CLI_BINARY` to be set and are skipped otherwise.

Tests need seeded documents so search has something to find. Use `CCPairManager.create_from_scratch()` + `DocumentManager.seed_doc_with_content()` with a unique phrase per test (same pattern as `backend/tests/integration/tests/search/test_search_api.py`).

1. **`test_search_returns_results`** — Seed a doc with a unique phrase. Run `onyx-cli search "<phrase>"`. Assert exit code 0, stdout is non-empty and contains the phrase.

2. **`test_search_raw`** — Same setup. Run `onyx-cli search --raw "<phrase>"`. Parse stdout as JSON. Assert `results` is a list with at least one entry, `llm_facing_text` is non-empty, `citation_mapping` is a dict. Assert the seeded doc's `document_id` appears in results.

3. **`test_search_source_filter`** — Seed docs on two different CC pairs (different sources if possible). Run `onyx-cli search --raw --source <source_type> "<phrase>"`. Assert only matching source appears in results.

4. **`test_search_agent_id`** — Create a document set + persona scoped to it (same pattern as `test_persona_scoped_search` in the search API integration tests). Run `onyx-cli search --agent-id <persona_id> "<phrase>"`. Assert scoped doc appears, out-of-scope doc does not.

5. **`test_search_truncation`** — Run `onyx-cli search --max-output 50 "<phrase>"`. Assert "response truncated" and "Full response:" appear in stdout.

6. **`test_search_no_query`** — Run `onyx-cli search` with no args. Assert exit code 2.

7. **`test_search_bad_pat`** — Run `onyx-cli search "test"` with `pat="bad-token"`. Assert exit code 4.

8. **`test_search_not_configured`** — Run `onyx-cli search "test"` with no PAT. Assert exit code 3.
