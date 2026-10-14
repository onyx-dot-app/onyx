package cmd

import (
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

func TestRunDBDump_copiesTheDumpOutOfTheContainer(t *testing.T) {
	cases := []struct {
		name       string
		opts       DBDumpOptions
		wantPgDump []string
	}{
		{
			name:       "custom format with a schema",
			opts:       DBDumpOptions{Format: "custom", Schema: "public"},
			wantPgDump: []string{"pg_dump", "-U", "alice", "-d", "onyx", "-Fc", "-n", "public", "-f", "/tmp/onyx_dump_tmp"},
		},
		{
			name:       "plain SQL",
			opts:       DBDumpOptions{Format: "sql"},
			wantPgDump: []string{"pg_dump", "-U", "alice", "-d", "onyx", "-Fp", "-f", "/tmp/onyx_dump_tmp"},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := dbSetup(t)
			t.Setenv("POSTGRES_USER", "alice")
			t.Setenv("POSTGRES_PASSWORD", "s3cret")
			t.Setenv("POSTGRES_DB", "onyx")
			container, calls := dbFakeDocker(t, binDir, `if [ "$1" = cp ]; then printf 'dump-bytes' > "$3"; fi`)
			logs := dbCaptureLog(t)
			// The output directory does not exist yet.
			output := filepath.Join(t.TempDir(), "nested", "backup.out")
			opts := c.opts
			opts.Output = output

			if err := runDBDump(&opts); err != nil {
				t.Fatalf("runDBDump failed: %v", err)
			}

			dbAssertCalls(t, dbDockerExecs(calls()), [][]string{
				append([]string{"exec", "-i", "-e", "PGPASSWORD=s3cret", container}, c.wantPgDump...),
				{"cp", container + ":/tmp/onyx_dump_tmp", output},
				{"exec", "-i", container, "rm", "-f", "/tmp/onyx_dump_tmp"},
			})
			data, err := os.ReadFile(output)
			if err != nil {
				t.Fatalf("expected the dump at %s: %v", output, err)
			}
			if string(data) != "dump-bytes" {
				t.Fatalf("expected %q, got %q", "dump-bytes", data)
			}
			if !strings.Contains(logs.String(), "Dump completed successfully (10 B)") {
				t.Fatalf("expected the dump size in the log, got %q", logs.String())
			}
		})
	}
}

func TestRunDBDump_reportsFailures(t *testing.T) {
	cases := []struct {
		name      string
		behaviour string
		wantErr   string
		wantExecs int
		// wantCleanup says whether the dump left in the container is removed.
		wantCleanup bool
	}{
		{"pg_dump fails", `if [ "$1" = exec ]; then exit 2; fi`, "Failed to run pg_dump: exit status 2", 1, false},
		{"copy fails", `if [ "$1" = cp ]; then exit 4; fi`, "Failed to copy dump file: exit status 4", 3, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := dbSetup(t)
			container, calls := dbFakeDocker(t, binDir, c.behaviour)

			err := runDBDump(&DBDumpOptions{Format: "custom", Output: filepath.Join(t.TempDir(), "x.dump")})

			if err == nil || err.Error() != c.wantErr {
				t.Fatalf("expected %q, got %v", c.wantErr, err)
			}
			execs := dbDockerExecs(calls())
			if len(execs) != c.wantExecs {
				t.Fatalf("expected %d docker calls, got:\n%s", c.wantExecs, dbFormatCalls(execs))
			}
			if !c.wantCleanup {
				return
			}
			want := []string{"exec", "-i", container, "rm", "-f", "/tmp/onyx_dump_tmp"}
			if last := execs[len(execs)-1]; !slices.Equal(last, want) {
				t.Fatalf("expected the temporary dump to be removed, got %q", last)
			}
		})
	}
}

func TestRunDBDump_failsWhenTheOutputDirectoryCannotBeCreated(t *testing.T) {
	binDir := dbSetup(t)
	_, calls := dbFakeDocker(t, binDir, "")
	blocker := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(blocker, nil, 0o644); err != nil {
		t.Fatal(err)
	}

	err := runDBDump(&DBDumpOptions{Format: "custom", Output: filepath.Join(blocker, "sub", "x.dump")})

	if err == nil || !strings.HasPrefix(err.Error(), "Failed to create output directory: ") {
		t.Fatalf("expected an output directory error, got %v", err)
	}
	if execs := dbDockerExecs(calls()); len(execs) != 0 {
		t.Fatalf("expected pg_dump not to run, got:\n%s", dbFormatCalls(execs))
	}
}

func TestDetermineOutputPath(t *testing.T) {
	dbSetup(t)
	snapshots := paths.SnapshotsDir()

	cases := []struct {
		name   string
		output string
		format string
		want   string
	}{
		{"bare filename goes to the snapshots directory", "mine.dump", "custom", filepath.Join(snapshots, "mine.dump")},
		{"relative path is kept", filepath.Join("backups", "mine.sql"), "sql", filepath.Join("backups", "mine.sql")},
		{"absolute path is kept", "/var/backups/mine.dump", "custom", "/var/backups/mine.dump"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := determineOutputPath(c.output, c.format); got != c.want {
				t.Fatalf("expected %q, got %q", c.want, got)
			}
		})
	}

	t.Run("no output uses a timestamped name with the format extension", func(t *testing.T) {
		for format, ext := range map[string]string{"custom": `\.dump`, "sql": `\.sql`} {
			got := determineOutputPath("", format)
			if filepath.Dir(got) != snapshots {
				t.Fatalf("expected a path in %q, got %q", snapshots, got)
			}
			if !regexp.MustCompile(`^onyx_\d{8}_\d{6}` + ext + `$`).MatchString(filepath.Base(got)) {
				t.Fatalf("unexpected default name for %s: %q", format, filepath.Base(got))
			}
		}
	})
}

func TestHumanizeBytes(t *testing.T) {
	cases := []struct {
		bytes int64
		want  string
	}{
		{0, "0 B"},
		{1023, "1023 B"},
		{1024, "1.0 KB"},
		{1536, "1.5 KB"},
		{5 << 30, "5.0 GB"},
	}
	for _, c := range cases {
		if got := humanizeBytes(c.bytes); got != c.want {
			t.Fatalf("humanizeBytes(%d): expected %q, got %q", c.bytes, c.want, got)
		}
	}
}
