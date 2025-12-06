package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/postgres"
)

// DBDumpOptions holds options for the db dump command.
type DBDumpOptions struct {
	Format string
	Schema string
	Output string
}

// NewDBDumpCommand creates the db dump command.
func NewDBDumpCommand() *cobra.Command {
	opts := &DBDumpOptions{}

	cmd := &cobra.Command{
		Use:   "dump [output-file]",
		Short: "Create a database snapshot",
		Long: `Create a database snapshot using pg_dump.

The snapshot is saved to the specified output file, or to the default
snapshots directory (~/.local/share/onyx-dev/snapshots/) if no file is specified.

Examples:
  ods db dump                           # Creates onyx_<timestamp>.dump in snapshots dir
  ods db dump mybackup.dump             # Creates mybackup.dump in snapshots dir
  ods db dump /path/to/backup.sql       # Creates backup.sql at specified path
  ods db dump --format sql              # Creates SQL format instead of custom format`,
		Args: cobra.MaximumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			if len(args) > 0 {
				opts.Output = args[0]
			}
			runDBDump(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Format, "format", "custom", "Output format: 'custom' (pg_dump -Fc) or 'sql' (plain SQL)")
	cmd.Flags().StringVar(&opts.Schema, "schema", "", "Dump only a specific schema")

	return cmd
}

func runDBDump(opts *DBDumpOptions) {
	// Find PostgreSQL container
	container, err := docker.FindPostgresContainer()
	if err != nil {
		log.Fatalf("Failed to find PostgreSQL container: %v", err)
	}
	log.Infof("Found PostgreSQL container: %s", container)

	config := postgres.NewConfigFromEnv()

	// Determine output file path
	outputPath := determineOutputPath(opts.Output, opts.Format)

	// Ensure output directory exists
	outputDir := filepath.Dir(outputPath)
	if err := os.MkdirAll(outputDir, 0755); err != nil {
		log.Fatalf("Failed to create output directory: %v", err)
	}

	log.Infof("Dumping database '%s' to: %s", config.Database, outputPath)

	// Build pg_dump arguments
	args := config.PgDumpArgs(opts.Format)
	if opts.Schema != "" {
		args = append(args, "-n", opts.Schema)
	}

	// Create a temporary file in the container
	containerTmpFile := "/tmp/onyx_dump_tmp"
	args = append(args, "-f", containerTmpFile)

	// Run pg_dump in container
	env := config.Env()
	pgDumpArgs := append([]string{"pg_dump"}, args...)
	if err := docker.ExecWithEnv(container, env, pgDumpArgs...); err != nil {
		log.Fatalf("Failed to run pg_dump: %v", err)
	}

	// Copy the dump file from container to host
	if err := docker.CopyFromContainer(container, containerTmpFile, outputPath); err != nil {
		log.Fatalf("Failed to copy dump file: %v", err)
	}

	// Clean up temporary file in container
	_ = docker.Exec(container, "rm", "-f", containerTmpFile)

	// Get file size for info
	if info, err := os.Stat(outputPath); err == nil {
		log.Infof("Dump completed successfully (%s)", humanizeBytes(info.Size()))
	} else {
		log.Info("Dump completed successfully")
	}
}

// determineOutputPath determines the output file path based on options.
func determineOutputPath(output string, format string) string {
	ext := ".dump"
	if format == "sql" {
		ext = ".sql"
	}

	if output == "" {
		// Generate default filename with timestamp
		timestamp := time.Now().Format("20060102_150405")
		filename := fmt.Sprintf("onyx_%s%s", timestamp, ext)
		return filepath.Join(paths.SnapshotsDir(), filename)
	}

	// Check if output is just a filename (no directory)
	if filepath.Dir(output) == "." {
		return filepath.Join(paths.SnapshotsDir(), output)
	}

	return output
}

// humanizeBytes converts bytes to a human-readable string.
func humanizeBytes(bytes int64) string {
	const unit = 1024
	if bytes < unit {
		return fmt.Sprintf("%d B", bytes)
	}
	div, exp := int64(unit), 0
	for n := bytes / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %cB", float64(bytes)/float64(div), "KMGTPE"[exp])
}
