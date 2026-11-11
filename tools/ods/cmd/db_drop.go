package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/postgres"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

// validIdentifier matches valid PostgreSQL identifiers (letters, digits,
// underscores, starting with letter/underscore).
var validIdentifier = regexp.MustCompile(`^[a-zA-Z_][a-zA-Z0-9_]*$`)

// DBDropOptions holds options for the db drop command.
type DBDropOptions struct {
	Yes    bool
	Schema string
}

// NewDBDropCommand creates the db drop command.
func NewDBDropCommand() *cobra.Command {
	opts := &DBDropOptions{}

	cmd := &cobra.Command{
		Use:   "drop",
		Short: "Drop and recreate the database",
		Long: `Drop and recreate the PostgreSQL database.

This command will:
  1. Find the running PostgreSQL container
  2. Drop all connections to the database
  3. Drop the database (or schema if --schema is specified)
  4. Recreate the database (or schema)

WARNING: This is a destructive operation. All data will be lost.`,
		Run: func(cmd *cobra.Command, args []string) {
			if err := runDBDrop(opts); err != nil {
				log.Fatal(err)
			}
		},
	}

	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip confirmation prompt")
	cmd.Flags().StringVar(&opts.Schema, "schema", "", "Drop a specific schema instead of the entire database")

	return cmd
}

func resolveDBContainerTarget() (devstack.Target, string, *postgres.Config, error) {
	if os.Getenv("POSTGRES_HOST") != "" {
		if flagProjectName() != "" {
			return devstack.Target{}, "", nil, fmt.Errorf("--project conflicts with explicit POSTGRES_HOST; select either a stack or a network database")
		}
		return devstack.Target{}, "", nil, fmt.Errorf("explicit POSTGRES_HOST requires a host PostgreSQL client; container-only drop, dump and restore are not supported for network targets")
	}
	target, err := resolveRuntimeTarget()
	if err != nil {
		return target, "", nil, err
	}
	fileEnv, err := devstack.LoadEnvFile(filepath.Join(target.Root, ".vscode", ".env"))
	if err != nil && !os.IsNotExist(err) {
		return target, "", nil, err
	}
	config := postgres.NewConfigFromEnvironment(append(fileEnv, os.Environ()...))
	if !target.Managed && !postgres.IsLoopbackHost(config.Host) {
		return target, "", nil, fmt.Errorf("POSTGRES_HOST in the checkout environment selects a network database; container-only drop, dump and restore are not supported")
	}
	container, err := docker.FindPostgresContainer(target.Project)
	if err != nil {
		return target, "", nil, fatalErrorf("Failed to find PostgreSQL container: %w", err)
	}
	return target, container, config, nil
}

func runDBDrop(opts *DBDropOptions) error {
	target, container, config, err := resolveDBContainerTarget()
	if err != nil {
		return err
	}
	log.Infof("Selected project %s, PostgreSQL container %s", target.Project, container)
	release, err := lockRuntimeTarget(target, true)
	if err != nil {
		return err
	}
	defer release()

	// Confirmation prompt
	if !opts.Yes {
		var msg string
		if opts.Schema != "" {
			msg = fmt.Sprintf("This will DROP the schema '%s' in database '%s' on project '%s', container '%s'. All data will be lost. Continue? (yes/no): ",
				opts.Schema, config.Database, target.Project, container)
		} else {
			msg = fmt.Sprintf("This will DROP and RECREATE the database '%s' on project '%s', container '%s'. All data will be lost. Continue? (yes/no): ",
				config.Database, target.Project, container)
		}

		if !prompt.Confirm(msg) {
			log.Info("Aborted.")
			return nil
		}
	}

	env := config.Env()

	if opts.Schema != "" {
		// Validate schema name to prevent SQL injection.
		if !validIdentifier.MatchString(opts.Schema) {
			return fatalErrorf("Invalid schema name: %s", opts.Schema)
		}

		// Drop and recreate schema.
		log.Infof("Dropping schema: %s", opts.Schema)
		dropSchemaSQL := fmt.Sprintf("DROP SCHEMA IF EXISTS %s CASCADE;", opts.Schema)
		createSchemaSQL := fmt.Sprintf("CREATE SCHEMA %s;", opts.Schema)

		args := append(config.PsqlArgs(), "-c", dropSchemaSQL)
		if err := docker.ExecWithEnv(container, env, append([]string{"psql"}, args...)...); err != nil {
			return fatalErrorf("Failed to drop schema: %w", err)
		}

		args = append(config.PsqlArgs(), "-c", createSchemaSQL)
		if err := docker.ExecWithEnv(container, env, append([]string{"psql"}, args...)...); err != nil {
			return fatalErrorf("Failed to create schema: %w", err)
		}

		log.Infof("Schema '%s' dropped and recreated successfully", opts.Schema)
	} else {
		// Drop and recreate entire database.
		log.Infof("Dropping database: %s", config.Database)

		// Use template1 as maintenance database (can't drop a DB while
		// connected to it).
		maintenanceDB := "template1"

		// Terminate existing connections.
		// Validate database name to prevent SQL injection.
		if !validIdentifier.MatchString(config.Database) {
			return fatalErrorf("Invalid database name: %s", config.Database)
		}

		// Terminate existing connections.
		terminateSQL := fmt.Sprintf(
			"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '%s' AND pid <> pg_backend_pid();",
			config.Database)

		args := []string{"psql", "-U", config.User, "-d", maintenanceDB, "-c", terminateSQL}
		if err := docker.ExecWithEnv(container, env, args...); err != nil {
			log.Warnf("Failed to terminate connections (this may be okay): %v", err)
		}

		// Drop database.
		dropSQL := fmt.Sprintf("DROP DATABASE IF EXISTS %s;", config.Database)
		args = []string{"psql", "-U", config.User, "-d", maintenanceDB, "-c", dropSQL}
		if err := docker.ExecWithEnv(container, env, args...); err != nil {
			return fatalErrorf("Failed to drop database: %w", err)
		}

		// Create database.
		createSQL := fmt.Sprintf("CREATE DATABASE %s;", config.Database)
		args = []string{"psql", "-U", config.User, "-d", maintenanceDB, "-c", createSQL}
		if err := docker.ExecWithEnv(container, env, args...); err != nil {
			return fatalErrorf("Failed to create database: %w", err)
		}

		log.Infof("Database '%s' dropped and recreated successfully", config.Database)
		log.Info("Run 'ods db upgrade' to apply migrations")
	}
	return nil
}
