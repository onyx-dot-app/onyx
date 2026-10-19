package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/alembic"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/postgres"
)

// MigrateOptions holds common options for migration commands.
type MigrateOptions struct {
	Schema string
}

func resolveDBMigrationTarget() (devstack.Target, error) {
	if os.Getenv("POSTGRES_HOST") != "" && flagProjectName() != "" {
		return devstack.Target{}, fmt.Errorf("--project conflicts with explicit POSTGRES_HOST; select either a stack or a network database")
	}
	if host := os.Getenv("POSTGRES_HOST"); host != "" {
		root, err := paths.GitRoot()
		if err != nil {
			return devstack.Target{}, err
		}
		if !postgres.IsLoopbackHost(host) {
			return devstack.Target{Root: root, Mode: runtimeMode()}, nil
		}
		port, err := loopbackDBPort(root)
		if err != nil {
			return devstack.Target{}, err
		}
		if target, found, err := devstack.ResolveManagedDatabaseTarget(root, port, runtimeRegistry()); err != nil || found {
			return target, err
		}
		stack, err := devstack.Open(root, "", runtimeMode())
		if err != nil {
			return devstack.Target{}, err
		}
		return devstack.Target{Root: stack.Root, Project: stack.Project, StateDir: stack.StateDir, Mode: stack.Mode, Ports: map[string]int{}}, nil
	}
	return resolveRuntimeTarget()
}

func lockDBMigrationTarget(target devstack.Target, mutating bool) (func(), error) {
	host := os.Getenv("POSTGRES_HOST")
	if host == "" {
		return lockStoppedMigrationTarget(target, mutating)
	}
	if !postgres.IsLoopbackHost(host) {
		return func() {}, nil
	}
	port, err := loopbackDBPort(target.Root)
	if err != nil {
		return nil, err
	}
	current, found, err := devstack.ResolveManagedDatabaseTarget(target.Root, port, runtimeRegistry())
	if err != nil {
		return nil, err
	}
	if !found && !target.Managed {
		return func() {}, nil
	}
	if found && !target.Managed {
		return nil, fmt.Errorf("project %s was claimed by %s after target selection; retry the command", current.Project, current.OwnerRoot)
	}
	if !found || current.Project != target.Project || current.StateDir != target.StateDir {
		return nil, fmt.Errorf("database port %d changed ownership after target selection; retry the command", port)
	}
	release, err := lockStoppedMigrationTarget(target, mutating)
	if err != nil {
		return nil, err
	}
	current, found, err = devstack.ResolveManagedDatabaseTarget(target.Root, port, runtimeRegistry())
	if err != nil || !found || current.Project != target.Project || current.StateDir != target.StateDir {
		release()
		if err != nil {
			return nil, err
		}
		return nil, fmt.Errorf("database port %d changed ownership while acquiring its lock; retry the command", port)
	}
	return release, nil
}

func lockStoppedMigrationTarget(target devstack.Target, mutating bool) (func(), error) {
	release, err := lockRuntimeTarget(target, mutating)
	if err != nil {
		return nil, err
	}
	if mutating && target.Managed {
		st, err := stackForTarget(target).ReadState()
		if err != nil {
			release()
			return nil, err
		}
		if st != nil {
			for _, service := range st.Services {
				if service.PID > 0 || service.PGID > 0 {
					release()
					prefix := "ods"
					if target.Mode == devstack.Isolated {
						prefix += " --isolated"
					}
					return nil, fmt.Errorf("project %s has managed services; run '%s stack stop' before manual migrations, or use '%s stack up' for a safe upgrade", target.Project, prefix, prefix)
				}
			}
		}
	}
	return release, nil
}

func loopbackDBPort(root string) (int, error) {
	fileEnv, err := devstack.LoadEnvFile(filepath.Join(root, ".vscode", ".env"))
	if err != nil {
		return 0, err
	}
	config := postgres.NewConfigFromEnvironment(append(fileEnv, os.Environ()...))
	port, err := strconv.Atoi(config.Port)
	if err != nil || port <= 0 || port > 65535 {
		return 0, fmt.Errorf("invalid POSTGRES_PORT")
	}
	return port, nil
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

The command uses the selected stack's actual PostgreSQL port. If that port is
not exposed, it uses only that project's api_server container. Explicit
POSTGRES_HOST selects a network database and never falls back to Docker.

Environment variables (auto-detected if not set):
  POSTGRES_HOST      Explicit network database host
  POSTGRES_PORT      Explicit network database port (default: 5432)
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
			if err := runDBUpgrade(revision, opts); err != nil {
				log.Fatal(err)
			}
		},
	}

	cmd.Flags().StringVar(&opts.Schema, "schema", "default", "Schema to migrate: 'default' or 'private' (multi-tenant)")

	return cmd
}

