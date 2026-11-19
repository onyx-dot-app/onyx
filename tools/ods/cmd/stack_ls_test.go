package cmd

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

const orphanInspect = `[{"Id":"a","Name":"/gone-1-relational_db-1","State":{"Status":"running","StartedAt":"2026-01-02T00:00:00Z"},
"Config":{"Labels":{"com.docker.compose.project":"gone-1","com.docker.compose.service":"relational_db","com.docker.compose.project.working_dir":"/nonexistent/gone/deployment/docker_compose"}}},
{"Id":"b","Name":"/gone-1-cache-1","State":{"Status":"running","StartedAt":"2026-01-02T00:00:00Z","Health":{"Status":"unhealthy"}},
"Config":{"Labels":{"com.docker.compose.project":"gone-1","com.docker.compose.service":"cache","com.docker.compose.project.working_dir":"/nonexistent/gone/deployment/docker_compose"}}}]`

// stackLsEnv isolates the data directory and fakes Docker with body.
func stackLsEnv(t *testing.T, body string) string {
	t.Helper()
	binDir := devtoolBinDir(t)
	ps, err := exec.LookPath("/bin/ps")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(ps, filepath.Join(binDir, "ps")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	t.Chdir(t.TempDir())
	return devtoolFakeTool(t, binDir, "docker", body)
}

func orphanDocker() string {
	return `case "$1" in
ps) echo a; echo b ;;
inspect) printf '%s\n' '` + orphanInspect + `' ;;
esac
exit 0
`
}

// runStackCLI runs ods with args and returns the exit code with stdout and
// the log output.
func runStackCLI(t *testing.T, args ...string) (code int, stdout string) {
	t.Helper()
	output, err := os.CreateTemp(t.TempDir(), "stdout")
	if err != nil {
		t.Fatal(err)
	}
	original := os.Stdout
	os.Stdout = output
	logger := log.StandardLogger()
	originalExit, originalHook, originalOutput := logger.ExitFunc, exitHook, logger.Out
	var logs strings.Builder
	logger.SetOutput(&logs)
	type exitCode int
	logger.ExitFunc = func(c int) { panic(exitCode(c)) }
	exitHook = func(c int) { panic(exitCode(c)) }
	defer func() {
		os.Stdout = original
		logger.ExitFunc, exitHook = originalExit, originalHook
		logger.SetOutput(originalOutput)
		data, err := os.ReadFile(output.Name())
		if err != nil {
			t.Fatal(err)
		}
		stdout = string(data) + logs.String()
	}()
	func() {
		defer func() {
			if got := recover(); got != nil {
				c, ok := got.(exitCode)
				if !ok {
					panic(got)
				}
				code = int(c)
			}
		}()
		cmd := NewRootCommand()
		cmd.SetArgs(args)
		_ = cmd.Execute()
	}()
	return code, stdout
}

func TestStackLsFlagsOrphansAndPrintsTheNextCommand(t *testing.T) {
	stackLsEnv(t, orphanDocker())
	code, out := runStackCLI(t, "stack", "ls")
	if code != 0 || !strings.Contains(out, "gone-1") || !strings.Contains(out, "orphaned") || !strings.Contains(out, "ods stack down --project gone-1") || !strings.Contains(out, "(missing)") || !strings.Contains(out, "2/2 unhealthy") {
		t.Fatalf("ls exit %d:\n%s", code, out)
	}
	code, out = runStackCLI(t, "stack", "ls", "--orphaned", "--json")
	var rows []devstack.StackRow
	if err := json.Unmarshal([]byte(out[:strings.LastIndex(out, "]")+1]), &rows); err != nil || code != 3 || len(rows) != 1 || rows[0].Next != "ods stack down --project gone-1" {
		t.Fatalf("ls --orphaned exit %d rows %+v err %v", code, rows, err)
	}
}

func TestStackLsWithoutStacks(t *testing.T) {
	stackLsEnv(t, "exit 0\n")
	for _, tc := range []struct {
		args []string
		want string
	}{
		{[]string{"stack", "ls"}, "ods stack ls --all"},
		{[]string{"stack", "ls", "--all"}, "ods stack up"},
		{[]string{"stack", "ls", "--orphaned"}, "No orphaned"},
		{[]string{"stack", "ls", "--json"}, "[]"},
	} {
		if code, out := runStackCLI(t, tc.args...); code != 0 || !strings.Contains(out, tc.want) {
			t.Errorf("%v: exit %d, output %q", tc.args, code, out)
		}
	}
}

func TestStackLsHidesStaleLeasesUntilAll(t *testing.T) {
	stackLsEnv(t, "exit 0\n")
	if _, err := runtimeRegistry().LeaseFor(t.TempDir(), "", []devstack.PortRequest{{Name: "web", Fixed: 43123}}); err != nil {
		t.Fatal(err)
	}
	if code, out := runStackCLI(t, "stack", "ls"); code != 0 || !strings.Contains(out, "ods stack ls --all") {
		t.Fatalf("ls exit %d:\n%s", code, out)
	}
	if code, out := runStackCLI(t, "stack", "ls", "--all"); code != 0 || !strings.Contains(out, "stale-lease") {
		t.Fatalf("ls --all exit %d:\n%s", code, out)
	}
}

func TestStackLsExitsOneWhenNoSourceCanBeRead(t *testing.T) {
	stackLsEnv(t, "exit 1\n")
	dir := runtimeRegistry().Dir
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "ports.json"), "not json")
	if code, _ := runStackCLI(t, "stack", "ls"); code != 1 {
		t.Fatalf("exit %d, want 1", code)
	}
}

