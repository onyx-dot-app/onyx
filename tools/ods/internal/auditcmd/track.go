package auditcmd

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// AuditTrackOptions holds options for the `ods audit track` command.
type AuditTrackOptions struct {
	Alerts  string
	History string
	Summary string
}

// newAuditTrackCommand creates the `ods audit track` subcommand.
func newAuditTrackCommand() *cobra.Command {
	opts := &AuditTrackOptions{}

	cmd := &cobra.Command{
		Use:   "track",
		Short: "Record today's CVE counts per image",
		Long: `Record today's CVE counts per image.

Reads the repository's code scanning alerts (--alerts, the output of
"gh api --paginate repos/OWNER/REPO/code-scanning/alerts") and counts the image
audits' CVEs per image: total, open, resolved, and open by severity, flagging
the ones open 90 days or more. Adds the counts to the --history file as
today's snapshot, replacing an earlier one from today, and creates the file if
it is missing. --summary writes the Slack summary of the latest snapshot.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			exitOnError(runAuditTrack(opts, time.Now()))
		},
	}

	cmd.Flags().StringVar(&opts.Alerts, "alerts", "", "JSON code scanning alerts, one or more concatenated arrays (required)")
	cmd.Flags().StringVar(&opts.History, "history", "", "JSON history file to update (required)")
	cmd.Flags().StringVar(&opts.Summary, "summary", "", "Write the Slack summary to this file")
	_ = cmd.MarkFlagRequired("alerts")
	_ = cmd.MarkFlagRequired("history")

	return cmd
}

func runAuditTrack(opts *AuditTrackOptions, now time.Time) error {
	alerts, err := readCodeScanningAlerts(opts.Alerts)
	if err != nil {
		return err
	}
	history, err := audit.ReadHistory(opts.History)
	if err != nil {
		return err
	}
	history.Record(audit.BuildSnapshot(alerts, now))
	if err := audit.WriteHistory(opts.History, history); err != nil {
		return err
	}
	if opts.Summary == "" {
		return nil
	}
	return os.WriteFile(opts.Summary, []byte(audit.RenderTrackSummary(history)+"\n"), 0644)
}

// readCodeScanningAlerts reads gh's paginated output, one JSON array per page.
func readCodeScanningAlerts(path string) ([]audit.CodeScanningAlert, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer func() { _ = f.Close() }()
	var all []audit.CodeScanningAlert
	dec := json.NewDecoder(f)
	for {
		var page []audit.CodeScanningAlert
		err := dec.Decode(&page)
		if errors.Is(err, io.EOF) {
			return all, nil
		}
		if err != nil {
			return nil, fmt.Errorf("failed to parse code scanning alerts %s: %w", path, err)
		}
		all = append(all, page...)
	}
}
