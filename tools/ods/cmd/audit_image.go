package cmd

import (
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// AuditImageOptions holds options for the `ods audit image` command.
type AuditImageOptions struct {
	Format    string
	FailOn    string
	IgnoreURL string
	Quiet     bool
}

// newAuditImageCommand creates the `ods audit image` subcommand.
func newAuditImageCommand() *cobra.Command {
	opts := &AuditImageOptions{}

	cmd := &cobra.Command{
		Use:   "image <ref>",
		Short: "Audit a container image for known vulnerabilities",
		Long: `Audit a container image for known vulnerabilities.

Scans the OS and language packages in a container image via osv-scanner's
layer-aware container scanner and matches them against OSV.dev. Accepted
advisories are suppressed via the same S3 allowlist used by 'ods audit', so a
release can be unblocked without a code change.

The ref may be a remote image (e.g. docker.io/onyxdotapp/onyx-backend:v1.2.3),
which is pulled using the ambient Docker credentials.

--format accepts a comma-separated list. Machine formats (json, sarif) write to
stdout while the human-readable text report writes to stderr, so a single run can
feed a SARIF upload and still print a readable report to the log:

  ods audit image "$IMAGE" --format=sarif,text > image-audit.sarif

Exits 1 when an unignored finding at or above --fail-on remains, which is how it
gates deploys, and 2 when the audit could not complete.`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runAuditImage(args[0], opts)
		},
	}

	cmd.Flags().StringVar(&opts.Format, "format", "text", "Output format(s), comma-separated: text, json, sarif (e.g. sarif,text)")
	cmd.Flags().StringVar(&opts.FailOn, "fail-on", "critical", "Minimum severity that fails the audit: critical, high, moderate, or low")
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")
	cmd.Flags().BoolVarP(&opts.Quiet, "quiet", "q", false, "Write nothing; report the verdict through the exit code only")

	return cmd
}

func runAuditImage(ref string, opts *AuditImageOptions) {
	stdout, stderr := auditWriters(opts.Quiet)

	failOn := audit.ParseSeverity(opts.FailOn)
	if failOn == audit.SeverityUnknown {
		log.Errorf("Invalid --fail-on %q (want critical, high, moderate, or low)", opts.FailOn)
		os.Exit(exitAuditError)
	}

	result, err := audit.RunImage(audit.ImageOptions{
		Image:     ref,
		Format:    opts.Format,
		FailOn:    failOn,
		IgnoreURL: opts.IgnoreURL,
		Stdout:    stdout,
		Stderr:    stderr,
	})
	if err != nil {
		log.Errorf("Image audit failed: %v", err)
		os.Exit(exitAuditError)
	}

	if len(result.Blocking) > 0 {
		log.Errorf("%d finding(s) at or above %s severity must be resolved or suppressed", len(result.Blocking), failOn)
		os.Exit(exitAuditFindings)
	}
}
