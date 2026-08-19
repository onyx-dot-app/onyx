package cmd

import (
	"io"
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// Exit codes for the audit commands. Callers that only want the verdict (see
// --quiet) use these to tell a failed gate apart from a failed run.
const (
	exitAuditFindings = 1 // unignored findings at or above --fail-on
	exitAuditError    = 2 // the audit could not complete
)

// AuditOptions holds options for the audit command.
type AuditOptions struct {
	Web        bool
	Python     bool
	Dependabot bool
	Actions    bool
	Format     string
	FailOn     string
	IgnoreURL  string
	Quiet      bool
}

// NewAuditCommand creates the `ods audit` command.
func NewAuditCommand() *cobra.Command {
	opts := &AuditOptions{}

	cmd := &cobra.Command{
		Use:   "audit",
		Short: "Audit dependencies for known vulnerabilities",
		Long: `Audit dependencies for known vulnerabilities.

Scans the JavaScript (bun.lock) and Python (uv.lock) lockfiles via osv-scanner,
open GitHub Dependabot security alerts, and the GitHub Actions pinned in
.github/workflows and .github/actions against OSV.dev. With no selector flags,
all sources are audited. Accepted advisories are suppressed via an allowlist
fetched from S3 at runtime, so releases can be unblocked without a code change.

Exits 1 when an unignored finding at or above --fail-on remains, which is how it
gates deploys, and 2 when the audit could not complete.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runAudit(opts)
		},
	}

	cmd.Flags().BoolVar(&opts.Web, "web", false, "Audit web/JS dependencies (bun.lock)")
	cmd.Flags().BoolVar(&opts.Python, "python", false, "Audit Python dependencies (uv.lock)")
	cmd.Flags().BoolVar(&opts.Dependabot, "dependabot", false, "Audit open Dependabot security alerts")
	cmd.Flags().BoolVar(&opts.Actions, "actions", false, "Audit GitHub Actions in .github/workflows and .github/actions")
	cmd.Flags().StringVar(&opts.Format, "format", "text", "Output format(s), comma-separated: text, json, sarif (e.g. sarif,text)")
	cmd.Flags().StringVar(&opts.FailOn, "fail-on", "critical", "Minimum severity that fails the audit: critical, high, moderate, or low")
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")
	cmd.Flags().BoolVarP(&opts.Quiet, "quiet", "q", false, "Write nothing; report the verdict through the exit code only")

	cmd.AddCommand(newAuditImageCommand())
	cmd.AddCommand(newAuditIgnoreCommand())

	return cmd
}

// auditWriters returns the report streams for an audit run. When quiet is set
// it also silences every logger the audit path writes through — logrus and
// osv-scanner's slog handler — so the run produces no output at all and only
// the exit code carries the verdict.
func auditWriters(quiet bool) (stdout, stderr io.Writer) {
	if !quiet {
		return os.Stdout, os.Stderr
	}
	log.SetOutput(io.Discard)
	audit.SilenceLogger()
	return io.Discard, io.Discard
}

func runAudit(opts *AuditOptions) {
	stdout, stderr := auditWriters(opts.Quiet)

	failOn := audit.ParseSeverity(opts.FailOn)
	if failOn == audit.SeverityUnknown {
		log.Errorf("Invalid --fail-on %q (want critical, high, moderate, or low)", opts.FailOn)
		os.Exit(exitAuditError)
	}

	result, err := audit.Run(audit.Options{
		Web:        opts.Web,
		Python:     opts.Python,
		Dependabot: opts.Dependabot,
		Actions:    opts.Actions,
		Format:     opts.Format,
		FailOn:     failOn,
		IgnoreURL:  opts.IgnoreURL,
		Stdout:     stdout,
		Stderr:     stderr,
	})
	if err != nil {
		log.Errorf("Audit failed: %v", err)
		os.Exit(exitAuditError)
	}

	if len(result.Blocking) > 0 {
		log.Errorf("%d finding(s) at or above %s severity must be resolved or suppressed", len(result.Blocking), failOn)
		os.Exit(exitAuditFindings)
	}
}
