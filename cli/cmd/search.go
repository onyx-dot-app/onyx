package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"strings"
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

// searchOutput is the top-level wrapper for `onyx-cli search` default stdout.
type searchOutput struct {
	Results    []searchOutputResult `json:"results"`
	Truncation *searchTruncation    `json:"truncation,omitempty"`
}

// searchTruncation is attached to searchOutput when results were dropped or
// trimmed to keep stdout under the output limit. The full pretty-printed
// response is saved to FullResponsePath.
type searchTruncation struct {
	Truncated        bool   `json:"truncated"`
	TotalResults     int    `json:"total_results"`
	ShownResults     int    `json:"shown_results"`
	TotalBytes       int    `json:"total_bytes"`
	ContentTruncated bool   `json:"content_truncated"`
	FullResponsePath string `json:"full_response_path"`
	Hint             string `json:"hint"`
}

// maxSearchDays caps --days at ~100 years. The cap mostly exists to keep
// `time.Duration(days) * 24h` from wrapping; nobody legitimately searches
// further back than this.
const maxSearchDays = 36500

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

// writeSearchJSON prints the search output as pretty JSON. When the payload
// exceeds truncateAt bytes (> 0), the full response is saved to a temp file
// and a smaller — but always valid — JSON envelope with truncation metadata
// is printed instead. Human-oriented notes go to stderr only.
func writeSearchJSON(ios *iostreams.IOStreams, output searchOutput, truncateAt int) error {
	data, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal response: %w", err)
	}

	if truncateAt <= 0 || len(data) <= truncateAt {
		fmt.Fprintln(ios.Out, string(data))
		return nil
	}

	fullPath, err := overflow.SaveFull("onyx-search-*.json", string(data))
	if err != nil {
		fmt.Fprintf(ios.ErrOut, "warning: could not save full response: %v\n", err)
		fullPath = ""
	}
	envelope, err := buildTruncatedSearchOutput(output, truncateAt, len(data), fullPath)
	if err != nil {
		return fmt.Errorf("failed to marshal response: %w", err)
	}
	fmt.Fprintln(ios.Out, string(envelope))

	note := fmt.Sprintf("response truncated (%d bytes total)", len(data))
	if fullPath != "" {
		note += "; full response: " + fullPath
	}
	fmt.Fprintln(ios.ErrOut, note)
	return nil
}

// buildTruncatedSearchOutput marshals a valid-JSON envelope that fits under
// limit by dropping whole results (relevance-ordered, so a prefix is kept).
// If the first result alone exceeds the limit, its content is trimmed at a
// rune boundary. The envelope may exceed limit only when the truncation
// metadata alone does: valid JSON always wins over the byte bound.
func buildTruncatedSearchOutput(
	full searchOutput, limit int, totalBytes int, fullPath string,
) ([]byte, error) {
	hint := "results were dropped to fit the output limit"
	if fullPath != "" {
		hint += "; the complete response is at full_response_path"
	}
	trunc := &searchTruncation{
		Truncated:        true,
		TotalResults:     len(full.Results),
		TotalBytes:       totalBytes,
		FullResponsePath: fullPath,
		Hint:             hint,
	}
	marshal := func(results []searchOutputResult) ([]byte, error) {
		trunc.ShownResults = len(results)
		return json.MarshalIndent(searchOutput{Results: results, Truncation: trunc}, "", "  ")
	}

	fit, data, err := largestFit(len(full.Results), limit, func(n int) ([]byte, error) {
		return marshal(full.Results[:n])
	})
	if err != nil {
		return nil, err
	}
	// Trim content only when the metadata fits but the first whole result
	// doesn't; otherwise nothing can fit and the n=0 envelope is best effort.
	if fit >= 1 || len(full.Results) == 0 || len(data) > limit {
		return data, nil
	}

	zeroEnvelope := data
	trunc.ContentTruncated = true
	trimmed := full.Results[0]
	runes := []rune(trimmed.Content)
	_, data, err = largestFit(len(runes), limit, func(k int) ([]byte, error) {
		trimmed.Content = string(runes[:k])
		return marshal([]searchOutputResult{trimmed})
	})
	if err != nil {
		return nil, err
	}
	// Even an empty-content result overflows (oversized title/url): fall back
	// to the zero-results envelope, which is known to fit.
	if len(data) > limit {
		return zeroEnvelope, nil
	}
	return data, nil
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
		Use:   "search [query]",
		Short: "Search company knowledge and return ranked documents",
		Long: `Search the Onyx knowledge base and return ranked, cited documents.

Results are retrieved using the full search pipeline: LLM query expansion,
hybrid retrieval, document selection, and context expansion — the same
search quality as the Onyx chat interface.

By default, output is a lean JSON shape tuned for LLM consumers:
{"results": [{title, url, source_type, content, updated_at}, ...]}.
Results contain only documents the LLM judged relevant, ordered by relevance;
content is the full chunk text of each. Use --raw for the full API response
(adds per-result citation_id).

When stdout is not a TTY and the response exceeds --max-output bytes, whole
results are dropped so stdout stays valid JSON; a "truncation" object carries
metadata (total_results, shown_results, full_response_path, ...) and the full
response is saved to a temp file.`,
		Args: cobra.MaximumNArgs(1),
		Example: `  onyx-cli search "What is our deployment process?"
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
			req := buildSearchRequest(searchFlags{
				query:            args[0],
				sources:          sources,
				days:             searchDays,
				daysSet:          cmd.Flags().Changed("days"),
				agentID:          searchAgentID,
				agentIDSet:       cmd.Flags().Changed("agent-id"),
				defaultAgentID:   cfg.DefaultAgentID,
				noQueryExpansion: searchNoQueryExpansion,
			})

			ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()

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

			truncateAt := 0
			if cmd.Flags().Changed("max-output") {
				truncateAt = maxOutput
			} else if !isTTY {
				truncateAt = defaultMaxOutputBytes
			}

			return writeSearchJSON(ios, toSearchOutput(*resp), truncateAt)
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
