package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"
	"unicode/utf8"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/overflow"
	"github.com/spf13/cobra"
)

// searchOutputResult is the per-document JSON shape `onyx-cli search` prints
// (without --raw). One `content` field per result, no Onyx-internal jargon.
type searchOutputResult struct {
	Title      string  `json:"title"`
	URL        *string `json:"url"`
	SourceType string  `json:"source_type"`
	Content    string  `json:"content"`
	UpdatedAt  *string `json:"updated_at"`
}

// searchOutput is the top-level wrapper for single-query `onyx-cli search`
// default stdout, and the per-query payload inside multi-query output.
type searchOutput struct {
	Results    []searchOutputResult `json:"results"`
	Truncation *searchTruncation    `json:"truncation,omitempty"`
}

// searchTruncation is attached when results were dropped or trimmed to keep
// stdout under the output limit. TotalBytes is the size of the full
// pretty-printed response saved at FullResponsePath (the whole multi-query
// payload when several queries were run).
type searchTruncation struct {
	Truncated        bool   `json:"truncated"`
	TotalResults     int    `json:"total_results"`
	ShownResults     int    `json:"shown_results"`
	TotalBytes       int    `json:"total_bytes"`
	ContentTruncated bool   `json:"content_truncated"`
	FullResponsePath string `json:"full_response_path"`
	Hint             string `json:"hint"`
}

// multiSearchEntry is one query's outcome in multi-query output. On failure
// Error is set and Results is null; otherwise Results (and Truncation, when
// the entry was reduced) mirror the single-query shape.
type multiSearchEntry struct {
	Query      string               `json:"query"`
	Error      string               `json:"error,omitempty"`
	Results    []searchOutputResult `json:"results"`
	Truncation *searchTruncation    `json:"truncation,omitempty"`
}

// multiSearchOutput is the top-level stdout shape when more than one query is
// passed: one entry per query, in argument order.
type multiSearchOutput struct {
	Searches []multiSearchEntry `json:"searches"`
}

// rawMultiSearchEntry mirrors multiSearchEntry for --raw, carrying the full
// API response instead of the lean projection.
type rawMultiSearchEntry struct {
	Query    string                 `json:"query"`
	Error    string                 `json:"error,omitempty"`
	Response *models.SearchResponse `json:"response,omitempty"`
}

// maxSearchDays caps --days at ~100 years. The cap mostly exists to keep
// `time.Duration(days) * 24h` from wrapping; nobody legitimately searches
// further back than this.
const maxSearchDays = 36500

// maxSearchQueries bounds one invocation. Each query runs an LLM-backed
// pipeline server-side, and an unquoted shell glob can expand into hundreds
// of arguments — better to error than fire a search per filename.
const maxSearchQueries = 32

// maxConcurrentSearches bounds parallel /search calls in one invocation.
const maxConcurrentSearches = 3

// maxInlineErrorBytes caps in-band per-query error strings so an oversized
// upstream error body can't blow through the --max-output contract.
const maxInlineErrorBytes = 2000

// truncationHint explains the truncation object to LLM consumers.
const truncationHint = "output was reduced to fit the output limit; the complete response is at full_response_path"

// toSearchOutput converts the API response into the default stdout shape.
// `CitationID` is kept on `models.SearchResult` and only surfaced via --raw;
// see `models.SearchResult` for the `Content` invariant.
func toSearchOutput(resp models.SearchResponse) searchOutput {
	out := searchOutput{Results: make([]searchOutputResult, 0, len(resp.Results))}
	for _, r := range resp.Results {
		out.Results = append(out.Results, searchOutputResult{
			Title:      r.Title,
			URL:        r.Link,
			SourceType: r.SourceType,
			Content:    r.Content,
			UpdatedAt:  r.UpdatedAt,
		})
	}
	return out
}

// clampError renders an error for in-band JSON output, trimming oversized
// messages (e.g. a whole HTML error page in an API error body) at a rune
// boundary.
func clampError(err error) string {
	msg := err.Error()
	if len(msg) <= maxInlineErrorBytes {
		return msg
	}
	cut := maxInlineErrorBytes
	for cut > 0 && !utf8.RuneStart(msg[cut]) {
		cut--
	}
	return msg[:cut] + " … (truncated)"
}

