package auditcmd

import (
	"errors"
	"fmt"
	"io"
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
	Debug      bool
}

// NewRootCommand creates the root command of the `ods-audit` binary. `ods audit`
// forwards to it, so both spellings run the same code.
func NewRootCommand(version, commit string) *cobra.Command {
	opts := &AuditOptions{}

	cmd := &cobra.Command{
		Use:   "ods-audit",
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
		PersistentPreRun: func(cmd *cobra.Command, args []string) {
			if opts.Debug {
				log.SetLevel(log.DebugLevel)
			} else {
				log.SetLevel(log.InfoLevel)
			}
			log.SetFormatter(&log.TextFormatter{
				DisableTimestamp: true,
			})
		},
		Run: func(cmd *cobra.Command, args []string) {
			exitOnError(runAudit(opts, cmd.OutOrStdout(), cmd.ErrOrStderr()))
		},
		Version: fmt.Sprintf("%s\ncommit %s", version, commit),
	}

	cmd.PersistentFlags().BoolVar(&opts.Debug, "debug", false, "run in debug mode")
	cmd.Flags().BoolVar(&opts.Web, "web", false, "Audit web/JS dependencies (bun.lock)")
	cmd.Flags().BoolVar(&opts.Python, "python", false, "Audit Python dependencies (uv.lock)")
	cmd.Flags().BoolVar(&opts.Dependabot, "dependabot", false, "Audit open Dependabot security alerts")
	cmd.Flags().BoolVar(&opts.Actions, "actions", false, "Audit GitHub Actions in .github/workflows and .github/actions")
	cmd.Flags().StringVar(&opts.Format, "format", "text", "Output format(s), comma-separated: text, json, sarif (e.g. sarif,text)")
	cmd.Flags().StringVar(&opts.FailOn, "fail-on", "critical", "Minimum severity that fails the audit: critical, high, moderate, or low")
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")

	cmd.AddCommand(newAuditImageCommand())
	cmd.AddCommand(newAuditIgnoreCommand(terminalEditUI()))

	return cmd
}

// blockingError reports unignored findings at or above the --fail-on threshold.
// It exits 1 like any other failure, but logs at error rather than fatal level.
type blockingError struct {
	count  int
	failOn audit.Severity
}

func (e *blockingError) Error() string {
	return fmt.Sprintf("%d finding(s) at or above %s severity must be resolved or suppressed", e.count, e.failOn)
}

// commandError is a command failure whose text is the exact line logged on
// exit, so it may start with a capital letter.
type commandError struct {
	msg string
}

func (e *commandError) Error() string {
	return e.msg
}

func failf(format string, args ...any) error {
	return &commandError{msg: fmt.Sprintf(format, args...)}
}

// exitOnError ends the process when a command body returns an error.
func exitOnError(err error) {
	if err == nil {
		return
	}
	var blocking *blockingError
	if errors.As(err, &blocking) {
		log.Error(blocking.Error())
		os.Exit(1)
	}
	log.Fatal(err)
}

func runAudit(opts *AuditOptions, stdout, stderr io.Writer) error {
	failOn := audit.ParseSeverity(opts.FailOn)
	if failOn == audit.SeverityUnknown {
		return failf("Invalid --fail-on %q (want critical, high, moderate, or low)", opts.FailOn)
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
		return failf("Audit failed: %v", err)
	}

	if len(result.Blocking) > 0 {
		return &blockingError{count: len(result.Blocking), failOn: failOn}
	}
	return nil
}
