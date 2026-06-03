package cmd

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// celeryWorker describes a single celery worker (or beat) process. The fields
// mirror the "Celery <name>" configurations in .vscode/launch.json so that
// `ods celery` launches the same set of processes as the "Run All Onyx
// Services" debug compound.
type celeryWorker struct {
	name        string // logical worker name, also used for --hostname and CLI selection
	command     string // celery subcommand: "worker" or "beat"
	concurrency string // --concurrency value; empty omits the flag (celery default)
	prefetch    string // --prefetch-multiplier value; empty omits the flag
	queues      string // comma-separated -Q queues; empty omits the flag (beat)
	inDefault   bool   // part of the default set run when no workers are named
}

// celeryWorkers is the canonical worker list, kept in sync with the celery
// configurations in .vscode/launch.json. `monitoring` is excluded from the
// default set to match the "Run All Onyx Services" compound, but can be run
// explicitly (`ods celery monitoring`) or via --all.
var celeryWorkers = []celeryWorker{
	{name: "primary", command: "worker", concurrency: "4", prefetch: "1", queues: "celery", inDefault: true},
	{name: "light", command: "worker", concurrency: "64", prefetch: "8", queues: "vespa_metadata_sync,connector_deletion,doc_permissions_upsert,checkpoint_cleanup,index_attempt_cleanup,opensearch_migration", inDefault: true},
	{name: "heavy", command: "worker", concurrency: "4", prefetch: "1", queues: "connector_pruning,connector_doc_permissions_sync,connector_external_group_sync,csv_generation,sandbox", inDefault: true},
	{name: "docfetching", command: "worker", prefetch: "1", queues: "connector_doc_fetching", inDefault: true},
	{name: "docprocessing", command: "worker", prefetch: "1", queues: "docprocessing", inDefault: true},
	{name: "user_file_processing", command: "worker", concurrency: "2", prefetch: "1", queues: "user_file_processing,user_file_project_sync,user_file_delete", inDefault: true},
	{name: "scheduled_tasks", command: "worker", concurrency: "4", prefetch: "1", queues: "scheduled_tasks", inDefault: true},
	{name: "beat", command: "beat", inDefault: true},
	{name: "monitoring", command: "worker", concurrency: "1", prefetch: "1", queues: "monitoring", inDefault: false},
}

// CeleryOptions holds options for the celery command.
type CeleryOptions struct {
	NoEE     bool
	NoReload bool
	LogLevel string
	All      bool
}

func NewCeleryCommand() *cobra.Command {
	opts := &CeleryOptions{}

	cmd := &cobra.Command{
		Use:   "celery [worker...]",
		Short: "Run Onyx celery workers (with hot-reload)",
		Long: `Run Onyx celery workers with environment from .vscode/.env.

With no arguments, starts every worker in the "Run All Onyx Services" debug
compound (primary, light, heavy, docfetching, docprocessing,
user_file_processing, scheduled_tasks, beat). Pass worker names to run only a
subset, or --all to additionally include the monitoring worker.

Each worker runs through scripts/dev_celery_reload.py for hot-reload on changes
under backend/onyx and backend/ee (disable with --no-reload). All workers stream
to this terminal with a per-worker prefix; Ctrl-C stops them all.

Enterprise Edition features are enabled by default for development, with license
enforcement disabled.

Available workers:
  primary, light, heavy, docfetching, docprocessing,
  user_file_processing, scheduled_tasks, beat, monitoring

Examples:
  ods celery
  ods celery primary beat
  ods celery --all
  ods celery docfetching docprocessing --no-reload`,
		Run: func(cmd *cobra.Command, args []string) {
			runCelery(selectCeleryWorkers(args, opts.All), opts)
		},
	}

	cmd.Flags().BoolVar(&opts.NoEE, "no-ee", false, "Disable Enterprise Edition features (enabled by default)")
	cmd.Flags().BoolVar(&opts.NoReload, "no-reload", false, "Disable hot-reload (run celery directly)")
	cmd.Flags().BoolVar(&opts.All, "all", false, "Run every worker, including monitoring")
	cmd.Flags().StringVar(&opts.LogLevel, "loglevel", "INFO", "Celery log level")

	return cmd
}

// selectCeleryWorkers resolves the worker list from positional args. With no
// args it returns the default set (or all workers when --all is set).
func selectCeleryWorkers(args []string, all bool) []celeryWorker {
	if all {
		if len(args) > 0 {
			log.Fatal("--all cannot be combined with named workers")
		}
		return celeryWorkers
	}

	if len(args) == 0 {
		var defaults []celeryWorker
		for _, w := range celeryWorkers {
			if w.inDefault {
				defaults = append(defaults, w)
			}
		}
		return defaults
	}

	byName := make(map[string]celeryWorker, len(celeryWorkers))
	for _, w := range celeryWorkers {
		byName[w.name] = w
	}

	var selected []celeryWorker
	for _, name := range args {
		w, ok := byName[name]
		if !ok {
			log.Fatalf("Unknown celery worker %q. Available: %s", name, allCeleryWorkerNames())
		}
		selected = append(selected, w)
	}
	return selected
}

func allCeleryWorkerNames() string {
	names := make([]string, len(celeryWorkers))
	for i, w := range celeryWorkers {
		names[i] = w.name
	}
	return strings.Join(names, ", ")
}

