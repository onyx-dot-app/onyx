package cmd

import (
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/install"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/spf13/cobra"
)

func newDeployInstallCmd(ios *iostreams.IOStreams) *cobra.Command {
	return newDeployInstallCmdWithDeps(ios, nil)
}

// newDeployInstallCmdWithDeps lets tests inject fake dependencies.
func newDeployInstallCmdWithDeps(ios *iostreams.IOStreams, deps *install.Deps) *cobra.Command {
	opts := install.Options{}
	var legacyShutdown, legacyDeleteData bool

	cmd := &cobra.Command{
		Use:   "install",
		Short: "Install or restart a self-hosted Onyx deployment",
		Long: `Install a self-hosted Onyx deployment with docker compose, or restart /
update an existing one.

The deployment files bundled with this CLI are used by default; installing a
pinned release tag fetches the files matching that version from GitHub. On
Linux, missing Docker Engine and the compose plugin are installed after
confirmation. Run non-interactively with --no-prompt (defaults are applied to
every prompt, including Lite mode).`,
		Example: `  onyx-cli deploy install
  onyx-cli deploy install --lite --no-prompt
  onyx-cli deploy install --include-craft
  onyx-cli deploy install --tag v4.4.6
  onyx-cli deploy install --dry-run`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if legacyShutdown {
				return exitcodes.New(exitcodes.BadRequest,
					"--shutdown has moved: run `onyx-cli deploy stop`")
			}
			if legacyDeleteData {
				return exitcodes.New(exitcodes.BadRequest,
					"--delete-data has moved: run `onyx-cli deploy uninstall`")
			}
			d := install.NewDeps(ios, fullVersion())
			if deps != nil {
				d = *deps
			}
			return install.RunInstall(cmd.Context(), d, opts)
		},
	}

	// Flag names match install.sh so bootstrap passthrough keeps working.
	cmd.Flags().BoolVar(&opts.Lite, "lite", false, "Deploy Onyx Lite (no OpenSearch, Redis, or model servers)")
	cmd.Flags().BoolVar(&opts.IncludeCraft, "include-craft", false, "Enable Onyx Craft (AI-powered web app building)")
	cmd.Flags().StringVar(&opts.Tag, "tag", "", "Image tag to deploy (default: the latest Onyx release)")
	cmd.Flags().BoolVar(&opts.Local, "local", false, "Use existing config files on disk instead of downloading")
	cmd.Flags().BoolVar(&opts.Offline, "offline", false, "Deploy from the images already on this host and contact no network (implies --local)")
	cmd.Flags().BoolVar(&opts.NoPrompt, "no-prompt", false, "Run non-interactively with defaults (for CI/automation)")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Show what would be done without making changes")
	cmd.Flags().BoolVar(&opts.Verbose, "verbose", false, "Show detailed output for debugging")
	cmd.Flags().BoolVar(&opts.NoWait, "no-wait", false, "Return as soon as containers are started (skip health waiting)")
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Deployment directory (default: ~/.config/onyx, or an existing ./onyx_data)")
	cmd.Flags().BoolVar(&opts.Force, "force", false, "Overwrite hand-edited managed files (a backup is kept) and recreate running services")

	// Retired install.sh mode flags: recognized so saved one-liners get a
	// redirect message instead of a raw unknown-flag error.
	cmd.Flags().BoolVar(&legacyShutdown, "shutdown", false, "")
	cmd.Flags().BoolVar(&legacyDeleteData, "delete-data", false, "")
	_ = cmd.Flags().MarkHidden("shutdown")
	_ = cmd.Flags().MarkHidden("delete-data")

	return cmd
}

// newInstallOnyxCmd is the documented curl|bash entrypoint: a top-level alias
// for `deploy install`.
func newInstallOnyxCmd(ios *iostreams.IOStreams) *cobra.Command {
	cmd := newDeployInstallCmd(ios)
	cmd.Use = "install-onyx"
	cmd.Short = "Install a self-hosted Onyx deployment (alias for `deploy install`)"
	return cmd
}
