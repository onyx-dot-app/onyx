package cmd

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

// dbFakeAlembic sets up a repository whose venv holds a fake alembic that
// runs behaviour, and pins POSTGRES_HOST so alembic runs locally. It returns
// a function that reads the recorded alembic invocations.
func dbFakeAlembic(t *testing.T, behaviour string) func() [][]string {
	t.Helper()
	dbSetup(t)
	root, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("POSTGRES_HOST", "db.test")
	venvBin := filepath.Join(root, ".venv", "bin")
	if err := os.MkdirAll(venvBin, 0o755); err != nil {
		t.Fatal(err)
	}
	return dbFakeBinary(t, venvBin, "alembic", behaviour)
}

func TestDBMigrateCommands_runAlembicForTheSchema(t *testing.T) {
	cases := []struct {
		name     string
		run      func() error
		wantArgs []string
	}{
		{"upgrade", func() error { return runDBUpgrade("head", &MigrateOptions{Schema: "default"}) }, []string{"upgrade", "head"}},
		{"upgrade private", func() error { return runDBUpgrade("+1", &MigrateOptions{Schema: "private"}) }, []string{"-n", "schema_private", "upgrade", "+1"}},
		{"downgrade", func() error { return runDBDowngrade("-1", &MigrateOptions{Schema: ""}) }, []string{"downgrade", "-1"}},
		{"downgrade private", func() error { return runDBDowngrade("base", &MigrateOptions{Schema: "private"}) }, []string{"-n", "schema_private", "downgrade", "base"}},
		{"current private", func() error { return runDBCurrent(&MigrateOptions{Schema: "private"}) }, []string{"-n", "schema_private", "current"}},
		{"history verbose", func() error {
			return runDBHistory(&HistoryOptions{MigrateOptions: MigrateOptions{Schema: "default"}, Verbose: true})
		}, []string{"history", "-v"}},
		{"history private", func() error {
			return runDBHistory(&HistoryOptions{MigrateOptions: MigrateOptions{Schema: "private"}})
		}, []string{"-n", "schema_private", "history"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := dbFakeAlembic(t, "")

			if err := c.run(); err != nil {
				t.Fatalf("expected success, got %v", err)
			}

			dbAssertCalls(t, calls(), [][]string{c.wantArgs})
		})
	}
}

func TestDBMigrateCommands_rejectAnUnknownSchema(t *testing.T) {
	opts := &MigrateOptions{Schema: "public"}
	cases := []struct {
		name string
		run  func() error
	}{
		{"upgrade", func() error { return runDBUpgrade("head", opts) }},
		{"downgrade", func() error { return runDBDowngrade("-1", opts) }},
		{"current", func() error { return runDBCurrent(opts) }},
		{"history", func() error { return runDBHistory(&HistoryOptions{MigrateOptions: *opts}) }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := dbFakeAlembic(t, "")

			err := c.run()

			want := "Invalid schema: public (must be 'default' or 'private')"
			if err == nil || err.Error() != want {
				t.Fatalf("expected %q, got %v", want, err)
			}
			if got := calls(); len(got) != 0 {
				t.Fatalf("expected alembic not to run, got:\n%s", dbFormatCalls(got))
			}
		})
	}
}

func TestDBMigrateCommands_reportAlembicFailures(t *testing.T) {
	opts := &MigrateOptions{Schema: "default"}
	cases := []struct {
		name    string
		run     func() error
		wantErr string
	}{
		{"upgrade", func() error { return runDBUpgrade("head", opts) }, "Failed to upgrade database: exit status 2"},
		{"downgrade", func() error { return runDBDowngrade("-1", opts) }, "Failed to downgrade database: exit status 2"},
		{"current", func() error { return runDBCurrent(opts) }, "Failed to get current revision: exit status 2"},
		{"history", func() error { return runDBHistory(&HistoryOptions{MigrateOptions: *opts}) }, "Failed to get migration history: exit status 2"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			dbFakeAlembic(t, "exit 2")

			if err := c.run(); err == nil || err.Error() != c.wantErr {
				t.Fatalf("expected %q, got %v", c.wantErr, err)
			}
		})
	}
}

