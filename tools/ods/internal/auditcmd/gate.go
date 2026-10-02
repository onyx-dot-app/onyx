package auditcmd

import (
	"fmt"
	"io"
	"os/exec"
	"strings"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// AuditGateOptions holds options for the `ods audit gate` command.
type AuditGateOptions struct {
	IgnoreURL string
	Script    string
}

// gateComponents are the images whose OS layer ships, in scan order.
var gateComponents = []string{"web", "model-server", "backend", "sandbox"}

// The scans behind the gate, swapped for canned results in tests.
var (
	runDeps  = audit.Run
	runImage = audit.RunImage
)

// newAuditGateCommand creates the `ods audit gate` subcommand.
func newAuditGateCommand() *cobra.Command {
	opts := &AuditGateOptions{}
	cmd := &cobra.Command{
		Use:   "gate",
		Short: "Run the deploy audit gate on the checked-out tree, as a tag build would",
		Long: `Run the deploy audit gate on the checked-out tree, as a tag build would.

Scans what deployment.yml's audit-gate scans: the lockfiles, the open Dependabot
alerts, the pinned Actions, and the OS layer each shipped image carries (the
pinned runtime base for web and model-server, the apt stages of backend and
the sandbox built from their Dockerfiles). Run it from the repository root on the commit you are
about to tag; a critical here is the one that would fail the tag build. Every
scan is strict, so a source that cannot be read (gh not signed in, no
docker login dhi.io) fails the gate instead of passing silently.

Example usage:

    $ git switch release/v4.7
    $ ods audit gate && git tag v4.7.11 && git push origin v4.7.11`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			exitOnError(runAuditGate(opts, cmd.OutOrStdout(), cmd.ErrOrStderr()))
		},
	}
	cmd.Flags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL of the advisory allowlist")
	cmd.Flags().StringVar(&opts.Script, "base-image-script", ".github/scripts/base-image-ref.sh", "Script printing the image to scan for a component")
	return cmd
}

func runAuditGate(opts *AuditGateOptions, stdout, stderr io.Writer) error {
	result, err := runDeps(audit.Options{
		Format:    "text",
		FailOn:    audit.SeverityCritical,
		IgnoreURL: opts.IgnoreURL,
		Strict:    true,
		Stdout:    stdout,
		Stderr:    stderr,
	})
	if err != nil {
		return failf("Audit failed: %v", err)
	}
	blocking := len(result.Blocking)
	for _, component := range gateComponents {
		resolve := exec.Command(opts.Script, component)
		resolve.Stderr = stderr
		out, err := resolve.Output()
		if err != nil {
			return failf("Failed to resolve the %s image: %v", component, err)
		}
		ref := strings.TrimSpace(string(out))
		_, _ = fmt.Fprintf(stderr, "\nScanning %s: %s\n", component, ref)
		res, err := runImage(audit.ImageOptions{
			Image:     ref,
			Format:    "text",
			FailOn:    audit.SeverityCritical,
			IgnoreURL: opts.IgnoreURL,
			Strict:    true,
			Stdout:    stdout,
			Stderr:    stderr,
		})
		if err != nil {
			return failf("Image audit of %s failed: %v", component, err)
		}
		blocking += len(res.Blocking)
	}
	if blocking > 0 {
		return &blockingError{count: blocking, failOn: audit.SeverityCritical}
	}
	return nil
}
