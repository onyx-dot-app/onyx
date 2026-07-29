package cmd

import (
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/install"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/spf13/cobra"
)

func newDeployStopCmd(ios *iostreams.IOStreams) *cobra.Command {
	return newDeployStopCmdWithDeps(ios, nil)
}

func newDeployStopCmdWithDeps(ios *iostreams.IOStreams, deps *install.Deps) *cobra.Command {
	opts := install.Options{}
	cmd := &cobra.Command{
		Use:   "stop",
		Short: "Stop (pause) the Onyx containers",
		Long: `Stop the Onyx containers without removing them or their data.
Start them again with: onyx-cli deploy install`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			d := install.NewDeps(ios, fullVersion())
			if deps != nil {
				d = *deps
			}
			return install.RunStop(cmd.Context(), d, opts)
		},
	}
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Deployment directory (default: auto-detected)")
	return cmd
}

func newDeployStatusCmd(ios *iostreams.IOStreams) *cobra.Command {
	return newDeployStatusCmdWithDeps(ios, nil)
}

func newDeployStatusCmdWithDeps(ios *iostreams.IOStreams, deps *install.Deps) *cobra.Command {
	opts := install.Options{}
	var jsonOut bool
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show the deployment's version, containers, and health",
		Long: `Show the state of a deployment: the installed version as recorded by the
CLI, by .env, and by the running containers (drift between them is flagged),
plus per-container status and health.

Read-only. Exit codes make it usable as a probe: 0 when everything is up and
healthy, 9 when no install exists, 1 when stopped or degraded.`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			d := install.NewDeps(ios, fullVersion())
			if deps != nil {
				d = *deps
			}
			return install.RunStatus(cmd.Context(), d, opts, jsonOut)
		},
	}
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Deployment directory (default: auto-detected)")
	cmd.Flags().BoolVar(&jsonOut, "json", false, "Output machine-readable JSON")
	return cmd
}

func newDeployLogsCmd(ios *iostreams.IOStreams) *cobra.Command {
	return newDeployLogsCmdWithDeps(ios, nil)
}

func newDeployLogsCmdWithDeps(ios *iostreams.IOStreams, deps *install.Deps) *cobra.Command {
	opts := install.Options{}
	logOpts := install.LogOptions{}
	cmd := &cobra.Command{
		Use:   "logs [service...]",
		Short: "Show the logs of the deployment's containers",
		Long: `Show the logs of a deployment's services, with no need to find the
deployment directory or remember which compose overlays it uses.

Name the services to narrow the output ("onyx-cli deploy logs api_server"),
which is what "onyx-cli deploy status" suggests for a service in trouble.`,
		Args: cobra.ArbitraryArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			d := install.NewDeps(ios, fullVersion())
			if deps != nil {
				d = *deps
			}
			logOpts.Services = args
			return install.RunLogs(cmd.Context(), d, opts, logOpts)
		},
	}
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Deployment directory (default: auto-detected)")
	cmd.Flags().BoolVarP(&logOpts.Follow, "follow", "f", false, "Keep printing new log lines")
	cmd.Flags().StringVar(&logOpts.Tail, "tail", "200", `Lines to show from the end of each log ("all" for everything)`)
	cmd.Flags().StringVar(&logOpts.Since, "since", "", "Only logs since this point (e.g. 10m, 2h, or a timestamp)")
	return cmd
}

func newDeployUninstallCmd(ios *iostreams.IOStreams) *cobra.Command {
	return newDeployUninstallCmdWithDeps(ios, nil)
}

func newDeployUninstallCmdWithDeps(ios *iostreams.IOStreams, deps *install.Deps) *cobra.Command {
	opts := install.Options{}
	cmd := &cobra.Command{
		Use:   "uninstall",
		Short: "Permanently delete the Onyx deployment and all its data",
		Long: `Remove the Onyx containers, volumes, and the deployment directory.

This permanently deletes all user data and documents. Interactive runs must
type DELETE to confirm; non-interactive runs require --force.`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			d := install.NewDeps(ios, fullVersion())
			if deps != nil {
				d = *deps
			}
			return install.RunUninstall(cmd.Context(), d, opts)
		},
	}
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Deployment directory (default: auto-detected)")
	cmd.Flags().BoolVar(&opts.Force, "force", false, "Skip the confirmation (for scripted teardown)")
	return cmd
}
