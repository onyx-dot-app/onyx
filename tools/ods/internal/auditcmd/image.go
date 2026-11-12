package auditcmd

import (
	"io"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// AuditImageOptions holds options for the `ods audit image` command.
type AuditImageOptions struct {
	SBOMOnly        bool
	Format          string
	FailOn          string
	IgnoreURL       string
	UpdatePolicyURL string
	Strict          bool
	SBOMs           []string
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

Exits non-zero when an unignored finding at or above --fail-on remains, which is
how it gates deploys.`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			exitOnError(runAuditImage(args[0], opts, cmd.OutOrStdout(), cmd.ErrOrStderr()))
		},
	}

	cmd.Flags().StringVar(&opts.Format, "format", "text", "Output format(s), comma-separated: text, json, sarif (e.g. sarif,text)")
	cmd.Flags().StringVar(&opts.FailOn, "fail-on", "critical", "Minimum severity that fails the audit: critical, high, moderate, or low")
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")
	cmd.Flags().BoolVar(&opts.Strict, "strict", false, "Fail when the scan extracts no packages from the image")

	cmd.Flags().StringSliceVar(&opts.SBOMs, "sbom", nil, "Required supplemental SBOM paths inside the image (scanned with Grype)")

	cmd.Flags().StringVar(&opts.UpdatePolicyURL, "update-policy", "", "Update policy for supplemental packages; enables freshness checks")
	cmd.Flags().BoolVar(&opts.SBOMOnly, "sbom-only", false, "Scan only the required supplemental inventories")
	return cmd
}

func runAuditImage(ref string, opts *AuditImageOptions, stdout, stderr io.Writer) error {
	failOn := audit.ParseSeverity(opts.FailOn)
	if failOn == audit.SeverityUnknown {
		return failf("Invalid --fail-on %q (want critical, high, moderate, or low)", opts.FailOn)
	}

	result, err := audit.RunImage(audit.ImageOptions{
		SBOMOnly:        opts.SBOMOnly,
		Image:           ref,
		UpdatePolicyURL: opts.UpdatePolicyURL,
		SBOMs:           opts.SBOMs,
		Format:          opts.Format,
		FailOn:          failOn,
		IgnoreURL:       opts.IgnoreURL,
		Strict:          opts.Strict,
		Stdout:          stdout,
		Stderr:          stderr,
	})
	if err != nil {
		return failf("Image audit failed: %v", err)
	}

	if result.BlockingUpdates() > 0 {
		return failf("%d package update deadlines failed", result.BlockingUpdates())
	}
	if len(result.Blocking) > 0 {
		return &blockingError{count: len(result.Blocking), failOn: failOn}
	}
	return nil
}