func TestStackDownByProjectRunsComposeByName(t *testing.T) {
	calls := stackLsEnv(t, orphanDocker())
	if code, _ := runStackCLI(t, "stack", "stop", "--project", "gone-1"); code != 0 {
		t.Fatalf("stop --project exit %d", code)
	}
	if code, _ := runStackCLI(t, "stack", "down", "--project", "gone-1"); code != 0 {
		t.Fatalf("down --project exit %d", code)
	}
	var compose []devtoolCall
	for _, call := range devtoolCalls(t, calls) {
		if call.Args[0] == "compose" {
			compose = append(compose, call)
		}
	}
	if len(compose) != 1 || strings.Join(compose[0].Args, " ") != "compose -p gone-1 down" {
		t.Fatalf("compose calls = %+v", compose)
	}
	if code, _ := runStackCLI(t, "stack", "down", "--project", "missing-project"); code != 1 {
		t.Fatalf("down of an unknown project exit %d, want 1", code)
	}
}

func TestStackPruneStopsEveryOrphan(t *testing.T) {
	calls := stackLsEnv(t, orphanDocker())
	if code, out := runStackCLI(t, "stack", "prune", "--yes"); code != 0 || !strings.Contains(out, "gone-1") {
		t.Fatalf("prune exit %d:\n%s", code, out)
	}
	found := false
	for _, call := range devtoolCalls(t, calls) {
		if strings.Join(call.Args, " ") == "compose -p gone-1 down" {
			found = true
		}
	}
	if !found {
		t.Fatal("prune did not run compose down")
	}
}

func TestStackPruneWithoutOrphans(t *testing.T) {
	calls := stackLsEnv(t, "exit 0\n")
	if code, _ := runStackCLI(t, "stack", "prune", "--yes"); code != 0 {
		t.Fatalf("prune exit %d", code)
	}
	for _, call := range devtoolCalls(t, calls) {
		if call.Args[0] == "compose" {
			t.Fatal("prune without orphans ran compose")
		}
	}
}

func TestStackPruneReportsComposeFailure(t *testing.T) {
	stackLsEnv(t, `[ "$1" = compose ] && exit 1
`+orphanDocker())
	if code, _ := runStackCLI(t, "stack", "prune", "--yes"); code != 1 {
		t.Fatalf("failed prune exit %d, want 1", code)
	}
}

