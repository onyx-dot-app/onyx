package cmd

import (
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/install"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/spf13/cobra"
)

func newDeployUpgradeCmd(ios *iostreams.IOStreams) *cobra.Command {
	return newDeployUpgradeCmdWithDeps(ios, nil)
}

func newDeployUpgradeCmdWithDeps(ios *iostreams.IOStreams, deps *install.Deps) *cobra.Command {
	opts := install.Options{}

	cmd := &cobra.Command{
		Use:   "upgrade",
		Short: "Upgrade an existing Onyx deployment to a newer version",
		Long: `Upgrade an existing Onyx deployment to a newer version.

Only the IMAGE_TAG line (plus SANDBOX_BACKEND when Craft is enabled) is
rewritten in .env — every other setting, including your edits, is preserved.
Managed files (compose, overlays, nginx config) are refreshed to match the
target version; files you hand-edited are kept unless you confirm the
overwrite (or pass --force), and a backup is made first. The running
services keep serving while images download and are then recreated on the
new version.

Prod deployments (the standalone docker-compose.prod.yml, TLS via certbot)
are detected from the manifest or the prod compose file on disk; --prod
asserts it for the first adoption of an unmanaged deployment. --project
targets a stack that runs under a compose project name other than "onyx".`,
		Example: `  onyx-cli deploy upgrade
  onyx-cli deploy upgrade --tag v4.4.6
  onyx-cli deploy upgrade --tag v4.4.6 --no-prompt --force
  onyx-cli deploy upgrade --prod --project danswer-stack --dir /opt/onyx --no-prompt`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			d := install.NewDeps(ios, fullVersion())
			if deps != nil {
				d = *deps
			}
			return install.RunUpgrade(cmd.Context(), d, opts)
		},
	}

	cmd.Flags().StringVar(&opts.Tag, "tag", "", "Image tag to upgrade to (default: the latest Onyx release)")
	cmd.Flags().BoolVar(&opts.Prod, "prod", false, "Manage this as a prod deployment (the standalone docker-compose.prod.yml)")
	cmd.Flags().StringVar(&opts.Project, "project", "", `Docker compose project name (default: recorded in the manifest, else "onyx")`)
	cmd.Flags().BoolVar(&opts.Force, "force", false, "Overwrite hand-edited managed files (a backup is kept)")
	cmd.Flags().BoolVar(&opts.AllowDowngrade, "allow-downgrade", false, "Proceed when the target version is older than the installed one")
	cmd.Flags().BoolVar(&opts.Local, "local", false, "Use existing config files on disk instead of downloading")
	cmd.Flags().BoolVar(&opts.Offline, "offline", false, "Upgrade to a version already on this host and contact no network (implies --local)")
	cmd.Flags().BoolVar(&opts.NoPrompt, "no-prompt", false, "Run non-interactively with defaults")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Show what would be done without making changes")
	cmd.Flags().BoolVar(&opts.Verbose, "verbose", false, "Show detailed output for debugging")
	cmd.Flags().BoolVar(&opts.NoWait, "no-wait", false, "Return as soon as containers are started (skip health waiting)")
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Deployment directory (default: auto-detected)")

	return cmd
}
