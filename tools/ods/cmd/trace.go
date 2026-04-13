package cmd

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/tui"
)

const playwrightWorkflow = "Run Playwright Tests"

// TraceOptions holds options for the trace command
type TraceOptions struct {
	Branch  string
	PR      string
	Project string
	List    bool
	NoOpen  bool
}

// traceInfo describes a single trace.zip found in the downloaded artifacts.
type traceInfo struct {
	Path    string // absolute path to trace.zip
	Project string // project group extracted from artifact dir (e.g. "admin", "admin-shard-1")
	TestDir string // test directory name (human-readable-ish)
}

// NewTraceCommand creates a new trace command
func NewTraceCommand() *cobra.Command {
	opts := &TraceOptions{}

	cmd := &cobra.Command{
		Use:   "trace [run-id-or-url]",
		Short: "Download and view Playwright traces from GitHub Actions",
		Long: `Download Playwright trace artifacts from a GitHub Actions run and open them
with 'playwright show-trace'.

The run can be specified as:
  - A GitHub Actions run ID (numeric)
  - A full GitHub Actions run URL
  - Omitted, to find the latest Playwright run for the current branch

You can also look up the latest run by branch name or PR number.

Examples:
  ods trace                          # latest run for current branch
  ods trace 12345678                 # specific run ID
  ods trace https://github.com/onyx-dot-app/onyx/actions/runs/12345678
  ods trace --pr 9500                # latest run for PR #9500
  ods trace --branch main            # latest run for main branch
  ods trace --project admin          # only download admin project traces
  ods trace --list                   # list available traces without opening`,
		Args: cobra.MaximumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runTrace(args, opts)
		},
	}

	cmd.Flags().StringVarP(&opts.Branch, "branch", "b", "", "Find latest run for this branch")
	cmd.Flags().StringVar(&opts.PR, "pr", "", "Find latest run for this PR number")
	cmd.Flags().StringVarP(&opts.Project, "project", "p", "", "Filter to a specific project (admin, exclusive, lite)")
	cmd.Flags().BoolVarP(&opts.List, "list", "l", false, "List available traces without opening")
	cmd.Flags().BoolVar(&opts.NoOpen, "no-open", false, "Download traces but don't open them")

	return cmd
}

// ghRun represents a GitHub Actions workflow run from `gh run list`
type ghRun struct {
	DatabaseID int64  `json:"databaseId"`
	Status     string `json:"status"`
	Conclusion string `json:"conclusion"`
	HeadBranch string `json:"headBranch"`
	URL        string `json:"url"`
}

func runTrace(args []string, opts *TraceOptions) {
	git.CheckGitHubCLI()

	runID, err := resolveRunID(args, opts)
	if err != nil {
		log.Fatalf("Failed to resolve run: %v", err)
	}

	log.Infof("Using run ID: %s", runID)

	destDir, err := downloadTraceArtifacts(runID, opts.Project)
	if err != nil {
		log.Fatalf("Failed to download artifacts: %v", err)
	}

	traces, err := findTraceInfos(destDir, runID)
	if err != nil {
		log.Fatalf("Failed to find traces: %v", err)
	}

	if len(traces) == 0 {
		log.Info("No trace files found in the downloaded artifacts.")
		log.Info("Traces are only generated for failing tests (retain-on-failure).")
		return
	}

	projects := groupByProject(traces)

	if opts.List || opts.NoOpen {
		printTraceList(traces, projects)
		fmt.Printf("\nTraces downloaded to: %s\n", destDir)
		return
	}

	if len(traces) == 1 {
		openTraces(traces)
		return
	}

	for {
		selected := selectTraces(traces, projects)
		if len(selected) == 0 {
			return
		}
		openTraces(selected)
	}
}