func TestDBMigrateRejectsConflictingProjectAndNetworkHost(t *testing.T) {
	calls := dbFakeAlembic(t, "")
	rootProject = "selected"
	err := runDBUpgrade("head", &MigrateOptions{})
	if err == nil || !strings.Contains(err.Error(), "--project conflicts with explicit POSTGRES_HOST") {
		t.Fatalf("expected network/project conflict, got %v", err)
	}
	if len(calls()) != 0 {
		t.Fatal("Alembic ran despite conflicting targets")
	}
}

func TestDBMigrateUsesSelectedProjectAndActualLeasedPort(t *testing.T) {
	calls := dbFakeAlembic(t, `printf '%s:%s' "$POSTGRES_HOST" "$POSTGRES_PORT" > "$0.endpoint"`)
	t.Setenv("POSTGRES_HOST", "")
	rootProject = "selected-data"
	_, dockerCalls := dbFakeDocker(t, os.Getenv("PATH"), `if [ "$1" = port ] && [ "$2" = selected-data-relational_db-1 ]; then echo 0.0.0.0:25432; fi`)
	if err := runDBUpgrade("head", &MigrateOptions{}); err != nil {
		t.Fatal(err)
	}
	root, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	endpoint, err := os.ReadFile(filepath.Join(root, ".venv", "bin", "alembic.endpoint"))
	if err != nil {
		t.Fatal(err)
	}
	if string(endpoint) != "localhost:25432" {
		t.Fatalf("wrong migration endpoint %s", endpoint)
	}
	dbAssertCalls(t, calls(), [][]string{{"upgrade", "head"}})
	for _, call := range dockerCalls() {
		line := strings.Join(call, " ")
		if strings.Contains(line, "onyx-relational_db") || len(dbDockerExecs([][]string{call})) > 0 {
			t.Fatalf("migration used an unselected container: %v", call)
		}
	}
}

func TestDBMigrateLoopbackCannotBypassManagedOwner(t *testing.T) {
	cases := []struct {
		name, host, port, filePort string
		saved, actual              int
	}{
		{"saved binding", "localhost", "25432", "", 25432, 0},
		{"discovered binding", "127.0.0.1", "25432", "", 15432, 25432},
		{"default port", "::1", "", "", 5432, 0},
		{"file binding", "localhost", "", "25432", 25432, 0},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := dbFakeAlembic(t, "")
			t.Setenv("POSTGRES_HOST", c.host)
			t.Setenv("POSTGRES_PORT", c.port)
			rootIsolated = false
			root, err := os.Getwd()
			if err != nil {
				t.Fatal(err)
			}
			if c.filePort != "" {
				if err := os.MkdirAll(filepath.Join(root, ".vscode"), 0755); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(root, ".vscode", ".env"), []byte("POSTGRES_PORT="+c.filePort+"\n"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			stack, err := devstack.Open(root, "shared-data", devstack.Shared)
			if err != nil {
				t.Fatal(err)
			}
			if err := stack.WriteState(&devstack.State{Root: t.TempDir(), Ports: map[string]int{"POSTGRES_HOST_PORT": c.saved}}); err != nil {
				t.Fatal(err)
			}
			dbFakeBinary(t, os.Getenv("PATH"), "docker", fmt.Sprintf(`if [ "$1" = port ] && [ "$2" = shared-data-relational_db-1 ] && [ %d -gt 0 ]; then echo 0.0.0.0:%d; else exit 1; fi`, c.actual, c.actual))
			err = runDBUpgrade("head", &MigrateOptions{})
			if err == nil || !strings.Contains(err.Error(), "managed by another checkout") {
				t.Fatalf("expected managed-owner refusal, got %v", err)
			}
			if len(calls()) != 0 {
				t.Fatal("loopback migration bypassed managed ownership")
			}
		})
	}
}