// writeJSONReduced prints payload as pretty JSON. When the payload exceeds
// truncateAt bytes (> 0), the full response is saved to a temp file first —
// dropped data must never be unrecoverable — and the smaller envelope built
// by reduce is printed instead. Human-oriented notes go to stderr only.
func writeJSONReduced[T any](
	ios *iostreams.IOStreams, payload T, truncateAt int,
	reduce func(totalBytes int, fullPath string) (T, error),
) error {
	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal response: %w", err)
	}

	if truncateAt <= 0 || len(data) <= truncateAt {
		fmt.Fprintln(ios.Out, string(data))
		return nil
	}

	fullPath, err := overflow.SaveFull("onyx-search-*.json", string(data))
	if err != nil {
		// Without the temp copy, dropped results would be unrecoverable —
		// emit the full response instead (valid JSON beats the byte bound).
		fmt.Fprintf(
			ios.ErrOut, "warning: could not save full response, emitting it whole: %v\n", err,
		)
		fmt.Fprintln(ios.Out, string(data))
		return nil
	}
	reduced, err := reduce(len(data), fullPath)
	if err != nil {
		return fmt.Errorf("failed to marshal response: %w", err)
	}
	envelope, err := json.MarshalIndent(reduced, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal response: %w", err)
	}
	fmt.Fprintln(ios.Out, string(envelope))

	fmt.Fprintf(ios.ErrOut, "response truncated (%d bytes total); full response: %s\n", len(data), fullPath)
	return nil
}

// writeSearchJSON prints single-query output, reducing oversized payloads to
// a truncation envelope.
func writeSearchJSON(ios *iostreams.IOStreams, output searchOutput, truncateAt int) error {
	return writeJSONReduced(ios, output, truncateAt,
		func(totalBytes int, fullPath string) (searchOutput, error) {
			return truncateSearchOutput(output, truncateAt, totalBytes, fullPath)
		})
}

// writeMultiSearchJSON prints multi-query output, reducing oversized payloads
// by capping per-query result counts.
func writeMultiSearchJSON(ios *iostreams.IOStreams, output multiSearchOutput, truncateAt int) error {
	return writeJSONReduced(ios, output, truncateAt,
		func(totalBytes int, fullPath string) (multiSearchOutput, error) {
			return truncateMultiSearchOutput(output, truncateAt, totalBytes, fullPath)
		})
}

// truncateSearchOutput builds a valid envelope that marshals to at most limit
// bytes by dropping whole results (relevance-ordered, so a prefix is kept).
// If the first result alone exceeds the limit, its content is trimmed at a
// rune boundary. The envelope may exceed limit only when the truncation
// metadata alone does: valid JSON always wins over the byte bound.
func truncateSearchOutput(
	full searchOutput, limit int, totalBytes int, fullPath string,
) (searchOutput, error) {
	render := func(results []searchOutputResult, contentTruncated bool) (searchOutput, []byte, error) {
		out := searchOutput{
			Results: results,
			Truncation: &searchTruncation{
				Truncated:        true,
				TotalResults:     len(full.Results),
				ShownResults:     len(results),
				TotalBytes:       totalBytes,
				ContentTruncated: contentTruncated,
				FullResponsePath: fullPath,
				Hint:             truncationHint,
			},
		}
		data, err := json.MarshalIndent(out, "", "  ")
		return out, data, err
	}

	fit, data, err := largestFit(len(full.Results), limit, func(n int) ([]byte, error) {
		_, d, err := render(full.Results[:n], false)
		return d, err
	})
	if err != nil {
		return searchOutput{}, err
	}
	// Trim content only when the metadata fits but the first whole result
	// doesn't; otherwise nothing can fit and the n=0 envelope is best effort.
	if fit >= 1 || len(full.Results) == 0 || len(data) > limit {
		out, _, err := render(full.Results[:fit], false)
		return out, err
	}

	trimmed := full.Results[0]
	runes := []rune(trimmed.Content)
	fitK, dataK, err := largestFit(len(runes), limit, func(k int) ([]byte, error) {
		trimmed.Content = string(runes[:k])
		_, d, err := render([]searchOutputResult{trimmed}, true)
		return d, err
	})
	if err != nil {
		return searchOutput{}, err
	}
	// Even an empty-content result overflows (oversized title/url): fall back
	// to the zero-results envelope, which is known to fit.
	if len(dataK) > limit {
		out, _, err := render(full.Results[:0], false)
		return out, err
	}
	trimmed.Content = string(runes[:fitK])
	out, _, err := render([]searchOutputResult{trimmed}, true)
	return out, err
}