// resolveRunID determines the run ID from the provided arguments and options.
func resolveRunID(args []string, opts *TraceOptions) (string, error) {
	if len(args) == 1 {
		return parseRunIDFromArg(args[0])
	}

	if opts.PR != "" {
		return findLatestRunForPR(opts.PR)
	}

	branch := opts.Branch
	if branch == "" {
		var err error
		branch, err = git.GetCurrentBranch()
		if err != nil {
			return "", fmt.Errorf("failed to get current branch: %w", err)
		}
		if branch == "" {
			return "", fmt.Errorf("detached HEAD; specify a --branch, --pr, or run ID")
		}
		log.Infof("Using current branch: %s", branch)
	}

	return findLatestRunForBranch(branch)
}

var runURLPattern = regexp.MustCompile(`/actions/runs/(\d+)`)

// parseRunIDFromArg extracts a run ID from either a numeric string or a full URL.
func parseRunIDFromArg(arg string) (string, error) {
	if matched, _ := regexp.MatchString(`^\d+$`, arg); matched {
		return arg, nil
	}

	matches := runURLPattern.FindStringSubmatch(arg)
	if matches != nil {
		return matches[1], nil
	}

	return "", fmt.Errorf("could not parse run ID from %q; expected a numeric ID or GitHub Actions URL", arg)
}

// findLatestRunForBranch finds the most recent Playwright workflow run for a branch.
func findLatestRunForBranch(branch string) (string, error) {
	log.Infof("Looking up latest Playwright run for branch: %s", branch)

	cmd := exec.Command("gh", "run", "list",
		"--workflow", playwrightWorkflow,
		"--branch", branch,
		"--limit", "1",
		"--json", "databaseId,status,conclusion,headBranch,url",
	)
	output, err := cmd.Output()
	if err != nil {
		return "", ghError(err, "gh run list failed")
	}

	var runs []ghRun
	if err := json.Unmarshal(output, &runs); err != nil {
		return "", fmt.Errorf("failed to parse run list: %w", err)
	}

	if len(runs) == 0 {
		return "", fmt.Errorf("no Playwright runs found for branch %q", branch)
	}

	run := runs[0]
	log.Infof("Found run: %s (status: %s, conclusion: %s)", run.URL, run.Status, run.Conclusion)
	return fmt.Sprintf("%d", run.DatabaseID), nil
}

// findLatestRunForPR finds the most recent Playwright workflow run for a PR.
func findLatestRunForPR(prNumber string) (string, error) {
	log.Infof("Looking up branch for PR #%s", prNumber)

	cmd := exec.Command("gh", "pr", "view", prNumber,
		"--json", "headRefName",
		"--jq", ".headRefName",
	)
	output, err := cmd.Output()
	if err != nil {
		return "", ghError(err, "gh pr view failed")
	}

	branch := strings.TrimSpace(string(output))
	if branch == "" {
		return "", fmt.Errorf("could not determine branch for PR #%s", prNumber)
	}

	log.Infof("PR #%s is on branch: %s", prNumber, branch)
	return findLatestRunForBranch(branch)
}

// downloadTraceArtifacts downloads playwright trace artifacts for a run.
// Returns the path to the download directory.
func downloadTraceArtifacts(runID string, project string) (string, error) {
	cacheKey := runID
	if project != "" {
		cacheKey = runID + "-" + project
	}
	destDir := filepath.Join(os.TempDir(), "ods-traces", cacheKey)

	// Reuse a previous download if traces exist
	if info, err := os.Stat(destDir); err == nil && info.IsDir() {
		traces, _ := findTraces(destDir)
		if len(traces) > 0 {
			log.Infof("Using cached download at %s", destDir)
			return destDir, nil
		}
		_ = os.RemoveAll(destDir)
	}

	if err := os.MkdirAll(destDir, 0755); err != nil {
		return "", fmt.Errorf("failed to create directory %s: %w", destDir, err)
	}

	ghArgs := []string{"run", "download", runID, "--dir", destDir}

	if project != "" {
		ghArgs = append(ghArgs, "--pattern", fmt.Sprintf("playwright-test-results-%s-*", project))
	} else {
		ghArgs = append(ghArgs, "--pattern", "playwright-test-results-*")
	}

	log.Infof("Downloading trace artifacts...")
	log.Debugf("Running: gh %s", strings.Join(ghArgs, " "))

	cmd := exec.Command("gh", ghArgs...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		_ = os.RemoveAll(destDir)
		return "", fmt.Errorf("gh run download failed: %w\nMake sure the run ID is correct and the artifacts haven't expired (30 day retention)", err)
	}

	return destDir, nil
}

