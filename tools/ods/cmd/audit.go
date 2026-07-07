package cmd

import (
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
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

Exits non-zero when an unignored finding at or above --fail-on remains, which is
how it gates deploys.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runAudit(opts)
		},
	}

	cmd.Flags().BoolVar(&opts.Web, "web", false, "Audit web/JS dependencies (bun.lock)")
	cmd.Flags().BoolVar(&opts.Python, "python", false, "Audit Python dependencies (uv.lock)")
	cmd.Flags().BoolVar(&opts.Dependabot, "dependabot", false, "Audit open Dependabot security alerts")
	cmd.Flags().BoolVar(&opts.Actions, "actions", false, "Audit GitHub Actions in .github/workflows and .github/actions")
	cmd.Flags().StringVar(&opts.Format, "format", "text", "Output format: text, json, or sarif")
	cmd.Flags().StringVar(&opts.FailOn, "fail-on", "critical", "Minimum severity that fails the audit: critical, high, moderate, or low")
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")

	cmd.AddCommand(newAuditImageCommand())
	cmd.AddCommand(newAuditIgnoreCommand())

	return cmd
}

func runAudit(opts *AuditOptions) {
	failOn := audit.ParseSeverity(opts.FailOn)
	if failOn == audit.SeverityUnknown {
		log.Fatalf("Invalid --fail-on %q (want critical, high, moderate, or low)", opts.FailOn)
	}

	result, err := audit.Run(audit.Options{
		Web:        opts.Web,
		Python:     opts.Python,
		Dependabot: opts.Dependabot,
		Actions:    opts.Actions,
		Format:     opts.Format,
		FailOn:     failOn,
		IgnoreURL:  opts.IgnoreURL,
		Writer:     os.Stdout,
	})
	if err != nil {
		log.Fatalf("Audit failed: %v", err)
	}

	if len(result.Blocking) > 0 {
		log.Errorf("%d finding(s) at or above %s severity must be resolved or suppressed", len(result.Blocking), failOn)
		os.Exit(1)
	}
}
