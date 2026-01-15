package cmd

import (
	"fmt"
	"regexp"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/postgres"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

// validIdentifier matches valid PostgreSQL identifiers (letters, digits, underscores, starting with letter/underscore)
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
			runDBDrop(opts)
		},
	}

	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip confirmation prompt")
	cmd.Flags().StringVar(&opts.Schema, "schema", "", "Drop a specific schema instead of the entire database")

	return cmd
}

func runDBDrop(opts *DBDropOptions) {
	// Find PostgreSQL container
	container, err := docker.FindPostgresContainer()
	if err != nil {
		log.Fatalf("Failed to find PostgreSQL container: %v", err)
	}
	log.Infof("Found PostgreSQL container: %s", container)

	config := postgres.NewConfigFromEnv()

	// Confirmation prompt
	if !opts.Yes {
		var msg string
		if opts.Schema != "" {
			msg = fmt.Sprintf("This will DROP the schema '%s' in database '%s'. All data will be lost. Continue? (yes/no): ",
				opts.Schema, config.Database)
		} else {
			msg = fmt.Sprintf("This will DROP and RECREATE the database '%s'. All data will be lost. Continue? (yes/no): ",
				config.Database)
		}

		if !prompt.Confirm(msg) {
			log.Info("Aborted.")
			return
		}
	}

	env := config.Env()

	if opts.Schema != "" {
		// Validate schema name to prevent SQL injection
		if !validIdentifier.MatchString(opts.Schema) {
			log.Fatalf("Invalid schema name: %s", opts.Schema)
		}

		// Drop and recreate schema
		log.Infof("Dropping schema: %s", opts.Schema)
		dropSchemaSQL := fmt.Sprintf("DROP SCHEMA IF EXISTS %s CASCADE;", opts.Schema)
		createSchemaSQL := fmt.Sprintf("CREATE SCHEMA %s;", opts.Schema)

		args := append(config.PsqlArgs(), "-c", dropSchemaSQL)
		if err := docker.ExecWithEnv(container, env, append([]string{"psql"}, args...)...); err != nil {
			log.Fatalf("Failed to drop schema: %v", err)
		}

		args = append(config.PsqlArgs(), "-c", createSchemaSQL)
		if err := docker.ExecWithEnv(container, env, append([]string{"psql"}, args...)...); err != nil {
			log.Fatalf("Failed to create schema: %v", err)
		}

		log.Infof("Schema '%s' dropped and recreated successfully", opts.Schema)
	} else {
		// Drop and recreate entire database
		log.Infof("Dropping database: %s", config.Database)

		// Use template1 as maintenance database (can't drop a DB while connected to it)
		maintenanceDB := "template1"

		// Terminate existing connections
		// Validate database name to prevent SQL injection
		if !validIdentifier.MatchString(config.Database) {
			log.Fatalf("Invalid database name: %s", config.Database)
		}

		// Terminate existing connections
		terminateSQL := fmt.Sprintf(
			"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '%s' AND pid <> pg_backend_pid();",
			config.Database)

		args := []string{"psql", "-U", config.User, "-d", maintenanceDB, "-c", terminateSQL}
		if err := docker.ExecWithEnv(container, env, args...); err != nil {
			log.Warnf("Failed to terminate connections (this may be okay): %v", err)
		}

		// Drop database
		dropSQL := fmt.Sprintf("DROP DATABASE IF EXISTS %s;", config.Database)
		args = []string{"psql", "-U", config.User, "-d", maintenanceDB, "-c", dropSQL}
		if err := docker.ExecWithEnv(container, env, args...); err != nil {
			log.Fatalf("Failed to drop database: %v", err)
		}

		// Create database
		createSQL := fmt.Sprintf("CREATE DATABASE %s;", config.Database)
		args = []string{"psql", "-U", config.User, "-d", maintenanceDB, "-c", createSQL}
		if err := docker.ExecWithEnv(container, env, args...); err != nil {
			log.Fatalf("Failed to create database: %v", err)
		}

		log.Infof("Database '%s' dropped and recreated successfully", config.Database)
		log.Info("Run 'ods db upgrade' to apply migrations")
	}
}
