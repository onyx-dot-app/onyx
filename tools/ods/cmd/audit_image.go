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

Exits non-zero when an unignored finding at or above --fail-on remains, which is
how it gates deploys.`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runAuditImage(args[0], opts)
		},
	}

	cmd.Flags().StringVar(&opts.Format, "format", "text", "Output format: text, json, or sarif")
	cmd.Flags().StringVar(&opts.FailOn, "fail-on", "critical", "Minimum severity that fails the audit: critical, high, moderate, or low")
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")

	return cmd
}

func runAuditImage(ref string, opts *AuditImageOptions) {
	failOn := audit.ParseSeverity(opts.FailOn)
	if failOn == audit.SeverityUnknown {
		log.Fatalf("Invalid --fail-on %q (want critical, high, moderate, or low)", opts.FailOn)
	}

	result, err := audit.RunImage(audit.ImageOptions{
		Image:     ref,
		Format:    opts.Format,
		FailOn:    failOn,
		IgnoreURL: opts.IgnoreURL,
		Writer:    os.Stdout,
	})
	if err != nil {
		log.Fatalf("Image audit failed: %v", err)
	}

	if len(result.Blocking) > 0 {
		log.Errorf("%d finding(s) at or above %s severity must be resolved or suppressed", len(result.Blocking), failOn)
		os.Exit(1)
	}
}
