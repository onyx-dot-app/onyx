package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"text/tabwriter"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

func newStackLsCommand() *cobra.Command {
	var asJSON, all, orphaned bool
	cmd := &cobra.Command{
		Use:   "ls",
		Short: "List every dev stack on this machine, with the command that stops each",
		Long: `List every Onyx dev stack on this machine, from any directory. ls reads
Docker, the project owner records, the stack state files and the port
leases. It takes no locks and changes nothing.

Statuses:
  orphaned     no worktree owns the stack any more: stop it with
               'ods stack down --project NAME' or 'ods stack prune'
  active       application processes run
  app-stopped  infrastructure runs, 'ods stack stop' stopped the app
  infra-only   infrastructure runs, no application process does
  stopped      nothing runs (shown with --all)
  stale-lease  port leases that no stack uses (shown with --all)

Exit codes: 0 success, 3 when --orphaned finds an orphan, 1 when no
source could be read.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			inv := discoverStacks()
			for _, warning := range inv.Warnings {
				log.Warn(warning)
			}
			if inv.Unreadable {
				log.Error("no stack source could be read")
				exitHook(1)
				return
			}
			rows := filterStackRows(inv.Rows, all, orphaned)
			if len(rows) == 0 && !asJSON {
				switch {
				case orphaned:
					fmt.Println("No orphaned dev stacks found")
				case all:
					fmt.Println("No dev stacks found on this machine; run 'ods stack up' in a worktree to start one")
				default:
					fmt.Println("No running dev stacks found; run 'ods stack ls --all' to include stopped stacks")
				}
				return
			}
			if asJSON {
				printJSON(rows)
			} else {
				printStackRows(os.Stdout, rows, time.Now())
				if hidden := len(filterStackRows(inv.Rows, true, orphaned)) - len(rows); hidden > 0 {
					fmt.Printf("\n%d stopped stack(s) or stale lease(s) hidden; run 'ods stack ls --all' to show them\n", hidden)
				}
			}
			if orphaned && len(rows) > 0 {
				exitHook(3)
			}
		},
	}
	cmd.Flags().BoolVar(&asJSON, "json", false, "Print the stacks as a JSON array")
	cmd.Flags().BoolVar(&all, "all", false, "Also show stopped stacks and stale port leases")
	cmd.Flags().BoolVar(&orphaned, "orphaned", false, "Show only orphaned stacks")
	return cmd
}

func newStackPruneCommand() *cobra.Command {
	var yes, volumes bool
	var stopTimeout, lockWait time.Duration
	cmd := &cobra.Command{
		Use:   "prune",
		Short: "Run 'down --project' for every orphaned stack (volumes are kept)",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			inv := discoverStacks()
			for _, warning := range inv.Warnings {
				log.Warn(warning)
			}
			rows := filterStackRows(inv.Rows, true, true)
			if len(rows) == 0 {
				log.Info("No orphaned stacks")
				return
			}
			printStackRows(os.Stdout, rows, time.Now())
			if !yes && !prompt.Confirm(fmt.Sprintf("Stop %d orphaned stack(s) and their containers? Volumes are kept. (yes/no): ", len(rows))) {
				log.Fatal("Aborted")
			}
			if volumes && !prompt.Confirm(fmt.Sprintf("Also DELETE the Docker volumes (database, index, files) of %s? (yes/no): ", stackRowNames(rows))) {
				log.Fatal("Aborted")
			}
			registry := runtimeRegistry()
			failed := 0
			for _, row := range rows {
				result, err := devstack.CleanupRow(context.Background(), registry, row, composeDownProject,
					devstack.ProjectOptions{StopTimeout: stopTimeout, LockWait: lockWait, Volumes: volumes})
				if err != nil {
					log.Errorf("%s: %v", stackRowName(row), err)
					failed++
					continue
				}
				logProjectResult(result)
			}
			if failed > 0 {
				exitHook(1)
			}
		},
	}
	cmd.Flags().BoolVar(&yes, "yes", false, "Do not ask for confirmation (the --volumes confirmation is still asked)")
	cmd.Flags().BoolVar(&volumes, "volumes", false, "Also delete the Docker volumes of the orphaned stacks")
	cmd.Flags().DurationVar(&stopTimeout, "timeout", 20*time.Second, "Grace period before a service is killed")
	cmd.Flags().DurationVar(&lockWait, "lock-wait", 10*time.Minute, "How long to wait for another lifecycle command on a stack")
	return cmd
}

func discoverStacks() devstack.Inventory {
	var dirs []string
	if cwd, err := os.Getwd(); err == nil {
		dirs = append(dirs, cwd)
	}
	return devstack.Discover(runtimeRegistry(), devstack.DiscoverOptions{Dirs: dirs})
}

func filterStackRows(rows []devstack.StackRow, all, orphaned bool) []devstack.StackRow {
	kept := []devstack.StackRow{}
	for _, row := range rows {
		switch {
		case orphaned:
			if row.Status != devstack.StatusOrphaned {
				continue
			}
		case !all:
			if !row.Running() {
				continue
			}
		}
		kept = append(kept, row)
	}
	return kept
}

// runProjectLifecycle stops (or downs) a stack selected by project from any
// directory, for a stack whose checkout is gone or is elsewhere.
func runProjectLifecycle(name, project string, opts devstack.ProjectOptions) {
	registry := runtimeRegistry()
	var result *devstack.ProjectResult
	var err error
	if name == "down" {
		result, err = devstack.DownProject(context.Background(), registry, project, composeDownProject, opts)
	} else {
		result, err = devstack.StopProject(context.Background(), registry, project, opts)
	}
	if result != nil {
		logProjectResult(result)
	}
	if err != nil {
		log.Fatal(err)
	}
}

// projectInCheckout reports whether the stack of the current checkout in
// the selected mode already records project, so the checkout path applies.
func projectInCheckout(project string) bool {
	cwd, err := os.Getwd()
	if err != nil {
		return false
	}
	mode := devstack.Shared
	if rootIsolated {
		mode = devstack.Isolated
	}
	stack, err := devstack.Open(cwd, project, mode)
	if err != nil {
		return false
	}
	st, err := stack.ReadState()
	if err != nil || st == nil || st.Project != docker.NormalizeProjectName(project) {
		return false
	}
	return mode != devstack.Shared || st.Root == stack.Root
}

func logProjectResult(result *devstack.ProjectResult) {
	parts := []string{fmt.Sprintf("%d service(s) stopped", result.StoppedServices)}
	if result.ComposeDown {
		parts = append(parts, "containers removed")
	}
	if result.ReleasedLeases > 0 {
		parts = append(parts, fmt.Sprintf("%d port lease(s) released", result.ReleasedLeases))
	}
	if result.RemovedOwner {
		parts = append(parts, "owner record removed")
	}
	log.Infof("%s: %s", stackRowName(result.Row), strings.Join(parts, ", "))
}

// composeDownProject runs Compose down by project name alone, so it works
// when the checkout that started the project is gone.
func composeDownProject(ctx context.Context, project string, volumes bool) error {
	args := []string{"compose", "-p", project, "down"}
	if volumes {
		args = append(args, "--volumes")
	}
	cmd := exec.CommandContext(ctx, "docker", args...)
	// A neutral directory keeps Compose from loading an unrelated compose file.
	cmd.Dir = os.TempDir()
	cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("docker %s: %w", strings.Join(args, " "), err)
	}
	return nil
}

func printJSON(value any) {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(value); err != nil {
		log.Fatal(err)
	}
}

func printStackRows(out io.Writer, rows []devstack.StackRow, now time.Time) {
	if len(rows) == 0 {
		_, _ = fmt.Fprintln(out, "No running dev stacks found")
		return
	}
	w := tabwriter.NewWriter(out, 0, 0, 2, ' ', 0)
	_, _ = fmt.Fprintln(w, "PROJECT\tSTATUS\tAPP\tINFRA\tWEB\tAGE\tROOT")
	statuses := map[string]bool{}
	for _, row := range rows {
		statuses[row.Status] = true
		app, infra, web := "-", "-", "-"
		if row.App != nil && row.App.Total > 0 {
			app = fmt.Sprintf("%d/%d", row.App.Running, row.App.Total)
		}
		if row.Infra != nil {
			infra = fmt.Sprintf("%d/%d", row.Infra.Running, row.Infra.Total)
			if row.Infra.Health != "" && row.Infra.Health != "healthy" {
				infra += " " + row.Infra.Health
			}
		}
		if row.Web != "" {
			web = row.Web
		}
		_, _ = fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", stackRowName(row), row.Status, app, infra, web, formatAge(row.Since, now), displayRoot(row))
		for _, e := range row.Errors {
			_, _ = fmt.Fprintf(w, "  error: %s\t\t\t\t\t\t\n", e)
		}
	}
	_ = w.Flush()
	var next []string
	for _, row := range rows {
		if row.Next != "" {
			next = append(next, fmt.Sprintf("  %s (%s): %s", stackRowName(row), row.Status, row.Next))
		}
	}
	if len(next) > 0 {
		_, _ = fmt.Fprintln(out, "\nTo stop a stack, run:")
		for _, line := range next {
			_, _ = fmt.Fprintln(out, line)
		}
	}
	if statuses[devstack.StatusOrphaned] {
		_, _ = fmt.Fprintln(out, "\nOrphaned stacks have no worktree. 'ods stack prune' stops all of them; volumes are kept.")
	}
}

func stackRowName(row devstack.StackRow) string {
	name := row.Project
	if name == "" {
		name = "-"
	}
	if row.Mode == devstack.Frontend {
		name += " (frontend)"
	}
	return name
}

func stackRowNames(rows []devstack.StackRow) string {
	names := make([]string, 0, len(rows))
	for _, row := range rows {
		names = append(names, stackRowName(row))
	}
	return strings.Join(names, ", ")
}

func formatAge(since, now time.Time) string {
	if since.IsZero() {
		return "-"
	}
	d := now.Sub(since)
	switch {
	case d < time.Minute:
		return fmt.Sprintf("%ds", max(0, int(d.Seconds())))
	case d < time.Hour:
		return fmt.Sprintf("%dm", int(d.Minutes()))
	case d < 24*time.Hour:
		return fmt.Sprintf("%dh", int(d.Hours()))
	}
	return fmt.Sprintf("%dd", int(d.Hours()/24))
}

func displayRoot(row devstack.StackRow) string {
	if row.Root == "" {
		return "-"
	}
	root := shortenPath(row.Root)
	switch {
	case !row.RootExists:
		root += " (missing)"
	case !row.Worktree && row.StateDir != "":
		root += " (not a worktree)"
	case row.Branch != "":
		root += " [" + row.Branch + "]"
	}
	return root
}

// shortenPath abbreviates the home directory and keeps the last two
// elements of a deep path.
func shortenPath(path string) string {
	prefix := ""
	rest := path
	if home, err := os.UserHomeDir(); err == nil && home != "" && (path == home || strings.HasPrefix(path, home+string(filepath.Separator))) {
		prefix, rest = "~", strings.TrimPrefix(path, home)
	}
	parts := strings.Split(strings.Trim(rest, string(filepath.Separator)), string(filepath.Separator))
	if len(parts) <= 3 {
		if prefix == "" {
			return path
		}
		return prefix + rest
	}
	sep := string(filepath.Separator)
	return prefix + sep + "…" + sep + strings.Join(parts[len(parts)-2:], sep)
}