// findTraces recursively finds all trace.zip files under a directory.
func findTraces(root string) ([]string, error) {
	var traces []string
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && info.Name() == "trace.zip" {
			traces = append(traces, path)
		}
		return nil
	})
	return traces, err
}

// findTraceInfos walks the download directory and returns structured trace info.
// Expects: destDir/{artifact-dir}/{test-dir}/trace.zip
func findTraceInfos(destDir, runID string) ([]traceInfo, error) {
	var traces []traceInfo
	err := filepath.Walk(destDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() || info.Name() != "trace.zip" {
			return nil
		}

		rel, _ := filepath.Rel(destDir, path)
		parts := strings.SplitN(rel, string(filepath.Separator), 3)

		artifactDir := ""
		testDir := filepath.Base(filepath.Dir(path))
		if len(parts) >= 2 {
			artifactDir = parts[0]
			testDir = parts[1]
		}

		traces = append(traces, traceInfo{
			Path:    path,
			Project: extractProject(artifactDir, runID),
			TestDir: testDir,
		})
		return nil
	})

	sort.Slice(traces, func(i, j int) bool {
		pi, pj := projectSortKey(traces[i].Project), projectSortKey(traces[j].Project)
		if pi != pj {
			return pi < pj
		}
		return traces[i].TestDir < traces[j].TestDir
	})

	return traces, err
}

// extractProject derives a project group from an artifact directory name.
// e.g. "playwright-test-results-admin-12345" -> "admin"
//
//	"playwright-test-results-admin-shard-1-12345" -> "admin-shard-1"
func extractProject(artifactDir, runID string) string {
	name := strings.TrimPrefix(artifactDir, "playwright-test-results-")
	name = strings.TrimSuffix(name, "-"+runID)
	if name == "" {
		return artifactDir
	}
	return name
}

// projectSortKey returns a sort-friendly key that orders admin < exclusive < lite.
func projectSortKey(project string) string {
	switch {
	case strings.HasPrefix(project, "admin"):
		return "0-" + project
	case strings.HasPrefix(project, "exclusive"):
		return "1-" + project
	case strings.HasPrefix(project, "lite"):
		return "2-" + project
	default:
		return "3-" + project
	}
}

// groupByProject returns an ordered list of unique project names found in traces.
func groupByProject(traces []traceInfo) []string {
	seen := map[string]bool{}
	var projects []string
	for _, t := range traces {
		if !seen[t.Project] {
			seen[t.Project] = true
			projects = append(projects, t.Project)
		}
	}
	sort.Slice(projects, func(i, j int) bool {
		return projectSortKey(projects[i]) < projectSortKey(projects[j])
	})
	return projects
}

// printTraceList displays traces grouped by project.
func printTraceList(traces []traceInfo, projects []string) {
	fmt.Printf("\nFound %d trace(s) across %d project(s):\n", len(traces), len(projects))

	idx := 1
	for _, proj := range projects {
		count := 0
		for _, t := range traces {
			if t.Project == proj {
				count++
			}
		}
		fmt.Printf("\n  %s (%d):\n", proj, count)
		for _, t := range traces {
			if t.Project == proj {
				fmt.Printf("    [%2d] %s\n", idx, t.TestDir)
				idx++
			}
		}
	}
}

// selectTraces tries the TUI picker first, falling back to a plain-text
// prompt when the terminal cannot be initialised (e.g. piped output).
func selectTraces(traces []traceInfo, projects []string) []traceInfo {
	// Build picker groups in the same order as the sorted traces slice.
	var groups []tui.PickerGroup
	for _, proj := range projects {
		var items []string
		for _, t := range traces {
			if t.Project == proj {
				items = append(items, t.TestDir)
			}
		}
		groups = append(groups, tui.PickerGroup{Label: proj, Items: items})
	}

	indices, err := tui.Pick(groups)
	if err != nil {
		// Terminal not available — fall back to text prompt
		log.Debugf("TUI picker unavailable: %v", err)
		printTraceList(traces, projects)
		return promptTraceSelection(traces, projects)
	}
	if indices == nil {
		return nil // user cancelled
	}

	selected := make([]traceInfo, len(indices))
	for i, idx := range indices {
		selected[i] = traces[idx]
	}
	return selected
}

