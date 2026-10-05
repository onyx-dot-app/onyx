package cmd

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// dbWriteSnapshot writes a snapshot file with dummy content.
func dbWriteSnapshot(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("Failed to create %s: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte("snapshot"), 0o644); err != nil {
		t.Fatalf("Failed to write %s: %v", path, err)
	}
}

func TestRunDBRestore_picksTheToolFromTheExtension(t *testing.T) {
	cases := []struct {
		name        string
		file        string
		clean       bool
		wantRestore []string
	}{
		{"custom dump", "backup.dump", false, []string{"pg_restore", "-U", "alice", "-d", "onyx", "/tmp/onyx_restore_tmp"}},
		{"custom dump with clean", "backup.DUMP", true, []string{"pg_restore", "-U", "alice", "-d", "onyx", "--clean", "--if-exists", "/tmp/onyx_restore_tmp"}},
		// --clean only applies to pg_restore.
		{"plain SQL", "backup.sql", true, []string{"psql", "-U", "alice", "-d", "onyx", "-f", "/tmp/onyx_restore_tmp"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := dbSetup(t)
			t.Setenv("POSTGRES_USER", "alice")
			t.Setenv("POSTGRES_PASSWORD", "s3cret")
			t.Setenv("POSTGRES_DB", "onyx")
			container, calls := dbFakeDocker(t, binDir, "")
			input := filepath.Join(t.TempDir(), c.file)
			dbWriteSnapshot(t, input)

			if err := runDBRestore(input, &DBRestoreOptions{Yes: true, Clean: c.clean}); err != nil {
				t.Fatalf("runDBRestore failed: %v", err)
			}

			dbAssertCalls(t, dbDockerExecs(calls()), [][]string{
				{"cp", input, container + ":/tmp/onyx_restore_tmp"},
				append([]string{"exec", "-i", "-e", "PGPASSWORD=s3cret", container}, c.wantRestore...),
				{"exec", "-i", container, "rm", "-f", "/tmp/onyx_restore_tmp"},
			})
		})
	}
}

func TestRunDBRestore_toleratesPgRestoreWarnings(t *testing.T) {
	binDir := dbSetup(t)
	_, calls := dbFakeDocker(t, binDir, `if [ "$1" = exec ] && [ "$6" = pg_restore ]; then exit 1; fi`)
	logs := dbCaptureLog(t)
	input := filepath.Join(t.TempDir(), "backup.dump")
	dbWriteSnapshot(t, input)

	if err := runDBRestore(input, &DBRestoreOptions{Yes: true}); err != nil {
		t.Fatalf("expected pg_restore errors to be warnings, got %v", err)
	}

	if !strings.Contains(logs.String(), "pg_restore completed with warnings or errors: exit status 1") {
		t.Fatalf("expected a pg_restore warning, got %q", logs.String())
	}
	execs := dbDockerExecs(calls())
	if last := execs[len(execs)-1]; !slices.Contains(last, "rm") {
		t.Fatalf("expected the temporary file to be removed, got:\n%s", dbFormatCalls(execs))
	}
}

func TestRunDBRestore_reportsFailures(t *testing.T) {
	cases := []struct {
		name      string
		behaviour string
		wantErr   string
		wantExecs int
	}{
		{"copy fails", `if [ "$1" = cp ]; then exit 4; fi`, "Failed to copy file to container: exit status 4", 1},
		// The temporary file stays in the container for inspection.
		{"psql fails", `if [ "$1" = exec ] && [ "$6" = psql ]; then exit 3; fi`, "Failed to restore from SQL file: exit status 3", 2},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := dbSetup(t)
			_, calls := dbFakeDocker(t, binDir, c.behaviour)
			input := filepath.Join(t.TempDir(), "backup.sql")
			dbWriteSnapshot(t, input)

			err := runDBRestore(input, &DBRestoreOptions{Yes: true})

			if err == nil || err.Error() != c.wantErr {
				t.Fatalf("expected %q, got %v", c.wantErr, err)
			}
			if execs := dbDockerExecs(calls()); len(execs) != c.wantExecs {
				t.Fatalf("expected %d docker calls, got:\n%s", c.wantExecs, dbFormatCalls(execs))
			}
		})
	}
}