// celeryArgs builds the argument list forwarded to the celery CLI for a worker.
func (w celeryWorker) celeryArgs(loglevel string) []string {
	args := []string{
		"-A", "onyx.background.celery.versioned_apps." + w.name,
		w.command,
		"--loglevel=" + loglevel,
	}
	if w.command != "worker" {
		return args
	}

	args = append(args, "--pool=threads")
	if w.concurrency != "" {
		args = append(args, "--concurrency="+w.concurrency)
	}
	if w.prefetch != "" {
		args = append(args, "--prefetch-multiplier="+w.prefetch)
	}
	args = append(args, "--hostname="+w.name+"@%n")
	if w.queues != "" {
		args = append(args, "-Q", w.queues)
	}
	return args
}

func runCelery(workers []celeryWorker, opts *CeleryOptions) {
	if len(workers) == 0 {
		log.Fatal("No celery workers selected")
	}

	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	backendDir := filepath.Join(root, "backend")

	envFile := ensureBackendEnvFile(root)
	fileVars := loadBackendEnvFile(envFile)
	fileVars = append(fileVars, eeEnvDefaults(opts.NoEE)...)
	mergedEnv := mergeEnv(os.Environ(), fileVars)
	log.Debugf("Applied %d env vars from %s (shell takes precedence)", len(fileVars), envFile)

	names := make([]string, len(workers))
	for i, w := range workers {
		names[i] = w.name
	}
	log.Infof("Starting %d celery worker(s): %s", len(workers), strings.Join(names, ", "))
	if !opts.NoReload {
		log.Info("Hot-reload enabled (use --no-reload to disable)")
	}
	if !opts.NoEE {
		log.Info("Enterprise Edition enabled (use --no-ee to disable)")
	}

	// Shared mutex so concurrent workers never interleave a partial line.
	var writeMu sync.Mutex
	colorize := isCharDevice(os.Stdout)

	var wg sync.WaitGroup
	var cmds []*exec.Cmd
	for i, w := range workers {
		celeryCLIArgs := w.celeryArgs(opts.LogLevel)

		var runArgs []string
		if opts.NoReload {
			runArgs = append([]string{"run", "celery"}, celeryCLIArgs...)
		} else {
			runArgs = append([]string{"run", "python", "scripts/dev_celery_reload.py"}, celeryCLIArgs...)
		}

		svcCmd := exec.Command("uv", runArgs...)
		svcCmd.Dir = backendDir
		svcCmd.Env = mergedEnv
		// Own process group so we can signal the whole tree (uv -> python ->
		// watchfiles fork -> celery) on shutdown.
		svcCmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

		prefix := celeryPrefix(w.name, i, colorize)
		svcCmd.Stdout = &linePrefixWriter{w: os.Stdout, prefix: prefix, mu: &writeMu}
		svcCmd.Stderr = &linePrefixWriter{w: os.Stderr, prefix: prefix, mu: &writeMu}

		log.Debugf("[%s] uv %s", w.name, strings.Join(runArgs, " "))
		if err := svcCmd.Start(); err != nil {
			// A partial startup would leave a silently degraded stack, so tear
			// down the workers we did start and fail.
			log.Errorf("Failed to start celery %s: %v", w.name, err)
			terminateCeleryWorkers(cmds)
			wg.Wait()
			os.Exit(1)
		}

		cmds = append(cmds, svcCmd)
		wg.Add(1)
		go func(c *exec.Cmd, name string) {
			defer wg.Done()
			if err := c.Wait(); err != nil {
				log.Debugf("celery %s exited: %v", name, err)
			}
		}(svcCmd, w.name)
	}

	// Forward the first interrupt to every worker's process group, then wait
	// for them to drain.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigCh
		log.Info("Shutting down celery workers...")
		terminateCeleryWorkers(cmds)
	}()

	wg.Wait()
}

// terminateCeleryWorkers sends SIGTERM to each worker's process group, stopping
// the whole tree (uv -> python -> watchfiles fork -> celery).
func terminateCeleryWorkers(cmds []*exec.Cmd) {
	for _, c := range cmds {
		if c.Process != nil {
			_ = syscall.Kill(-c.Process.Pid, syscall.SIGTERM)
		}
	}
}

// linePrefixWriter buffers bytes until a newline, then writes the complete line
// prefixed with the worker label. The shared mutex serializes writes across all
// workers so lines never interleave.
type linePrefixWriter struct {
	w      io.Writer
	prefix string
	mu     *sync.Mutex
	buf    []byte
}

func (p *linePrefixWriter) Write(b []byte) (int, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, c := range b {
		if c != '\n' {
			p.buf = append(p.buf, c)
			continue
		}
		_, _ = fmt.Fprintf(p.w, "%s%s\n", p.prefix, p.buf)
		p.buf = p.buf[:0]
	}
	return len(b), nil
}

var celeryPrefixColors = []string{
	"\033[36m", "\033[32m", "\033[33m", "\033[35m", "\033[34m",
	"\033[31m", "\033[96m", "\033[92m", "\033[95m",
}

const celeryColorReset = "\033[0m"

func celeryPrefix(name string, index int, colorize bool) string {
	label := fmt.Sprintf("%-20s | ", name)
	if !colorize {
		return label
	}
	return celeryPrefixColors[index%len(celeryPrefixColors)] + label + celeryColorReset
}

func isCharDevice(f *os.File) bool {
	info, err := f.Stat()
	if err != nil {
		return false
	}
	return info.Mode()&os.ModeCharDevice != 0
}
