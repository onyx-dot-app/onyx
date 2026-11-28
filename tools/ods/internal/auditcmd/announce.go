package auditcmd

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// AuditAnnounceOptions holds options for the `ods audit announce` command.
type AuditAnnounceOptions struct {
	Failing   string
	TriageDir string
	Threads   string
	Branch    string
	RunURL    string
	AuditURL  string
	Owner     string
	Expires   string
}

// newAuditAnnounceCommand creates the `ods audit announce` subcommand.
func newAuditAnnounceCommand() *cobra.Command {
	opts := &AuditAnnounceOptions{}

	cmd := &cobra.Command{
		Use:   "announce",
		Short: "Plan a CVE Alerts run's #cve-reviews posts",
		Long: `Plan a CVE Alerts run's #cve-reviews posts.

Reads the run's blocking alerts (--failing, from "ods audit alert --failing"),
the triage summaries its publish jobs wrote (--triage-dir, one JSON file per
issue), and the Slack thread each earlier advisory was announced in (--threads,
a JSON object of advisory id to message ts).

Every advisory with no thread goes in one top-level post owned by --owner,
naming the image it surfaced in, with an ignore command for each. An advisory
announced before gets a follow-up in its thread instead. Prints the plan as
JSON and posts nothing.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			exitOnError(runAuditAnnounce(opts, cmd.OutOrStdout()))
		},
	}

	cmd.Flags().StringVar(&opts.Failing, "failing", "", "JSON file of the run's blocking alerts (required)")
	cmd.Flags().StringVar(&opts.TriageDir, "triage-dir", "", "Directory of per-issue triage summaries")
	cmd.Flags().StringVar(&opts.Threads, "threads", "", "JSON file mapping advisory ids to Slack thread timestamps")
	cmd.Flags().StringVar(&opts.Branch, "branch", "main", "Branch the run scanned")
	cmd.Flags().StringVar(&opts.RunURL, "run-url", "", "URL of this CVE Alerts run (required)")
	cmd.Flags().StringVar(&opts.AuditURL, "audit-url", "", "URL of the failed audit run that dispatched this one")
	cmd.Flags().StringVar(&opts.Owner, "owner", "", "Slack mention of the run's reviewer")
	cmd.Flags().StringVar(&opts.Expires, "expires", "", "Date for the temporary ignore commands (default: 30 days out)")
	_ = cmd.MarkFlagRequired("failing")
	_ = cmd.MarkFlagRequired("run-url")

	return cmd
}

func runAuditAnnounce(opts *AuditAnnounceOptions, stdout io.Writer) error {
	var failing []audit.Alert
	if err := readJSONFile(opts.Failing, &failing); err != nil {
		return err
	}
	threads := map[string]string{}
	if opts.Threads != "" {
		if err := readJSONFile(opts.Threads, &threads); err != nil {
			return err
		}
	}
	triage := map[int]audit.TriageSummary{}
	if opts.TriageDir != "" {
		paths, err := filepath.Glob(filepath.Join(opts.TriageDir, "*.json"))
		if err != nil {
			return err
		}
		for _, path := range paths {
			var t audit.TriageSummary
			if err := readJSONFile(path, &t); err != nil {
				return err
			}
			triage[t.Issue] = t
		}
	}
	expires := opts.Expires
	if expires == "" {
		expires = time.Now().UTC().AddDate(0, 0, 30).Format(time.DateOnly)
	}
	plan := audit.PlanAnnouncement(audit.AnnounceOptions{
		Failing:  failing,
		Triage:   triage,
		Threads:  threads,
		Branch:   opts.Branch,
		RunURL:   opts.RunURL,
		AuditURL: opts.AuditURL,
		Owner:    opts.Owner,
		Expires:  expires,
	})
	enc := json.NewEncoder(stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(plan)
}

func readJSONFile(path string, v any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(data, v); err != nil {
		return fmt.Errorf("failed to parse %s: %w", path, err)
	}
	return nil
}
