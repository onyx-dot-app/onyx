package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/overflow"
	"github.com/spf13/cobra"
)

// buildSearchRequest maps CLI flags into a SearchRequest.
// Boolean "set" parameters indicate whether the corresponding flag was explicitly provided.
func buildSearchRequest(
	query string,
	sources []string,
	days int, daysSet bool,
	limit int, limitSet bool,
	agentID int, agentIDSet bool,
	defaultAgentID int,
	noQueryExpansion bool,
) models.SearchRequest {
	req := models.SearchRequest{Query: query}

	for _, s := range sources {
		s = strings.TrimSpace(s)
		if s != "" {
			req.Sources = append(req.Sources, s)
		}
	}
	if daysSet {
		req.TimeCutoffDays = &days
	}
	if limitSet {
		req.NumResults = limit
	}
	if agentIDSet {
		req.PersonaID = &agentID
	} else if defaultAgentID != 0 {
		req.PersonaID = &defaultAgentID
	}
	if noQueryExpansion {
		req.SkipQueryExpansion = true
	}
	return req
}

func newSearchCmd(ios *iostreams.IOStreams) *cobra.Command {
	var (
		searchSources          string
		searchDays             int
		searchLimit            int
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

By default, output is the LLM-facing JSON that SearchTool produces — a
{"results": [...]} object with citation IDs, titles, content, and source
types. Use --raw for the full API response including document IDs, scores,
links, and citation mapping.

When stdout is not a TTY, output is truncated to --max-output bytes and the
full response is saved to a temp file.`,
		Args: cobra.MaximumNArgs(1),
		Example: `  onyx-cli search "What is our deployment process?"
  onyx-cli search --source slack "auth migration status"
  onyx-cli search --days 30 --limit 5 "recent production incidents"
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

			var sources []string
			if cmd.Flags().Changed("source") {
				sources = strings.Split(searchSources, ",")
			}
			req := buildSearchRequest(
				args[0],
				sources,
				searchDays, cmd.Flags().Changed("days"),
				searchLimit, cmd.Flags().Changed("limit"),
				searchAgentID, cmd.Flags().Changed("agent-id"),
				cfg.DefaultAgentID,
				searchNoQueryExpansion,
			)

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

			ow := &overflow.Writer{Limit: truncateAt, Out: ios.Out, ErrOut: ios.ErrOut}
			ow.Write(resp.LLMFacingText)
			ow.Finish()

			return nil
		},
	}

	cmd.Flags().StringVar(&searchSources, "source", "", "Filter by source type (comma-separated: slack,google_drive)")
	cmd.Flags().IntVar(&searchDays, "days", 0, "Only return results from the last N days")
	cmd.Flags().IntVar(&searchLimit, "limit", 0, "Maximum number of results (default: server decides)")
	cmd.Flags().IntVar(&searchAgentID, "agent-id", 0, "Agent ID for scoped search")
	cmd.Flags().BoolVar(&searchRaw, "raw", false, "Output full API response (results with scores, links, document IDs, citation mapping)")
	cmd.Flags().BoolVar(&searchNoQueryExpansion, "no-query-expansion", false, "Skip LLM query expansion (faster, less comprehensive)")
	cmd.Flags().IntVar(&maxOutput, "max-output", defaultMaxOutputBytes,
		"Max bytes to print before truncating (0 to disable, auto-enabled for non-TTY, ignored with --raw)")

	return cmd
}