func TestDBMigrateRemoteIgnoresAmbiguousLocalDatasets(t *testing.T) {
	calls := dbFakeAlembic(t, "")
	rootIsolated = false
	root, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	first, err := devstack.Open(root, "legacy-a", devstack.Isolated)
	if err != nil {
		t.Fatal(err)
	}
	if err := first.WriteState(&devstack.State{}); err != nil {
		t.Fatal(err)
	}
	second := &devstack.Stack{Root: root, Project: "legacy-b", StateDir: filepath.Join(root, ".git", "worktrees", "other", "ods-stack")}
	if err := second.WriteState(&devstack.State{}); err != nil {
		t.Fatal(err)
	}
	dockerCalls := dbFakeBinary(t, os.Getenv("PATH"), "docker", "exit 1")
	if err := runDBUpgrade("head", &MigrateOptions{}); err != nil {
		t.Fatalf("explicit remote database depended on local datasets: %v", err)
	}
	dbAssertCalls(t, calls(), [][]string{{"upgrade", "head"}})
	if len(dockerCalls()) != 0 {
		t.Fatal("remote database triggered Docker discovery")
	}
	if _, err := os.Stat(filepath.Join(root, ".git", "ods-stack-shared", "lock")); !os.IsNotExist(err) {
		t.Fatal("remote migration acquired a local stack lock")
	}
}

func TestDBMigrateMatchingLoopbackHoldsProjectLock(t *testing.T) {
	dbFakeAlembic(t, "")
	t.Setenv("POSTGRES_HOST", "localhost")
	t.Setenv("POSTGRES_PORT", "25432")
	rootIsolated = false
	root, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	stack, err := devstack.Open(root, "shared-data", devstack.Shared)
	if err != nil {
		t.Fatal(err)
	}
	if err := stack.WriteState(&devstack.State{Ports: map[string]int{"POSTGRES_HOST_PORT": 25432}}); err != nil {
		t.Fatal(err)
	}
	dbFakeBinary(t, os.Getenv("PATH"), "docker", "exit 1")
	target, err := resolveDBMigrationTarget()
	if err != nil {
		t.Fatal(err)
	}
	release, err := lockDBMigrationTarget(target, true)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	otherRelease, err := stackForTarget(target).LockInfrastructure(context.Background(), 0)
	if err == nil {
		otherRelease()
		t.Fatal("matching loopback migration did not hold the project lock")
	}
	if !errors.Is(err, devstack.ErrLocked) {
		t.Fatalf("expected project lock contention, got %v", err)
	}
}

func TestDBMigrateUnrelatedLoopbackPortPreservesNetworkIntent(t *testing.T) {
	calls := dbFakeAlembic(t, "")
	t.Setenv("POSTGRES_HOST", "127.0.0.1")
	t.Setenv("POSTGRES_PORT", "35432")
	rootIsolated = false
	root, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	stack, err := devstack.Open(root, "shared-data", devstack.Shared)
	if err != nil {
		t.Fatal(err)
	}
	if err := stack.WriteState(&devstack.State{Root: t.TempDir(), Ports: map[string]int{"POSTGRES_HOST_PORT": 25432}}); err != nil {
		t.Fatal(err)
	}
	dbFakeBinary(t, os.Getenv("PATH"), "docker", "echo 0.0.0.0:25432")
	if err := runDBUpgrade("head", &MigrateOptions{}); err != nil {
		t.Fatalf("unrelated network endpoint inherited stack ownership: %v", err)
	}
	dbAssertCalls(t, calls(), [][]string{{"upgrade", "head"}})
}

