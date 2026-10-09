package alembic

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// fixture is an isolated environment: a git repository named onyx as the
// working directory, and a PATH that holds only git and the fake binaries.
type fixture struct {
	root   string
	binDir string
}

func newFixture(t *testing.T) fixture {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake binaries are shell scripts")
	}
	gitPath, err := exec.LookPath("git")
	if err != nil {
		t.Skipf("git is not installed: %v", err)
	}
	for _, key := range []string{"POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"} {
		t.Setenv(key, "")
	}

	root := filepath.Join(t.TempDir(), "onyx")
	if err := os.MkdirAll(filepath.Join(root, "backend"), 0o755); err != nil {
		t.Fatal(err)
	}
	gittest.Git(t, root, "init", "--quiet")
	t.Chdir(root)

	binDir := t.TempDir()
	if err := os.Symlink(gitPath, filepath.Join(binDir, "git")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir)
	return fixture{root: root, binDir: binDir}
}

// writeScript writes an executable shell script to path. The script appends
// its argv as one line to path+".calls" before it runs body.
func writeScript(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	script := "#!/bin/sh\necho \"$*\" >> \"$0.calls\"\n" + body + "\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
}

// calls returns the recorded argv lines of the script at path.
func calls(t *testing.T, path string) []string {
	t.Helper()
	data, err := os.ReadFile(path + ".calls")
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

// venvAlembic installs a fake alembic in the repository venv. The script
// writes its working directory and POSTGRES_* values to path+".env".
func (f fixture) venvAlembic(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(f.root, ".venv", "bin", "alembic")
	writeScript(t, path, `printf 'dir=%s\nhost=%s\nport=%s\nuser=%s\npassword=%s\ndb=%s\n' "$(pwd -P)" "$POSTGRES_HOST" "$POSTGRES_PORT" "$POSTGRES_USER" "$POSTGRES_PASSWORD" "$POSTGRES_DB" > "$0.env"`+"\n"+body)
	return path
}

// docker installs a fake docker that runs body.
func (f fixture) docker(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(f.binDir, "docker")
	writeScript(t, path, body)
	return path
}

func assertLines(t *testing.T, got, want []string) {
	t.Helper()
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestFindAlembicBinary(t *testing.T) {
	t.Run("prefers the venv binary", func(t *testing.T) {
		f := newFixture(t)
		want := f.venvAlembic(t, "")
		writeScript(t, filepath.Join(f.binDir, "alembic"), "")

		got, err := FindAlembicBinary()

		if err != nil {
			t.Fatalf("FindAlembicBinary failed: %v", err)
		}
		if got != want {
			t.Fatalf("expected %q, got %q", want, got)
		}
	})

	t.Run("falls back to PATH", func(t *testing.T) {
		f := newFixture(t)
		want := filepath.Join(f.binDir, "alembic")
		writeScript(t, want, "")

		got, err := FindAlembicBinary()

		if err != nil {
			t.Fatalf("FindAlembicBinary failed: %v", err)
		}
		if got != want {
			t.Fatalf("expected %q, got %q", want, got)
		}
	})

	t.Run("explains how to install alembic", func(t *testing.T) {
		newFixture(t)

		_, err := FindAlembicBinary()

		want := "alembic not found. Ensure you have activated the venv or installed alembic globally"
		if err == nil || err.Error() != want {
			t.Fatalf("expected %q, got %v", want, err)
		}
	})
}

func TestRun_locallyWhenPostgresHostIsSet(t *testing.T) {
	f := newFixture(t)
	t.Setenv("POSTGRES_HOST", "db.test")
	t.Setenv("POSTGRES_USER", "alice")
	alembic := f.venvAlembic(t, "")
	docker := f.docker(t, "exit 1")

	if err := Upgrade("", SchemaPrivate); err != nil {
		t.Fatalf("Upgrade failed: %v", err)
	}

	assertLines(t, calls(t, alembic), []string{"-n schema_private upgrade head"})
	if got := calls(t, docker); got != nil {
		t.Fatalf("expected no docker calls with POSTGRES_HOST set, got %q", got)
	}
	backend, err := filepath.EvalSymlinks(filepath.Join(f.root, "backend"))
	if err != nil {
		t.Fatal(err)
	}
	env, err := os.ReadFile(alembic + ".env")
	if err != nil {
		t.Fatal(err)
	}
	// Unset variables get the postgres package defaults.
	assertLines(t, strings.Split(strings.TrimSpace(string(env)), "\n"), []string{
		"dir=" + backend,
		"host=db.test",
		"port=5432",
		"user=alice",
		"password=password",
		"db=postgres",
	})
}

func TestRun_commandArguments(t *testing.T) {
	cases := []struct {
		name string
		run  func() error
		want string
	}{
		{"upgrade to a revision", func() error { return Upgrade("abc123", SchemaDefault) }, "upgrade abc123"},
		{"downgrade", func() error { return Downgrade("-1", SchemaDefault) }, "downgrade -1"},
		{"current", func() error { return Current(SchemaPrivate) }, "-n schema_private current"},
		{"history", func() error { return History(SchemaDefault, false) }, "history"},
		{"verbose history", func() error { return History(SchemaDefault, true) }, "history -v"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			f := newFixture(t)
			t.Setenv("POSTGRES_HOST", "db.test")
			alembic := f.venvAlembic(t, "")

			if err := c.run(); err != nil {
				t.Fatalf("expected success, got %v", err)
			}

			assertLines(t, calls(t, alembic), []string{c.want})
		})
	}
}

func TestRun_returnsTheAlembicExitStatus(t *testing.T) {
	f := newFixture(t)
	t.Setenv("POSTGRES_HOST", "db.test")
	f.venvAlembic(t, "exit 4")

	err := Current(SchemaDefault)

	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 4 {
		t.Fatalf("expected exit status 4, got %v", err)
	}
}

func TestRun_locallyFailures(t *testing.T) {
	t.Run("outside a repository", func(t *testing.T) {
		f := newFixture(t)
		t.Setenv("POSTGRES_HOST", "db.test")
		writeScript(t, filepath.Join(f.binDir, "alembic"), "")
		outside := t.TempDir()
		t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(outside))
		t.Chdir(outside)

		err := Current(SchemaDefault)

		if err == nil || !strings.HasPrefix(err.Error(), "failed to find backend directory: ") {
			t.Fatalf("expected a backend directory error, got %v", err)
		}
	})

	t.Run("without alembic", func(t *testing.T) {
		newFixture(t)
		t.Setenv("POSTGRES_HOST", "db.test")

		err := Current(SchemaDefault)

		if err == nil || !strings.HasPrefix(err.Error(), "alembic not found") {
			t.Fatalf("expected an alembic not found error, got %v", err)
		}
	})
}