// truncateMultiSearchOutput builds a valid multi-query envelope that fits
// under limit by capping every entry's results at the largest uniform
// per-query count k that fits: small result sets pass through whole while
// large ones lose their lowest-relevance tail first. Capped entries carry
// truncation metadata pointing at the combined full response on disk. Fit is
// measured on the real envelope; it exceeds limit only when even the k=0
// render does (valid JSON always wins over the byte bound). Size is not
// perfectly monotone in k — capping an entry adds metadata bytes — so the
// binary search may miss the optimum by a hair, but never returns an
// unmeasured render.
func truncateMultiSearchOutput(
	full multiSearchOutput, limit int, totalBytes int, fullPath string,
) (multiSearchOutput, error) {
	maxResults := 0
	for _, entry := range full.Searches {
		maxResults = max(maxResults, len(entry.Results))
	}
	render := func(k int) (multiSearchOutput, []byte, error) {
		out := multiSearchOutput{Searches: make([]multiSearchEntry, 0, len(full.Searches))}
		for _, entry := range full.Searches {
			if entry.Error != "" || len(entry.Results) <= k {
				out.Searches = append(out.Searches, entry)
				continue
			}
			out.Searches = append(out.Searches, multiSearchEntry{
				Query:   entry.Query,
				Results: entry.Results[:k],
				Truncation: &searchTruncation{
					Truncated:        true,
					TotalResults:     len(entry.Results),
					ShownResults:     k,
					TotalBytes:       totalBytes,
					FullResponsePath: fullPath,
					Hint:             truncationHint,
				},
			})
		}
		data, err := json.MarshalIndent(out, "", "  ")
		return out, data, err
	}

	fit, _, err := largestFit(maxResults, limit, func(k int) ([]byte, error) {
		_, data, err := render(k)
		return data, err
	})
	if err != nil {
		return multiSearchOutput{}, err
	}
	out, _, err := render(fit)
	return out, err
}

// largestFit binary-searches for the largest n in [0, maxN] whose rendering is
// at most limit bytes, returning n and its rendering. render must produce
// output whose size is non-decreasing in n. Falls back to render(0) when
// nothing fits.
func largestFit(
	maxN int, limit int, render func(n int) ([]byte, error),
) (int, []byte, error) {
	best := 0
	bestData, err := render(0)
	if err != nil {
		return 0, nil, err
	}
	lo, hi := 1, maxN
	for lo <= hi {
		mid := (lo + hi) / 2
		data, err := render(mid)
		if err != nil {
			return 0, nil, err
		}
		if len(data) <= limit {
			best, bestData = mid, data
			lo = mid + 1
		} else {
			hi = mid - 1
		}
	}
	return best, bestData, nil
}

// searchFlags bundles the resolved CLI flag inputs for buildSearchRequest.
// `daysSet` / `agentIDSet` track whether the corresponding flag was passed
// explicitly (so unset flags don't end up in the JSON body).
type searchFlags struct {
	query            string
	sources          []string
	days             int
	daysSet          bool
	agentID          int
	agentIDSet       bool
	defaultAgentID   int
	noQueryExpansion bool
}

// buildSearchRequest maps resolved CLI flags into the search API request body.
func buildSearchRequest(flags searchFlags) models.SearchRequest {
	req := models.SearchRequest{Query: flags.query}

	for _, source := range flags.sources {
		source = strings.TrimSpace(source)
		if source != "" {
			req.Sources = append(req.Sources, source)
		}
	}
	if flags.daysSet {
		cutoff := time.Now().UTC().Add(-time.Duration(flags.days) * 24 * time.Hour).Format(time.RFC3339)
		req.TimeCutoff = &cutoff
	}
	if flags.agentIDSet {
		req.PersonaID = &flags.agentID
	} else if flags.defaultAgentID != 0 {
		req.PersonaID = &flags.defaultAgentID
	}
	if flags.noQueryExpansion {
		req.SkipQueryExpansion = true
	}
	return req
}