func TestDBMigrateLoopbackRechecksNewManagedOwner(t *testing.T) {
	dbFakeAlembic(t, "")
	t.Setenv("POSTGRES_HOST", "localhost")
	t.Setenv("POSTGRES_PORT", "25432")
	rootIsolated = false
	target, err := resolveDBMigrationTarget()
	if err != nil {
		t.Fatal(err)
	}
	if target.Managed {
		t.Fatal("fixture already has a managed owner")
	}
	if err := stackForTarget(target).WriteState(&devstack.State{Root: t.TempDir(), Ports: map[string]int{"POSTGRES_HOST_PORT": 25432}}); err != nil {
		t.Fatal(err)
	}
	dbFakeBinary(t, os.Getenv("PATH"), "docker", "echo 0.0.0.0:25432")
	release, err := lockDBMigrationTarget(target, true)
	if err == nil {
		release()
		t.Fatal("loopback migration bypassed the new managed owner")
	}
	if !strings.Contains(err.Error(), "was claimed") {
		t.Fatalf("expected refreshed ownership refusal, got %v", err)
	}
}

func TestDBMigrateLoopbackLocksTheActualManagedProject(t *testing.T) {
	calls := dbFakeAlembic(t, "")
	t.Setenv("POSTGRES_HOST", "localhost")
	t.Setenv("POSTGRES_PORT", "25432")
	rootIsolated = false
	root, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	shared, err := devstack.Open(root, "shared-a", devstack.Shared)
	if err != nil {
		t.Fatal(err)
	}
	if err := shared.WriteState(&devstack.State{Ports: map[string]int{"POSTGRES_HOST_PORT": 15432}}); err != nil {
		t.Fatal(err)
	}
	other := &devstack.Stack{Root: t.TempDir(), Project: "isolated-b", StateDir: filepath.Join(root, ".git", "worktrees", "other", "ods-stack")}
	if err := other.WriteState(&devstack.State{Phase: devstack.PhaseReady, Ports: map[string]int{"POSTGRES_HOST_PORT": 25432}}); err != nil {
		t.Fatal(err)
	}
	dbFakeBinary(t, os.Getenv("PATH"), "docker", `case "$2" in shared-a-relational_db-1) echo 0.0.0.0:15432 ;; isolated-b-relational_db-1) echo 0.0.0.0:25432 ;; *) exit 1 ;; esac`)
	err = runDBUpgrade("head", &MigrateOptions{})
	if err == nil || !strings.Contains(err.Error(), "managed by another checkout") {
		t.Fatalf("cross-project migration accepted: %v", err)
	}
	if len(calls()) != 0 {
		t.Fatal("migration ran against another managed dataset")
	}
}

func TestDBMigrateRequiresStoppingManagedServices(t *testing.T) {
	calls := dbFakeAlembic(t, "")
	t.Setenv("POSTGRES_HOST", "localhost")
	t.Setenv("POSTGRES_PORT", "25432")
	rootIsolated = false
	root, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	stack, err := devstack.Open(root, "shared-data", devstack.Shared)
	if err != nil {
		t.Fatal(err)
	}
	state := &devstack.State{Phase: devstack.PhaseReady, Ports: map[string]int{"POSTGRES_HOST_PORT": 25432}, Services: []devstack.ServiceRecord{{Slug: "api", PID: 123, PGID: 123}}}
	if err := stack.WriteState(state); err != nil {
		t.Fatal(err)
	}
	dbFakeBinary(t, os.Getenv("PATH"), "docker", "echo 0.0.0.0:25432")
	err = runDBUpgrade("head", &MigrateOptions{})
	if err == nil || !strings.Contains(err.Error(), "stack stop") {
		t.Fatalf("manual migration accepted managed services: %v", err)
	}
	if len(calls()) != 0 {
		t.Fatal("manual migration ran before services stopped")
	}
	state.Services = nil
	state.Phase = devstack.PhaseStopped
	if err := stack.WriteState(state); err != nil {
		t.Fatal(err)
	}
	if err := runDBUpgrade("head", &MigrateOptions{}); err != nil {
		t.Fatalf("stopped stack cannot migrate: %v", err)
	}
}
