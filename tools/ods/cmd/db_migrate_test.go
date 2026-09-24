package cmd

import (
	"os"
	"path/filepath"
	"testing"
)

// dbFakeAlembic sets up a repository whose venv holds a fake alembic that
// runs behaviour, and pins POSTGRES_HOST so alembic runs locally. It returns
// a function that reads the recorded alembic invocations.
func dbFakeAlembic(t *testing.T, behaviour string) func() [][]string {
	t.Helper()
	gitPath := dbGitPath(t)
	binDir := dbSetup(t)
	root := dbFakeRepo(t, binDir, gitPath)
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
