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

// multiSearchEntry is one query's outcome. On failure Error is set and
// Results is null; otherwise it mirrors the single-query shape.
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

// maxSearchQueries caps one invocation at the number of /search calls run in
// parallel — every accepted query is in flight at once.
const maxSearchQueries = 3

// maxInlineErrorBytes caps the JSON-encoded size of each in-band per-query
// error string (an upstream error body can be a whole HTML page).
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

// clampError bounds an error's JSON-encoded size for in-band output — the
// encoded size is what matters, since escaping expands some bytes six-fold.
func clampError(err error) string {
	msg := err.Error()
	if data, err := json.Marshal(msg); err == nil && len(data) <= maxInlineErrorBytes {
		return msg
	}
	const suffix = " … (truncated)"
	runes := []rune(msg)
	fit, _, err := largestFit(len(runes), maxInlineErrorBytes, func(n int) ([]byte, error) {
		return json.Marshal(string(runes[:n]) + suffix)
	})
	if err != nil {
		// Unreachable: marshaling a string cannot fail.
		return suffix
	}
	return string(runes[:fit]) + suffix
}

// writeJSONReduced prints payload as pretty JSON. When it exceeds truncateAt
// bytes (> 0), the full response is saved to a temp file — dropped data must
// never be unrecoverable — and the envelope built by reduce prints instead.
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

func writeSearchJSON(ios *iostreams.IOStreams, output searchOutput, truncateAt int) error {
	return writeJSONReduced(ios, output, truncateAt,
		func(totalBytes int, fullPath string) (searchOutput, error) {
			return truncateSearchOutput(output, truncateAt, totalBytes, fullPath)
		})
}

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

// truncateMultiSearchOutput fits multi-query output under limit by capping
// every entry at the largest uniform result count k that fits, so small
// result sets pass through whole. When no k fits (one result can outweigh
// the whole budget), entries are instead reduced against an even share each.
// The k=0 render is the floor: valid JSON and one entry per query beat the
// byte bound.
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

	// Rendered size is not monotone in k (an entry sheds its truncation
	// metadata once k reaches its result count), so binary search would skip
	// fitting candidates; scan from the top instead.
	for k := maxResults; k > 0; k-- {
		out, data, err := render(k)
		if err != nil {
			return multiSearchOutput{}, err
		}
		if len(data) <= limit {
			return out, nil
		}
	}

	// A one-result entry cannot shrink below k=1, so one oversized result
	// defeats every k. Reduce each entry against an even share instead.
	share := limit / len(full.Searches)
	shared := multiSearchOutput{Searches: make([]multiSearchEntry, 0, len(full.Searches))}
	for _, entry := range full.Searches {
		single := searchOutput{Results: entry.Results}
		data, err := json.MarshalIndent(single, "", "  ")
		if err != nil {
			return multiSearchOutput{}, err
		}
		if entry.Error != "" || len(data) <= share {
			shared.Searches = append(shared.Searches, entry)
			continue
		}
		reduced, err := truncateSearchOutput(single, share, totalBytes, fullPath)
		if err != nil {
			return multiSearchOutput{}, err
		}
		shared.Searches = append(shared.Searches, multiSearchEntry{
			Query:      entry.Query,
			Results:    reduced.Results,
			Truncation: reduced.Truncation,
		})
	}
	data, err := json.MarshalIndent(shared, "", "  ")
	if err != nil {
		return multiSearchOutput{}, err
	}
	if len(data) <= limit {
		return shared, nil
	}
	out, _, err := render(0)
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

Multiple queries (up to 3 per invocation) run concurrently, so batching
independent queries is much faster than separate sequential calls. Flags
apply to every query. The command fails only when every query fails;
otherwise failed queries carry an in-band "error" field with null results.

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
					"no query provided\n  Usage: onyx-cli search \"your query\" [\"another query\" ...]")
			}
			if len(args) > maxSearchQueries {
				return exitcodes.New(exitcodes.BadRequest, fmt.Sprintf(
					"%d queries exceeds the per-invocation limit of %d — split the batch into smaller calls, and check that an unquoted glob or sentence didn't expand into separate arguments",
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

			// All-single-word args often mean one unquoted query; the shell
			// strips quotes before argv, so a hint is all this can be.
			if len(args) > 1 && !strings.ContainsAny(strings.Join(args, ""), " \t") {
				fmt.Fprintln(ios.ErrOut, "note: each argument searches separately — quote multi-word queries")
			}

			isTTY := ios.IsStdoutTTY
			if isTTY {
				if len(args) > 1 {
					fmt.Fprintf(ios.ErrOut, "\033[2mSearching (%d queries)...\033[0m\n", len(args))
				} else {
					fmt.Fprintf(ios.ErrOut, "\033[2mSearching...\033[0m\n")
				}
			}

			responses := make([]*models.SearchResponse, len(args))
			errs := make([]error, len(args))
			var wg sync.WaitGroup
			for i, query := range args {
				wg.Add(1)
				go func(i int, query string) {
					defer wg.Done()
					flags := baseFlags
					flags.query = query
					responses[i], errs[i] = client.Search(ctx, buildSearchRequest(flags))
				}(i, query)
			}
			wg.Wait()

			failures := 0
			for _, err := range errs {
				if err != nil {
					failures++
				}
			}
			if failures == len(args) {
				label := "search failed"
				if len(args) > 1 {
					for i := 1; i < len(args); i++ {
						fmt.Fprintf(ios.ErrOut, "search failed for %q: %s\n", args[i], clampError(errs[i]))
					}
					label = fmt.Sprintf("search failed for %q", args[0])
				}
				return apiErrorToExit(errs[0], label)
			}

			// An interrupted batch prints what it completed but must not
			// exit 0; interruptErr replaces the final nil returns below.
			var interruptErr error
			if ctx.Err() != nil {
				for _, err := range errs {
					if err != nil {
						interruptErr = apiErrorToExit(err, "search interrupted")
						break
					}
				}
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
					return interruptErr
				}
				if err := writeSearchJSON(ios, toSearchOutput(*responses[0]), truncateAt); err != nil {
					return err
				}
				return interruptErr
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
				return interruptErr
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
			if err := writeMultiSearchJSON(ios, output, truncateAt); err != nil {
				return err
			}
			return interruptErr
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