func TestStackPruneLeavesVolumeOnlyOrphansForPruneVolumes(t *testing.T) {
	calls := stackLsEnv(t, `case "$1" in
volume) echo removed-1; echo removed-1 ;;
esac
exit 0
`)
	owner := filepath.Join(runtimeRegistry().Dir, "projects", devstack.ProjectName("removed-1"), "owner.json")
	if err := os.MkdirAll(filepath.Dir(owner), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, owner, `{"state_dir":"/missing/ods-stack"}`)

	code, out := runStackCLI(t, "stack", "ls")
	if code != 0 || !strings.Contains(out, "removed-1") || !strings.Contains(out, "ods stack prune --volumes") {
		t.Fatalf("ls exit %d:\n%s", code, out)
	}
	code, out = runStackCLI(t, "stack", "prune", "--yes")
	if code != 0 || !strings.Contains(out, "1 removed stack(s) left only Docker volumes") || !strings.Contains(out, "No orphaned stacks") {
		t.Fatalf("prune exit %d:\n%s", code, out)
	}
	for _, call := range devtoolCalls(t, calls) {
		if call.Args[0] == "compose" {
			t.Fatalf("prune without --volumes ran %v", call.Args)
		}
	}
	if _, err := os.Stat(owner); err != nil {
		t.Fatalf("prune removed the owner record of a project with volumes: %v", err)
	}
}

func TestPrintStackRowsShowsEachRowState(t *testing.T) {
	home, err := os.UserHomeDir()
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	rows := []devstack.StackRow{
		{Project: "a-1", Status: devstack.StatusActive, Root: filepath.Join(home, "x", "y", ".worktrees", "a"), RootExists: true, Worktree: true, Branch: "feat",
			App: &devstack.AppCount{Running: 2, Total: 2}, Infra: &devstack.InfraCount{Running: 7, Total: 7, Health: "healthy"}, Web: "http://localhost:3004",
			Since: now.Add(-2 * time.Hour), Next: "cd /a && ods --isolated stack down"},
		{Project: "b-1", Mode: devstack.Frontend, Status: devstack.StatusStopped, Root: "/b", RootExists: true, StateDir: "/b/.git/ods-stack-frontend",
			Since: now.Add(-50 * time.Hour), Errors: []string{"parse state.json"}},
		{Status: devstack.StatusStaleLease, Root: "/very/deep/path/to/c"},
	}
	var out strings.Builder
	printStackRows(&out, rows, now)
	for _, want := range []string{"~/…/.worktrees/a [feat]", "2/2", "http://localhost:3004", "2h", "2d", "b-1 (frontend)", "(not a worktree)", "error: parse state.json", "/…/to/c"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("output lacks %q:\n%s", want, out.String())
		}
	}
	for since, want := range map[time.Duration]string{30 * time.Second: "30s", 5 * time.Minute: "5m"} {
		if got := formatAge(now.Add(-since), now); got != want {
			t.Errorf("formatAge(%s) = %s, want %s", since, got, want)
		}
	}
	if formatAge(time.Time{}, now) != "-" || displayRoot(devstack.StackRow{}) != "-" || shortenPath("/a/b") != "/a/b" {
		t.Error("empty values are not shown as -")
	}
}

func TestStackPruneRejectsANegativeIdle(t *testing.T) {
	stackLsEnv(t, "exit 0\n")
	if code, out := runStackCLI(t, "stack", "prune", "--idle", "-1h"); code != 1 || !strings.Contains(out, "--idle must not be negative") {
		t.Fatalf("prune --idle -1h exit %d:\n%s", code, out)
	}
}

func TestStackPruneIdleWithoutStacks(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "darwin" {
		t.Skip("finding coding agents is supported only on Linux and macOS")
	}
	stackLsEnv(t, "exit 0\n")
	if code, out := runStackCLI(t, "stack", "prune", "--idle", "1h", "--yes"); code != 0 || !strings.Contains(out, "No orphaned stacks and no stacks idle for 1h0m0s") {
		t.Fatalf("prune --idle 1h exit %d:\n%s", code, out)
	}
}

func TestLogProjectResultNamesEachStep(t *testing.T) {
	logger := log.StandardLogger()
	original := logger.Out
	t.Cleanup(func() { logger.SetOutput(original) })
	var logs strings.Builder
	logger.SetOutput(&logs)
	logProjectResult(&devstack.ProjectResult{Row: devstack.StackRow{Project: "a-1"}, StoppedServices: 2, RemovedVolumes: true, ReleasedLeases: 3, RemovedOwner: true})
	logProjectResult(&devstack.ProjectResult{Row: devstack.StackRow{Project: "b-1"}, ComposeDown: true})
	for _, want := range []string{"2 service(s) stopped, containers and volumes removed, 3 port lease(s) released, owner record removed", "0 service(s) stopped, containers removed"} {
		if !strings.Contains(logs.String(), want) {
			t.Fatalf("logs do not contain %q:\n%s", want, logs.String())
		}
	}
}