// promptTraceSelection asks the user which traces to open via plain text.
// Accepts numbers (1,3,5), ranges (1-5), "all", or a project name.
func promptTraceSelection(traces []traceInfo, projects []string) []traceInfo {
	fmt.Printf("\nOpen which traces? (e.g. 1,3,5 | 1-5 | all | %s): ", strings.Join(projects, " | "))

	reader := bufio.NewReader(os.Stdin)
	input, err := reader.ReadString('\n')
	if err != nil {
		log.Fatalf("Failed to read input: %v", err)
	}
	input = strings.TrimSpace(input)

	if input == "" || strings.EqualFold(input, "all") {
		return traces
	}

	// Check if input matches a project name
	for _, proj := range projects {
		if strings.EqualFold(input, proj) {
			var selected []traceInfo
			for _, t := range traces {
				if t.Project == proj {
					selected = append(selected, t)
				}
			}
			return selected
		}
	}

	// Parse as number/range selection
	indices := parseTraceSelection(input, len(traces))
	if len(indices) == 0 {
		log.Warn("No valid selection; opening all traces")
		return traces
	}

	selected := make([]traceInfo, len(indices))
	for i, idx := range indices {
		selected[i] = traces[idx]
	}
	return selected
}

// parseTraceSelection parses a comma-separated list of numbers and ranges into
// 0-based indices. Input is 1-indexed (matches display). Out-of-range values
// are silently ignored.
func parseTraceSelection(input string, max int) []int {
	var result []int
	seen := map[int]bool{}

	for _, part := range strings.Split(input, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}

		if idx := strings.Index(part, "-"); idx > 0 {
			lo, err1 := strconv.Atoi(strings.TrimSpace(part[:idx]))
			hi, err2 := strconv.Atoi(strings.TrimSpace(part[idx+1:]))
			if err1 != nil || err2 != nil {
				continue
			}
			for i := lo; i <= hi; i++ {
				zi := i - 1
				if zi >= 0 && zi < max && !seen[zi] {
					result = append(result, zi)
					seen[zi] = true
				}
			}
		} else {
			n, err := strconv.Atoi(part)
			if err != nil {
				continue
			}
			zi := n - 1
			if zi >= 0 && zi < max && !seen[zi] {
				result = append(result, zi)
				seen[zi] = true
			}
		}
	}

	return result
}

// openTraces opens the selected traces with playwright show-trace,
// running npx from the web/ directory to use the project's Playwright version.
func openTraces(traces []traceInfo) {
	tracePaths := make([]string, len(traces))
	for i, t := range traces {
		tracePaths[i] = t.Path
	}

	args := append([]string{"playwright", "show-trace"}, tracePaths...)

	log.Infof("Opening %d trace(s) with playwright show-trace...", len(traces))
	cmd := exec.Command("npx", args...)

	// Run from web/ to pick up the locally-installed Playwright version
	if root, err := paths.GitRoot(); err == nil {
		cmd.Dir = filepath.Join(root, "web")
	}

	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin

	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			// Normal exit (e.g. user closed the window) — just log and return
			// so the picker loop can continue.
			log.Debugf("playwright exited with code %d", exitErr.ExitCode())
			return
		}
		log.Errorf("playwright show-trace failed: %v\nMake sure Playwright is installed (npx playwright install)", err)
	}
}

// ghError wraps a gh CLI error with stderr output.
func ghError(err error, msg string) error {
	if exitErr, ok := err.(*exec.ExitError); ok {
		return fmt.Errorf("%s: %w: %s", msg, err, string(exitErr.Stderr))
	}
	return fmt.Errorf("%s: %w", msg, err)
}
