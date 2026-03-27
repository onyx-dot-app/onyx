// Package cmd implements Cobra CLI commands for the Onyx CLI.
package cmd

import (
	"context"
	"fmt"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/version"
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

// Version and Commit are set via ldflags at build time.
var (
	Version string
	Commit  string
)

func fullVersion() string {
	if Commit != "" && Commit != "none" && len(Commit) > 7 {
		return Version + " (" + Commit[:7] + ")"
	}
	return Version
}

func printVersion(cmd *cobra.Command) {
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Client version: %s\n", fullVersion())

	cfg := config.Load()
	if !cfg.IsConfigured() {
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Server version: unknown (not configured)\n")
		return
	}

	client := api.NewClient(cfg)
	ctx, cancel := context.WithTimeout(cmd.Context(), 5*time.Second)
	defer cancel()

	log.Debug("fetching backend version from /api/version")
	backendVersion, err := client.GetBackendVersion(ctx)
	if err != nil {
		log.WithError(err).Debug("could not fetch backend version")
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Server version: unknown (could not reach server)\n")
		return
	}

	if backendVersion == "" {
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Server version: unknown (empty response)\n")
		return
	}

	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Server version: %s\n", backendVersion)

	min := version.MinServer()
	if sv, ok := version.Parse(backendVersion); ok && sv.LessThan(min) {
		log.Warnf("Server version %s is below minimum required %d.%d, please upgrade",
			backendVersion, min.Major, min.Minor)
	}
}

// Execute creates and runs the root command.
func Execute() error {
	opts := struct {
		Debug bool
	}{}

	rootCmd := &cobra.Command{
		Use:   "onyx-cli",
		Short: "Terminal UI for chatting with Onyx",
		Long:  "Onyx CLI — a terminal interface for chatting with your Onyx agent.",
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
	}

	rootCmd.PersistentFlags().BoolVar(&opts.Debug, "debug", false, "run in debug mode")

	// Custom --version flag instead of Cobra's built-in (which only shows one version string)
	var showVersion bool
	rootCmd.Flags().BoolVarP(&showVersion, "version", "v", false, "Print client and server version information")

	// Register subcommands
	chatCmd := newChatCmd()
	rootCmd.AddCommand(chatCmd)
	rootCmd.AddCommand(newAskCmd())
	rootCmd.AddCommand(newAgentsCmd())
	rootCmd.AddCommand(newConfigureCmd())
	rootCmd.AddCommand(newValidateConfigCmd())

	// Default command is chat, but intercept --version first
	rootCmd.RunE = func(cmd *cobra.Command, args []string) error {
		if showVersion {
			printVersion(cmd)
			return nil
		}
		return chatCmd.RunE(cmd, args)
	}

	return rootCmd.Execute()
}
