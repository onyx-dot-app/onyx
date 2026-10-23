package cmd

import (
	"fmt"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

var (
	Version string
	Commit  string

	// rootProject is the --project flag, read by commands that derive their
	// own project name when it is empty.
	rootProject  string
	rootIsolated bool
)

func flagProjectName() string { return rootProject }

// RootOptions holds options for the root command.
type RootOptions struct {
	Debug    bool
	Project  string
	Isolated bool
}

// NewRootCommand creates the root command.
func NewRootCommand() *cobra.Command {
	opts := &RootOptions{}

	cmd := &cobra.Command{
		Use:   "ods ",
		Short: "Developer utilities for working on onyx.app",
		Run:   rootCmd,
		PersistentPreRun: func(cmd *cobra.Command, args []string) {
			if opts.Debug {
				log.SetLevel(log.DebugLevel)
			} else {
				log.SetLevel(log.InfoLevel)
			}
			log.SetFormatter(&log.TextFormatter{
				DisableTimestamp: true,
			})
			rootProject = opts.Project
			rootIsolated = opts.Isolated
		},
		Version: fmt.Sprintf("%s\ncommit %s", Version, Commit),
	}

	cmd.PersistentFlags().BoolVar(&opts.Debug, "debug", false, "run in debug mode")
	cmd.PersistentFlags().StringVar(&opts.Project, "project", "", "Infrastructure project (default: saved shared or isolated target)")
	cmd.PersistentFlags().BoolVar(&opts.Isolated, "isolated", false, "Use this worktree's separate infrastructure and data")

	// Add subcommands
	cmd.AddCommand(NewAuditCommand())
	cmd.AddCommand(NewBackendCommand())
	cmd.AddCommand(NewCheckGetattrCommand())
	cmd.AddCommand(NewCheckLazyImportsCommand())
	cmd.AddCommand(NewCherryPickCommand())
	cmd.AddCommand(NewDBCommand())
	cmd.AddCommand(NewDeployCommand())
	cmd.AddCommand(NewOpenAPICommand())
	cmd.AddCommand(NewComposeCommand())
	cmd.AddCommand(NewGenerateComposeCommand())
	cmd.AddCommand(NewEnvCommand())
	cmd.AddCommand(NewObjectStoreCommand())
	cmd.AddCommand(NewFmtCommand())
	cmd.AddCommand(NewLintCommand())
	cmd.AddCommand(NewLogsCommand())
	cmd.AddCommand(NewPullCommand())
	cmd.AddCommand(NewRunCICommand())
	cmd.AddCommand(NewScreenshotDiffCommand())
	cmd.AddCommand(NewStackCommand())
	cmd.AddCommand(NewTestCommand())
	cmd.AddCommand(NewCoverageCommand())
	cmd.AddCommand(NewTypeCoverageCommand())
	cmd.AddCommand(NewDesktopCommand())
	cmd.AddCommand(NewDevCommand())
	cmd.AddCommand(NewWebCommand())
	cmd.AddCommand(NewWhoisCommand())
	cmd.AddCommand(NewTraceCommand())
	cmd.AddCommand(NewUpdateBaseDigestsCommand())
	cmd.AddCommand(NewInstallSkillCommand())
	cmd.AddCommand(NewReleaseCommand())
	groups := map[string][]string{
		"local":       {"stack", "backend", "web", "desktop", "dev"},
		"infra":       {"compose", "env", "logs", "pull", "db", "object-store"},
		"quality":     {"test", "coverage", "type-coverage", "fmt", "lint", "check-getattr", "check-lazy-imports", "audit"},
		"ci":          {"run-ci", "trace", "screenshot-diff"},
		"maintenance": {"generate-compose", "openapi", "update-base-digests", "install-skill"},
		"operations":  {"deploy", "release", "cherry-pick", "whois"},
	}
	for _, group := range []struct{ id, title string }{{"local", "Local development:"}, {"infra", "Infrastructure and data:"}, {"quality", "Checks and tests:"}, {"ci", "CI diagnostics:"}, {"maintenance", "Generation and setup:"}, {"operations", "Release and operations:"}} {
		cmd.AddGroup(&cobra.Group{ID: group.id, Title: group.title})
	}
	for _, child := range cmd.Commands() {
		for group, names := range groups {
			for _, name := range names {
				if child.Name() == name {
					child.GroupID = group
				}
			}
		}
	}
	cmd.SetHelpCommandGroupID("maintenance")
	cmd.SetCompletionCommandGroupID("maintenance")

	return cmd
}

func rootCmd(cmd *cobra.Command, args []string) {
	_ = cmd.Help()
}
