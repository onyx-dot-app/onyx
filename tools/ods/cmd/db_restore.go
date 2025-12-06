package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/postgres"
)

// DBRestoreOptions holds options for the db restore command.
type DBRestoreOptions struct {
	Yes   bool
	Clean bool
}

// NewDBRestoreCommand creates the db restore command.
func NewDBRestoreCommand() *cobra.Command {
	opts := &DBRestoreOptions{}

	cmd := &cobra.Command{
		Use:   "restore <input-file>",
		Short: "Restore a database snapshot",
		Long: `Restore a database snapshot using pg_restore or psql.

The format is automatically detected based on file extension:
  - .dump files: restored with pg_restore (custom format)
  - .sql files: restored with psql (plain SQL)

If just a filename is provided (without path), the file is looked up
in the default snapshots directory (~/.local/share/onyx-dev/snapshots/).

Examples:
  ods db restore mybackup.dump           # Restores from snapshots dir
  ods db restore /path/to/backup.sql     # Restores from absolute path
  ods db restore backup.dump --clean     # Drop objects before restoring`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runDBRestore(args[0], opts)
		},
		ValidArgsFunction: completeSnapshotFiles,
	}

	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip confirmation prompt")
	cmd.Flags().BoolVar(&opts.Clean, "clean", false, "Drop database objects before restoring")

	return cmd
}

// completeSnapshotFiles provides tab completion for snapshot files.
func completeSnapshotFiles(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
	if len(args) != 0 {
		return nil, cobra.ShellCompDirectiveNoFileComp
	}

	var completions []string

	// List files from snapshots directory
	snapshotsDir := paths.SnapshotsDir()
	entries, err := os.ReadDir(snapshotsDir)
	if err == nil {
		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			name := entry.Name()
			// Only suggest .dump and .sql files
			if strings.HasSuffix(name, ".dump") || strings.HasSuffix(name, ".sql") {
				if strings.HasPrefix(name, toComplete) {
					completions = append(completions, name)
				}
			}
		}
	}

	// Also allow file path completion
	return completions, cobra.ShellCompDirectiveDefault
}

func runDBRestore(input string, opts *DBRestoreOptions) {
	// Resolve input path
	inputPath := resolveInputPath(input)

	// Check if file exists
	if _, err := os.Stat(inputPath); os.IsNotExist(err) {
		log.Fatalf("Input file not found: %s", inputPath)
	}

	// Find PostgreSQL container
	container, err := docker.FindPostgresContainer()
	if err != nil {
		log.Fatalf("Failed to find PostgreSQL container: %v", err)
	}
	log.Infof("Found PostgreSQL container: %s", container)

	config := postgres.NewConfigFromEnv()

	// Confirmation prompt
	if !opts.Yes {
		prompt := fmt.Sprintf("This will restore '%s' to database '%s'. Existing data may be overwritten. Continue? (yes/no): ",
			filepath.Base(inputPath), config.Database)
		if !promptConfirm(prompt) {
			log.Info("Aborted.")
			return
		}
	}

	// Detect format from extension
	isCustomFormat := strings.HasSuffix(strings.ToLower(inputPath), ".dump")

	log.Infof("Restoring database '%s' from: %s", config.Database, inputPath)

	// Copy file to container
	containerTmpFile := "/tmp/onyx_restore_tmp"
	if err := docker.CopyToContainer(container, inputPath, containerTmpFile); err != nil {
		log.Fatalf("Failed to copy file to container: %v", err)
	}

	env := config.Env()

	if isCustomFormat {
		// Use pg_restore for custom format
		args := config.PgRestoreArgs()
		if opts.Clean {
			args = append(args, "--clean", "--if-exists")
		}
		args = append(args, containerTmpFile)

		restoreArgs := append([]string{"pg_restore"}, args...)
		if err := docker.ExecWithEnv(container, env, restoreArgs...); err != nil {
			// pg_restore may return non-zero for warnings, check if it's fatal
			log.Warnf("pg_restore completed with warnings or errors: %v", err)
		}
	} else {
		// Use psql for SQL format
		args := config.PsqlArgs()
		args = append(args, "-f", containerTmpFile)

		psqlArgs := append([]string{"psql"}, args...)
		if err := docker.ExecWithEnv(container, env, psqlArgs...); err != nil {
			log.Fatalf("Failed to restore from SQL file: %v", err)
		}
	}

	// Clean up temporary file in container
	_ = docker.Exec(container, "rm", "-f", containerTmpFile)

	log.Info("Restore completed successfully")
}

// resolveInputPath resolves the input file path.
func resolveInputPath(input string) string {
	// If it's an absolute path or contains directory separator, use as-is
	if filepath.IsAbs(input) || strings.Contains(input, string(filepath.Separator)) {
		return input
	}

	// Check if file exists in snapshots directory
	snapshotPath := filepath.Join(paths.SnapshotsDir(), input)
	if _, err := os.Stat(snapshotPath); err == nil {
		return snapshotPath
	}

	// Check if file exists in current directory
	if _, err := os.Stat(input); err == nil {
		absPath, _ := filepath.Abs(input)
		return absPath
	}

	// Default to snapshots directory
	return snapshotPath
}