func TestRunDBRestore_failsBeforeDockerWhenTheInputIsMissing(t *testing.T) {
	binDir := dbSetup(t)
	_, calls := dbFakeDocker(t, binDir, "")
	t.Chdir(t.TempDir())

	err := runDBRestore("missing.dump", &DBRestoreOptions{Yes: true})

	want := "Input file not found: " + filepath.Join(paths.SnapshotsDir(), "missing.dump")
	if err == nil || err.Error() != want {
		t.Fatalf("expected %q, got %v", want, err)
	}
	if got := calls(); len(got) != 0 {
		t.Fatalf("expected no docker calls, got:\n%s", dbFormatCalls(got))
	}
}

func TestResolveInputPath(t *testing.T) {
	dbSetup(t)
	snapshots := paths.SnapshotsDir()
	cwd := t.TempDir()
	t.Chdir(cwd)
	dbWriteSnapshot(t, filepath.Join(snapshots, "both.dump"))
	dbWriteSnapshot(t, filepath.Join(cwd, "both.dump"))
	dbWriteSnapshot(t, filepath.Join(cwd, "local.sql"))

	cases := []struct {
		name  string
		input string
		want  string
	}{
		{"absolute path is kept", "/data/backup.dump", "/data/backup.dump"},
		{"path with a directory is kept", filepath.Join("data", "backup.dump"), filepath.Join("data", "backup.dump")},
		{"snapshots directory wins over the working directory", "both.dump", filepath.Join(snapshots, "both.dump")},
		{"file in the working directory becomes absolute", "local.sql", filepath.Join(cwd, "local.sql")},
		{"unknown file defaults to the snapshots directory", "nowhere.dump", filepath.Join(snapshots, "nowhere.dump")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := resolveInputPath(c.input); got != c.want {
				t.Fatalf("expected %q, got %q", c.want, got)
			}
		})
	}
}

func TestCompleteSnapshotFiles(t *testing.T) {
	dbSetup(t)
	snapshots := paths.SnapshotsDir()
	for _, name := range []string{"prod.dump", "prod.sql", "prod.txt", "staging.dump"} {
		dbWriteSnapshot(t, filepath.Join(snapshots, name))
	}
	if err := os.MkdirAll(filepath.Join(snapshots, "prod.dump.d"), 0o755); err != nil {
		t.Fatal(err)
	}

	t.Run("suggests matching dump and sql files", func(t *testing.T) {
		got, directive := completeSnapshotFiles(&cobra.Command{}, nil, "prod")

		slices.Sort(got)
		if want := []string{"prod.dump", "prod.sql"}; !slices.Equal(got, want) {
			t.Fatalf("expected %q, got %q", want, got)
		}
		if directive != cobra.ShellCompDirectiveDefault {
			t.Fatalf("expected file path completion to stay on, got %v", directive)
		}
	})

	t.Run("completes nothing after the input file", func(t *testing.T) {
		got, directive := completeSnapshotFiles(&cobra.Command{}, []string{"prod.dump"}, "")

		if got != nil || directive != cobra.ShellCompDirectiveNoFileComp {
			t.Fatalf("expected no completions, got %q with %v", got, directive)
		}
	})
}

func TestDBCommands_failWithoutAPostgresContainer(t *testing.T) {
	cases := []struct {
		name string
		run  func(t *testing.T) error
	}{
		{"drop", func(t *testing.T) error { return runDBDrop(&DBDropOptions{Yes: true}) }},
		{"dump", func(t *testing.T) error {
			return runDBDump(&DBDumpOptions{Format: "custom", Output: filepath.Join(t.TempDir(), "x.dump")})
		}},
		{"restore", func(t *testing.T) error {
			input := filepath.Join(t.TempDir(), "x.dump")
			dbWriteSnapshot(t, input)
			return runDBRestore(input, &DBRestoreOptions{Yes: true})
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := dbSetup(t)
			// No container is running and `docker ps` lists nothing.
			_, calls := dbFakeDocker(t, binDir, `if [ "$1" = inspect ]; then echo false; exit 0; fi`)

			err := c.run(t)

			if err == nil || !strings.HasPrefix(err.Error(), "Failed to find PostgreSQL container: no running PostgreSQL container found") {
				t.Fatalf("expected a missing container error, got %v", err)
			}
			if execs := dbDockerExecs(calls()); len(execs) != 0 {
				t.Fatalf("expected no docker exec or cp, got:\n%s", dbFormatCalls(execs))
			}
		})
	}
}
