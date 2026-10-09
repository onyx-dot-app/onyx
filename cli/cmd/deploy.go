package cmd

import (
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/spf13/cobra"
)

// newDeployCmd groups the self-hosted deployment lifecycle: the Go
// replacement for deployment/docker_compose/install.sh.
func newDeployCmd(ios *iostreams.IOStreams) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "deploy",
		Short: "Install and manage a self-hosted Onyx deployment",
		Long: `Install and manage a self-hosted Onyx deployment (docker compose).

New installs live in ~/.config/onyx by default; deployments created by the
legacy install.sh in ./onyx_data are detected and managed in place. Pass
--dir (or set ONYX_DEPLOYMENT_DIR) to target a specific location.`,
	}

	cmd.AddCommand(newDeployInstallCmd(ios))
	cmd.AddCommand(newDeployUpgradeCmd(ios))
	cmd.AddCommand(newDeployStopCmd(ios))
	cmd.AddCommand(newDeployStatusCmd(ios))
	cmd.AddCommand(newDeployLogsCmd(ios))
	cmd.AddCommand(newDeployUninstallCmd(ios))

	return cmd
}
