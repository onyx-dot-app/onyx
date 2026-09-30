package auditcmd

import (
	"encoding/json"
	"io"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// AuditAlertOptions holds options for the `ods audit alert` command.
type AuditAlertOptions struct {
	Results   []string
	IgnoreURL string
	Scope     string
	KeepOpen  bool
	DryRun    bool
}

// newAuditAlertCommand creates the `ods audit alert` subcommand.
func newAuditAlertCommand() *cobra.Command {
	opts := &AuditAlertOptions{}

	cmd := &cobra.Command{
		Use:   "alert",
		Short: "Sync the tracking issues for blocking vulnerabilities",
		Long: `Sync the tracking issues for blocking vulnerabilities.

Reads the JSON results of earlier "ods audit --format=json" and "ods audit image
--format=json" runs and keeps one open GitHub issue (label ` + audit.AlertLabel + `) per package and branch (--scope)
with a blocking finding. It opens an issue for a newly blocking package, updates
the issue when the package gains an advisory, and closes the issues of packages
that no longer block. Pass the results of every scan, since a package missing
from all of them counts as resolved.

The sync applies the allowlist itself and fails if it cannot fetch it, so a
suppressed advisory never opens an issue, and suppressing a package's last
advisory closes its issue.

Prints the alerts that need announcing (new packages and new advisories) to
stdout as a JSON array, also when a later issue change fails and the command
exits non-zero. --dry-run reads the open issues and prints the alerts but
changes nothing.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			exitOnError(runAuditAlert(opts, cmd.OutOrStdout()))
		},
	}

	cmd.Flags().StringArrayVar(&opts.Results, "results", nil, "JSON audit result file (repeatable, required)")
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")
	cmd.Flags().StringVar(&opts.Scope, "scope", "main", "Branch the results came from, which keys the issues and fix branches")
	cmd.Flags().BoolVar(&opts.KeepOpen, "keep-open", false, "Close no issue, for a run that skipped a scan")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Print the alerts without changing any issue")
	_ = cmd.MarkFlagRequired("results")

	return cmd
}

func runAuditAlert(opts *AuditAlertOptions, stdout io.Writer) error {
	alerts, syncErr := audit.SyncAlerts(audit.SyncAlertsOptions{
		ResultFiles: opts.Results,
		IgnoreURL:   opts.IgnoreURL,
		Scope:       opts.Scope,
		KeepOpen:    opts.KeepOpen,
		DryRun:      opts.DryRun,
	})
	if alerts == nil {
		alerts = []audit.Alert{}
	}
	// Print the recorded alerts even after a failed sync, so they still get
	// announced.
	enc := json.NewEncoder(stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(alerts); err != nil {
		return err
	}
	if syncErr != nil {
		return failf("Alert sync failed: %v", syncErr)
	}
	return nil
}
