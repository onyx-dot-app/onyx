package cmd

import (
	"github.com/spf13/cobra"
)

// NewDBCommand creates the parent db command.
func NewDBCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "db",
		Short: "Database administration commands",
		Long: `Database administration commands for managing PostgreSQL and Alembic migrations.

Commands include dropping/recreating databases, creating and restoring snapshots,
and managing Alembic migrations (upgrade, downgrade, current, history).`,
	}

	// Add subcommands
	cmd.AddCommand(NewDBDropCommand())
	cmd.AddCommand(NewDBDumpCommand())
	cmd.AddCommand(NewDBRestoreCommand())
	cmd.AddCommand(NewDBUpgradeCommand())
	cmd.AddCommand(NewDBDowngradeCommand())
	cmd.AddCommand(NewDBCurrentCommand())
	cmd.AddCommand(NewDBHistoryCommand())

	return cmd
}