func runDBUpgrade(revision string, opts *MigrateOptions) error {
	schema, valid := getAlembicSchema(opts.Schema)
	if !valid {
		return fatalErrorf("Invalid schema: %s (must be 'default' or 'private')", opts.Schema)
	}

	log.Infof("Upgrading database to revision: %s", revision)
	if schema == alembic.SchemaPrivate {
		log.Info("Using schema: private (schema_private)")
	}

	target, err := resolveDBMigrationTarget()
	if err != nil {
		return err
	}
	release, err := lockDBMigrationTarget(target, true)
	if err != nil {
		return err
	}
	defer release()
	if err := alembic.Upgrade(target, revision, schema); err != nil {
		return fatalErrorf("Failed to upgrade database: %w", err)
	}

	log.Info("Upgrade completed successfully")
	return nil
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
			if err := runDBDowngrade(args[0], opts); err != nil {
				log.Fatal(err)
			}
		},
	}

	cmd.Flags().StringVar(&opts.Schema, "schema", "default", "Schema to migrate: 'default' or 'private' (multi-tenant)")

	return cmd
}

func runDBDowngrade(revision string, opts *MigrateOptions) error {
	schema, valid := getAlembicSchema(opts.Schema)
	if !valid {
		return fatalErrorf("Invalid schema: %s (must be 'default' or 'private')", opts.Schema)
	}

	log.Infof("Downgrading database to revision: %s", revision)
	if schema == alembic.SchemaPrivate {
		log.Info("Using schema: private (schema_private)")
	}

	target, err := resolveDBMigrationTarget()
	if err != nil {
		return err
	}
	release, err := lockDBMigrationTarget(target, true)
	if err != nil {
		return err
	}
	defer release()
	if err := alembic.Downgrade(target, revision, schema); err != nil {
		return fatalErrorf("Failed to downgrade database: %w", err)
	}

	log.Info("Downgrade completed successfully")
	return nil
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
			if err := runDBCurrent(opts); err != nil {
				log.Fatal(err)
			}
		},
	}

	cmd.Flags().StringVar(&opts.Schema, "schema", "default", "Schema to check: 'default' or 'private' (multi-tenant)")

	return cmd
}

func runDBCurrent(opts *MigrateOptions) error {
	schema, valid := getAlembicSchema(opts.Schema)
	if !valid {
		return fatalErrorf("Invalid schema: %s (must be 'default' or 'private')", opts.Schema)
	}

	if schema == alembic.SchemaPrivate {
		log.Info("Checking current revision for schema: private (schema_private)")
	}

	target, err := resolveDBMigrationTarget()
	if err != nil {
		return err
	}
	release, err := lockDBMigrationTarget(target, false)
	if err != nil {
		return err
	}
	defer release()
	if err := alembic.Current(target, schema); err != nil {
		return fatalErrorf("Failed to get current revision: %w", err)
	}
	return nil
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
			if err := runDBHistory(opts); err != nil {
				log.Fatal(err)
			}
		},
	}

	cmd.Flags().StringVar(&opts.Schema, "schema", "default", "Schema to check: 'default' or 'private' (multi-tenant)")
	cmd.Flags().BoolVarP(&opts.Verbose, "verbose", "v", false, "Show verbose output")

	return cmd
}

func runDBHistory(opts *HistoryOptions) error {
	schema, valid := getAlembicSchema(opts.Schema)
	if !valid {
		return fatalErrorf("Invalid schema: %s (must be 'default' or 'private')", opts.Schema)
	}

	if schema == alembic.SchemaPrivate {
		log.Info("Showing history for schema: private (schema_private)")
	}

	target, err := resolveDBMigrationTarget()
	if err != nil {
		return err
	}
	release, err := lockDBMigrationTarget(target, false)
	if err != nil {
		return err
	}
	defer release()
	if err := alembic.History(target, schema, opts.Verbose); err != nil {
		return fatalErrorf("Failed to get migration history: %w", err)
	}
	return nil
}