func TestRun_withoutPostgresHostRunsLocallyWhenThePortIsReachable(t *testing.T) {
	// Without a running project container, one lookup tries every known
	// container name and then docker ps.
	search := []string{
		"inspect -f {{.State.Running}} onyx-relational_db-1",
		"inspect -f {{.State.Running}} onyx_postgres",
		"inspect -f {{.State.Running}} onyx-relational_db-1",
		"inspect -f {{.State.Running}} onyx-stack-relational_db-1",
		"inspect -f {{.State.Running}} docker_compose-relational_db-1",
		"inspect -f {{.State.Running}} relational_db",
		"ps --format {{.Names}}\t{{.Image}}",
	}
	cases := []struct {
		name   string
		docker string
		want   []string
	}{
		{
			name: "exposed port",
			docker: `case "$1" in
inspect) echo true ;;
port) echo 0.0.0.0:5432 ;;
esac`,
			// shouldUseDockerExec and the host detection both look the port up.
			want: []string{
				"inspect -f {{.State.Running}} onyx-relational_db-1",
				"port onyx-relational_db-1 5432",
				"inspect -f {{.State.Running}} onyx-relational_db-1",
				"port onyx-relational_db-1 5432",
			},
		},
		{
			name: "no postgres container",
			docker: `case "$1" in
inspect) echo false ;;
esac`,
			// shouldUseDockerExec and the host detection both search.
			want: slices.Concat(search, search),
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			f := newFixture(t)
			alembic := f.venvAlembic(t, "")
			docker := f.docker(t, c.docker)

			if err := Current(SchemaDefault); err != nil {
				t.Fatalf("Current failed: %v", err)
			}

			assertLines(t, calls(t, alembic), []string{"current"})
			assertLines(t, calls(t, docker), c.want)
			for _, call := range calls(t, docker) {
				if strings.HasPrefix(call, "exec") {
					t.Fatalf("expected alembic to run locally, got docker %q", call)
				}
			}
			env, err := os.ReadFile(alembic + ".env")
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(string(env), "host=localhost\n") {
				t.Fatalf("expected POSTGRES_HOST=localhost, got:\n%s", env)
			}
		})
	}
}

func TestRun_viaDockerExecWhenThePortIsHidden(t *testing.T) {
	cases := []struct {
		name      string
		container string
	}{
		{"project container", "onyx-api_server-1"},
		{"legacy container", "api_server"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			f := newFixture(t)
			alembic := f.venvAlembic(t, "")
			docker := f.docker(t, `case "$1 $4" in
"inspect onyx-relational_db-1"|"inspect `+c.container+`") echo true ;;
inspect*) echo "Error: No such object" >&2; exit 1 ;;
port*) exit 1 ;;
exec*) exit 6 ;;
esac`)

			err := History(SchemaPrivate, true)

			var exitErr *exec.ExitError
			if !errors.As(err, &exitErr) || exitErr.ExitCode() != 6 {
				t.Fatalf("expected the docker exec status 6, got %v", err)
			}
			got := calls(t, docker)
			if want := "exec -i " + c.container + " alembic -n schema_private history -v"; got[len(got)-1] != want {
				t.Fatalf("expected %q last, got %q", want, got)
			}
			if got := calls(t, alembic); got != nil {
				t.Fatalf("expected the local alembic not to run, got %q", got)
			}
		})
	}
}

func TestRun_viaDockerExecWithoutAnAlembicContainer(t *testing.T) {
	f := newFixture(t)
	docker := f.docker(t, `case "$1 $4" in
"inspect onyx-relational_db-1") echo true ;;
inspect*) echo "Error: No such object" >&2; exit 1 ;;
port*) exit 1 ;;
esac`)

	err := Upgrade("head", SchemaDefault)

	if err == nil || err.Error() != "cannot connect to database" {
		t.Fatalf("expected %q, got %v", "cannot connect to database", err)
	}
	for _, call := range calls(t, docker) {
		if strings.HasPrefix(call, "exec") {
			t.Fatalf("expected no docker exec, got %q", call)
		}
	}
}
