package cmd

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// NewK8sCommand creates the parent "k8s" command for running Onyx against a
// local kind cluster.
func NewK8sCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "k8s",
		Short: "Run Onyx against a local kind cluster",
		Long: `Run Onyx against a local kind cluster (kind-onyx-dev).

This is the CLI equivalent of the "Run All Onyx Services (k8s)" compound
launch config in .vscode/launch.json. See docs/dev/run-all-k8s-cli.md
and docs/dev/local-kubernetes.md.

Commands:
  up     Start web + api_server + all celery workers against kind-onyx-dev
  down   Stop running services and tear down the telepresence intercept
  logs   Tail logs from one or all services`,
	}

	cmd.AddCommand(newK8sUpCommand())
	cmd.AddCommand(newK8sDownCommand())
	cmd.AddCommand(newK8sLogsCommand())

	return cmd
}

// k8sServices lists log filenames written by "ods k8s up", used for arg
// validation and shell completion of "ods k8s logs".
var k8sServices = []string{
	"api_server",
	"web_server",
	"celery_primary",
	"celery_light",
	"celery_heavy",
	"celery_docfetching",
	"celery_docprocessing",
	"celery_user_file_processing",
	"celery_scheduled_tasks",
	"celery_beat",
}

func newK8sLogsCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "logs [service]",
		Short: "Tail logs from one or all services",
		Long: `Tail logs written by "ods k8s up" under log/.

With no argument, tails every <service>.log in log/ (prefixed
with the filename on each switch). With a service name, tails just
that file.

Examples:
  ods k8s logs              # tail all 10 service logs
  ods k8s logs api_server
  ods k8s logs celery_docprocessing`,
		Args:      cobra.MaximumNArgs(1),
		ValidArgs: k8sServices,
		Run: func(cmd *cobra.Command, args []string) {
			runK8sLogs(args)
		},
	}

	return cmd
}

func runK8sLogs(args []string) {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	logDir := filepath.Join(root, "log")

	var tailArgs []string
	if len(args) == 0 {
		matches, err := filepath.Glob(filepath.Join(logDir, "*.log"))
		if err != nil || len(matches) == 0 {
			log.Fatalf("No log files found in %s (have you run \"ods k8s up\"?)", logDir)
		}
		tailArgs = append([]string{"-f"}, matches...)
	} else {
		service := args[0]
		if !contains(k8sServices, service) {
			log.Fatalf("Unknown service %q. Valid services:\n  %s", service, strings.Join(k8sServices, "\n  "))
		}
		logFile := filepath.Join(logDir, service+".log")
		if _, err := os.Stat(logFile); err != nil {
			log.Fatalf("Log file not found: %s (have you run \"ods k8s up\"?)", logFile)
		}
		tailArgs = []string{"-f", logFile}
	}

	tailCmd := exec.Command("tail", tailArgs...)
	tailCmd.Stdout = os.Stdout
	tailCmd.Stderr = os.Stderr
	tailCmd.Stdin = os.Stdin
	if err := tailCmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			if code := exitErr.ExitCode(); code != -1 {
				os.Exit(code)
			}
		}
		log.Fatalf("Failed to run tail: %v", err)
	}
}

func contains(slice []string, s string) bool {
	for _, v := range slice {
		if v == s {
			return true
		}
	}
	return false
}

func newK8sUpCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "up",
		Short: "Start all Onyx services against kind-onyx-dev",
		Long: `Start web, api_server, and all celery workers locally with telepresence
intercept routing in-cluster traffic to your laptop.

Prerequisites (see docs/dev/local-kubernetes.md):
  - kind-onyx-dev kubectl context exists and the cluster is up
  - .venv at the repo root (uv sync)
  - .vscode/.env.k8s exists (copy from .env.k8s.template, fill GEN_AI_API_KEY)
  - telepresence installed; either passwordless sudo or already connected

Each service logs to log/<service>.log. Ctrl-C stops everything.

Examples:
  ods k8s up
  ods k8s logs    # in another terminal`,
		Run: func(cmd *cobra.Command, args []string) {
			runK8sUp()
		},
	}

	return cmd
}

func newK8sDownCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "down",
		Short: "Stop running services and tear down the telepresence intercept",
		Long: `Stop services started by "ods k8s up", leave the telepresence intercept
on onyx-api-server, and quit the telepresence daemon.

Useful when the "up" terminal was killed and orphaned the services, or
to clean up from a different shell. In the happy path, Ctrl-C in the
"up" terminal already handles this.

Examples:
  ods k8s down`,
		Run: func(cmd *cobra.Command, args []string) {
			runK8sDown()
		},
	}

	return cmd
}

// processPatterns are pgrep -f patterns matching processes started by "ods k8s up".
var processPatterns = []string{
	"dev_celery_reload",
	"uvicorn onyx.main",
	"next dev",
}

func runK8sDown() {
	for _, pattern := range processPatterns {
		killByPattern(pattern)
	}

	log.Info("Leaving telepresence intercept on onyx-api-server...")
	leaveCmd := exec.Command("telepresence", "leave", "onyx-api-server")
	leaveCmd.Stdout = os.Stdout
	leaveCmd.Stderr = os.Stderr
	// Ignore errors — intercept may not exist, which is fine.
	_ = leaveCmd.Run()

	log.Info("Quitting telepresence daemon...")
	quitCmd := exec.Command("telepresence", "quit", "-s")
	quitCmd.Stdout = os.Stdout
	quitCmd.Stderr = os.Stderr
	_ = quitCmd.Run()
}

// killByPattern sends SIGTERM to all processes matching the pgrep -f pattern.
// Logs how many processes were killed; missing matches are not an error.
func killByPattern(pattern string) {
	out, err := exec.Command("pgrep", "-f", pattern).Output()
	if err != nil {
		// pgrep exits 1 when no matches found — not an error.
		log.Debugf("No processes matching %q", pattern)
		return
	}

	var pids []string
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line != "" {
			pids = append(pids, line)
		}
	}
	if len(pids) == 0 {
		log.Debugf("No processes matching %q", pattern)
		return
	}

	log.Infof("Killing %d process(es) matching %q (pids: %v)", len(pids), pattern, pids)
	killCmd := exec.Command("kill", append([]string{"-TERM"}, pids...)...)
	if err := killCmd.Run(); err != nil {
		log.Warnf("kill failed for pattern %q: %v", pattern, err)
	}
}

func runK8sUp() {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	script := filepath.Join(root, "scripts", "run-all-k8s.sh")
	if _, err := os.Stat(script); err != nil {
		log.Fatalf("Script not found at %s: %v", script, err)
	}

	svcCmd := exec.Command(script)
	svcCmd.Dir = root
	svcCmd.Stdout = os.Stdout
	svcCmd.Stderr = os.Stderr
	svcCmd.Stdin = os.Stdin

	if err := svcCmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			if code := exitErr.ExitCode(); code != -1 {
				os.Exit(code)
			}
		}
		log.Fatalf("Failed to run %s: %v", script, err)
	}
}
