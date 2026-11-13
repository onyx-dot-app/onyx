package auditcmd

import (
	"io"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// AuditCraftFCOptions holds options for the `ods audit craft-fc` command.
type AuditCraftFCOptions struct {
	Dockerfile string
	Format     string
	FailOn     string
	IgnoreURL  string
}

// newAuditCraftFCCommand creates the `ods audit craft-fc` subcommand.
func newAuditCraftFCCommand() *cobra.Command {
	opts := &AuditCraftFCOptions{}

	cmd := &cobra.Command{
		Use:   "craft-fc",
		Short: "Audit the Craft Firecracker guest kernel and Firecracker pins",
		Long: `Audit the Craft Firecracker guest kernel and Firecracker pins.

A package scanner cannot read a bare vmlinux or the Firecracker binaries, so
this command matches the versions pinned in deployment/craft-fc/Dockerfile.artifacts
against their advisory feeds:

  - the guest kernel (an Amazon Linux microvm-kernel tag) against the Amazon
    Linux 2023 advisories (ALAS) of the same kernel series, reporting each
    advisory fixed in a newer package than the pin;
  - Firecracker against the GitHub security advisories of
    firecracker-microvm/firecracker.

The same S3 allowlist as 'ods audit' applies. A feed that cannot be read fails
the command. Set GH_TOKEN to raise the GitHub API rate limit.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, _ []string) {
			exitOnError(runAuditCraftFC(opts, cmd.OutOrStdout(), cmd.ErrOrStderr()))
		},
	}

	cmd.Flags().StringVar(&opts.Dockerfile, "dockerfile", audit.DefaultCraftFCDockerfile, "Dockerfile with the KERNEL_TAG and FC_VERSION pins, relative to the repository root")
	cmd.Flags().StringVar(&opts.Format, "format", "text", "Output format(s), comma-separated: text, json, sarif (e.g. sarif,text)")
	cmd.Flags().StringVar(&opts.FailOn, "fail-on", "critical", "Minimum severity that fails the audit: critical, high, moderate, or low")
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")
	return cmd
}

func runAuditCraftFC(opts *AuditCraftFCOptions, stdout, stderr io.Writer) error {
	failOn := audit.ParseSeverity(opts.FailOn)
	if failOn == audit.SeverityUnknown {
		return failf("Invalid --fail-on %q (want critical, high, moderate, or low)", opts.FailOn)
	}

	result, err := audit.RunCraftFC(audit.CraftFCOptions{
		Dockerfile: opts.Dockerfile,
		Format:     opts.Format,
		FailOn:     failOn,
		IgnoreURL:  opts.IgnoreURL,
		Stdout:     stdout,
		Stderr:     stderr,
	})
	if err != nil {
		return failf("Craft Firecracker audit failed: %v", err)
	}
	if len(result.Blocking) > 0 {
		return &blockingError{count: len(result.Blocking), failOn: failOn}
	}
	return nil
}
