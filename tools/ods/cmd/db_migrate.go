package cmd

import (
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/alembic"
)

// MigrateOptions holds common options for migration commands.
type MigrateOptions struct {
	Schema string
}

// getAlembicSchema converts the schema flag value to alembic.Schema.
// Returns the schema and true if valid, or SchemaDefault and false if invalid.
func getAlembicSchema(schema string) (alembic.Schema, bool) {
	switch schema {
	case "default", "":
		return alembic.SchemaDefault, true
	case "private":
		return alembic.SchemaPrivate, true
	default:
		return alembic.SchemaDefault, false
	}
}

// NewDBUpgradeCommand creates the db upgrade command.
func NewDBUpgradeCommand() *cobra.Command {
	opts := &MigrateOptions{}

	cmd := &cobra.Command{
		Use:   "upgrade [revision]",
		Short: "Run Alembic migrations",
		Long: `Run Alembic migrations to upgrade the database schema.

If no revision is specified, upgrades to 'head' (latest revision).

The command automatically detects the PostgreSQL container IP if POSTGRES_HOST
is not set, so it works even when the port isn't exposed to localhost.

Environment variables (auto-detected if not set):
  POSTGRES_HOST      Database host (auto-detects container IP)
  POSTGRES_PORT      Database port (default: 5432)
  POSTGRES_USER      Database user (default: postgres)
  POSTGRES_PASSWORD  Database password (default: password)
  POSTGRES_DB        Database name (default: postgres)

Examples:
  ods db upgrade                    # Upgrade to latest
  ods db upgrade head               # Same as above
  ods db upgrade +1                 # Upgrade one revision
  ods db upgrade abc123             # Upgrade to specific revision
  ods db upgrade --schema private   # Upgrade private schema (multi-tenant)`,
		Args: cobra.MaximumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			revision := "head"
			if len(args) > 0 {
				revision = args[0]
			}
			runDBUpgrade(revision, opts)
		},
	}

	cmd.Flags().StringVar(&opts.Schema, "schema", "default", "Schema to migrate: 'default' or 'private' (multi-tenant)")

	return cmd
}

func runDBUpgrade(revision string, opts *MigrateOptions) {
	schema, valid := getAlembicSchema(opts.Schema)
	if !valid {
		log.Fatalf("Invalid schema: %s (must be 'default' or 'private')", opts.Schema)
	}

	log.Infof("Upgrading database to revision: %s", revision)
	if schema == alembic.SchemaPrivate {
		log.Info("Using schema: private (schema_private)")
	}

	if err := alembic.Upgrade(revision, schema); err != nil {
		log.Fatalf("Failed to upgrade database: %v", err)
	}

	log.Info("Upgrade completed successfully")
}

// NewDBDowngradeCommand creates the db downgrade command.
func NewDBDowngradeCommand() *cobra.Command {
	opts := &MigrateOptions{}

	cmd := &cobra.Command{
		Use:   "downgrade <revision>",
		Short: "Rollback Alembic migrations",
		Long: `Rollback Alembic migrations to a previous revision.

Examples:
  ods db downgrade -1               # Downgrade one revision
  ods db downgrade -2               # Downgrade two revisions
  ods db downgrade base             # Downgrade to initial state
  ods db downgrade abc123           # Downgrade to specific revision
  ods db downgrade --schema private # Downgrade private schema`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runDBDowngrade(args[0], opts)
		},
	}

	cmd.Flags().StringVar(&opts.Schema, "schema", "default", "Schema to migrate: 'default' or 'private' (multi-tenant)")

	return cmd
}

func runDBDowngrade(revision string, opts *MigrateOptions) {
	schema, valid := getAlembicSchema(opts.Schema)
	if !valid {
		log.Fatalf("Invalid schema: %s (must be 'default' or 'private')", opts.Schema)
	}

	log.Infof("Downgrading database to revision: %s", revision)
	if schema == alembic.SchemaPrivate {
		log.Info("Using schema: private (schema_private)")
	}

	if err := alembic.Downgrade(revision, schema); err != nil {
		log.Fatalf("Failed to downgrade database: %v", err)
	}

	log.Info("Downgrade completed successfully")
}

// NewDBCurrentCommand creates the db current command.
func NewDBCurrentCommand() *cobra.Command {
	opts := &MigrateOptions{}

	cmd := &cobra.Command{
		Use:   "current",
		Short: "Show current Alembic revision",
		Long: `Show the current Alembic revision for the database.

Examples:
  ods db current
  ods db current --schema private`,
		Run: func(cmd *cobra.Command, args []string) {
			runDBCurrent(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Schema, "schema", "default", "Schema to check: 'default' or 'private' (multi-tenant)")

	return cmd
}

func runDBCurrent(opts *MigrateOptions) {
	schema, valid := getAlembicSchema(opts.Schema)
	if !valid {
		log.Fatalf("Invalid schema: %s (must be 'default' or 'private')", opts.Schema)
	}

	if schema == alembic.SchemaPrivate {
		log.Info("Checking current revision for schema: private (schema_private)")
	}

	if err := alembic.Current(schema); err != nil {
		log.Fatalf("Failed to get current revision: %v", err)
	}
}

// HistoryOptions holds options for the history command.
type HistoryOptions struct {
	MigrateOptions
	Verbose bool
}

// NewDBHistoryCommand creates the db history command.
func NewDBHistoryCommand() *cobra.Command {
	opts := &HistoryOptions{}

	cmd := &cobra.Command{
		Use:   "history",
		Short: "Show Alembic migration history",
		Long: `Show the Alembic migration history.

Examples:
  ods db history
  ods db history --verbose
  ods db history --schema private`,
		Run: func(cmd *cobra.Command, args []string) {
			runDBHistory(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Schema, "schema", "default", "Schema to check: 'default' or 'private' (multi-tenant)")
	cmd.Flags().BoolVarP(&opts.Verbose, "verbose", "v", false, "Show verbose output")

	return cmd
}

func runDBHistory(opts *HistoryOptions) {
	schema, valid := getAlembicSchema(opts.Schema)
	if !valid {
		log.Fatalf("Invalid schema: %s (must be 'default' or 'private')", opts.Schema)
	}

	if schema == alembic.SchemaPrivate {
		log.Info("Showing history for schema: private (schema_private)")
	}

	if err := alembic.History(schema, opts.Verbose); err != nil {
		log.Fatalf("Failed to get migration history: %v", err)
	}
}
