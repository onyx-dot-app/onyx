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
// (without --raw). One ``content`` field per result, no Onyx-internal jargon.
type searchOutputResult struct {
	Title      string  `json:"title"`
	URL        *string `json:"url"`
	SourceType string  `json:"source_type"`
	Content    string  `json:"content"`
	UpdatedAt  *string `json:"updated_at"`
}

// searchOutput is the top-level wrapper for `onyx-cli search` default stdout.
type searchOutput struct {
	Results []searchOutputResult `json:"results"`
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

When stdout is not a TTY, output is truncated to --max-output bytes and the
full response is saved to a temp file.`,
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

			output := toSearchOutput(*resp)
			data, err := json.MarshalIndent(output, "", "  ")
			if err != nil {
				return fmt.Errorf("failed to marshal response: %w", err)
			}

			ow := &overflow.Writer{Limit: truncateAt, Out: ios.Out, ErrOut: ios.ErrOut}
			ow.Write(string(data))
			ow.Finish()

			return nil
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
