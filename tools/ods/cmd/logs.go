package cmd

import (
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/logs"
)

// NewLogsCommand creates the logs command
func NewLogsCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "logs",
		Short: "Sort and view logs chronologically",
		Long: `Read logs from stdin, sort them chronologically by timestamp, and display in a pager.

This command parses log lines with timestamps in the format MM/DD/YYYY HH:MM:SS AM/PM,
sorts them chronologically, and displays the result in a pager (less).

Examples:
  cat api-server*.log | ods logs
  cat service1.log service2.log | ods logs
  kubectl logs -l app=api-server | ods logs`,
		Run: func(cmd *cobra.Command, args []string) {
			runLogs()
		},
	}

	return cmd
}

func runLogs() {
	// Check if stdin has data
	stat, _ := os.Stdin.Stat()
	if (stat.Mode() & os.ModeCharDevice) != 0 {
		log.Fatal("No input provided. Pipe log files to this command:\n  cat *.log | ods logs")
	}

	if err := logs.ProcessAndDisplay(os.Stdin); err != nil {
		log.Fatalf("Error processing logs: %v", err)
	}
}