func newSearchCmd(ios *iostreams.IOStreams) *cobra.Command {
	var (
		searchSources          string
		searchDays             int
		searchAgentID          int
		searchRaw              bool
		searchNoQueryExpansion bool
		maxOutput              int
	)

	cmd := &cobra.Command{
		Use:   "search <query> [<query>...]",
		Short: "Search company knowledge and return ranked documents",
		Long: `Search the Onyx knowledge base and return ranked, cited documents.

Results are retrieved using the full search pipeline: LLM query expansion,
hybrid retrieval, document selection, and context expansion — the same
search quality as the Onyx chat interface.

Multiple queries run concurrently in one invocation, so batching independent
queries is much faster than separate sequential calls. Flags apply to every
query. The command fails only when every query fails; otherwise failed
queries carry an in-band "error" field.

By default, output is a lean JSON shape tuned for LLM consumers. One query:
{"results": [{title, url, source_type, content, updated_at}, ...]}.
Multiple queries: {"searches": [{query, results}, ...]}, in argument order.
Results contain only documents the LLM judged relevant, ordered by relevance;
content is the full chunk text of each. Use --raw for the full API response:
one query prints it bare (adds per-result citation_id), multiple queries
print {"searches": [{query, response}, ...]}.

When stdout is not a TTY and the response exceeds --max-output bytes, whole
results are dropped so stdout stays valid JSON; a "truncation" object carries
metadata (total_results, shown_results, full_response_path, ...) and the full
response is saved to a temp file, shaped like the printed output ("results"
for one query, "searches" for several). With multiple queries, per-query
result counts are capped uniformly until the combined output fits, so small
result sets pass through whole.`,
		Args: cobra.ArbitraryArgs,
		Example: `  onyx-cli search "What is our deployment process?"
  onyx-cli search "Q3 roadmap" "hiring plan" "incident postmortem template"
  onyx-cli search --source slack "auth migration status"
  onyx-cli search --days 30 "recent production incidents"
  onyx-cli search --agent-id 5 "engineering roadmap"
  onyx-cli search --raw "API documentation" | jq '.results[].title'
  onyx-cli search --no-query-expansion "exact error message text"`,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg, client, err := requireClient()
			if err != nil {
				return err
			}

			if len(args) == 0 {
				return exitcodes.New(exitcodes.BadRequest,
					"no query provided\n  Usage: onyx-cli search \"your query\"")
			}
			if len(args) > maxSearchQueries {
				return exitcodes.New(exitcodes.BadRequest, fmt.Sprintf(
					"%d queries exceeds the limit of %d — did an unquoted glob or sentence expand into separate arguments?",
					len(args), maxSearchQueries))
			}

			if cmd.Flags().Changed("days") {
				if searchDays <= 0 {
					return exitcodes.New(exitcodes.BadRequest,
						"--days must be a positive integer")
				}
				if searchDays > maxSearchDays {
					return exitcodes.New(exitcodes.BadRequest,
						fmt.Sprintf("--days cannot exceed %d (~100 years)", maxSearchDays))
				}
			}

			var sources []string
			if cmd.Flags().Changed("source") {
				sources = strings.Split(searchSources, ",")
			}
			baseFlags := searchFlags{
				sources:          sources,
				days:             searchDays,
				daysSet:          cmd.Flags().Changed("days"),
				agentID:          searchAgentID,
				agentIDSet:       cmd.Flags().Changed("agent-id"),
				defaultAgentID:   cfg.DefaultAgentID,
				noQueryExpansion: searchNoQueryExpansion,
			}

			ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()

			isTTY := ios.IsStdoutTTY
			if isTTY {
				if len(args) > 1 {
					fmt.Fprintf(ios.ErrOut, "\033[2mSearching (%d queries)...\033[0m\n", len(args))
					// All-single-word arguments often mean one unquoted query.
					if !strings.ContainsAny(strings.Join(args, ""), " \t") {
						fmt.Fprintf(ios.ErrOut, "\033[2m(each argument searches separately — quote multi-word queries)\033[0m\n")
					}
				} else {
					fmt.Fprintf(ios.ErrOut, "\033[2mSearching...\033[0m\n")
				}
			}

			responses := make([]*models.SearchResponse, len(args))
			errs := make([]error, len(args))
			sem := make(chan struct{}, maxConcurrentSearches)
			var wg sync.WaitGroup
			for i, query := range args {
				wg.Add(1)
				go func(i int, query string) {
					defer wg.Done()
					sem <- struct{}{}
					defer func() { <-sem }()
					flags := baseFlags
					flags.query = query
					responses[i], errs[i] = client.Search(ctx, buildSearchRequest(flags))
				}(i, query)
			}
			wg.Wait()

			// An interrupted run must not masquerade as a successful partial
			// one: surface the first cancellation error and exit non-zero.
			if ctx.Err() != nil {
				for _, err := range errs {
					if err != nil {
						return apiErrorToExit(err, "search failed")
					}
				}
			}

			failures := 0
			for _, err := range errs {
				if err != nil {
					failures++
				}
			}
			if failures == len(args) {
				for i := 1; i < len(args); i++ {
					fmt.Fprintf(ios.ErrOut, "search failed for %q: %v\n", args[i], clampError(errs[i]))
				}
				return apiErrorToExit(errs[0], "search failed")
			}

			truncateAt := 0
			if cmd.Flags().Changed("max-output") {
				truncateAt = maxOutput
			} else if !isTTY {
				truncateAt = defaultMaxOutputBytes
			}

			if len(args) == 1 {
				if searchRaw {
					data, err := json.MarshalIndent(responses[0], "", "  ")
					if err != nil {
						return fmt.Errorf("failed to marshal response: %w", err)
					}
					fmt.Fprintln(ios.Out, string(data))
					return nil
				}
				return writeSearchJSON(ios, toSearchOutput(*responses[0]), truncateAt)
			}

			if searchRaw {
				out := struct {
					Searches []rawMultiSearchEntry `json:"searches"`
				}{Searches: make([]rawMultiSearchEntry, 0, len(args))}
				for i, query := range args {
					entry := rawMultiSearchEntry{Query: query}
					if errs[i] != nil {
						entry.Error = clampError(errs[i])
					} else {
						entry.Response = responses[i]
					}
					out.Searches = append(out.Searches, entry)
				}
				data, err := json.MarshalIndent(out, "", "  ")
				if err != nil {
					return fmt.Errorf("failed to marshal response: %w", err)
				}
				fmt.Fprintln(ios.Out, string(data))
				return nil
			}

			output := multiSearchOutput{Searches: make([]multiSearchEntry, 0, len(args))}
			for i, query := range args {
				entry := multiSearchEntry{Query: query}
				if errs[i] != nil {
					entry.Error = clampError(errs[i])
				} else {
					entry.Results = toSearchOutput(*responses[i]).Results
				}
				output.Searches = append(output.Searches, entry)
			}
			return writeMultiSearchJSON(ios, output, truncateAt)
		},
	}

	cmd.Flags().StringVar(&searchSources, "source", "", "Filter by source type (comma-separated: slack,google_drive)")
	cmd.Flags().IntVar(&searchDays, "days", 0, "Only return results from the last N days")
	cmd.Flags().IntVar(&searchAgentID, "agent-id", 0, "Agent ID for scoped search")
	cmd.Flags().BoolVar(&searchRaw, "raw", false, "Output full API response (adds per-result citation_id)")
	cmd.Flags().BoolVar(&searchNoQueryExpansion, "no-query-expansion", false, "Skip LLM query expansion (faster, less comprehensive)")
	cmd.Flags().IntVar(&maxOutput, "max-output", defaultMaxOutputBytes,
		"Max bytes to print before truncating (0 to disable, auto-enabled for non-TTY, ignored with --raw)")

	return cmd
}
