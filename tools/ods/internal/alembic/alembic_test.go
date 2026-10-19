package alembic

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
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
		want, _ = filepath.EvalSymlinks(want)
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

func (f fixture) target() devstack.Target {
	return devstack.Target{Root: f.root, Project: "onyx", Mode: devstack.Isolated}
}

func TestRun_explicitNetworkHostNeverUsesDocker(t *testing.T) {
	f := newFixture(t)
	t.Setenv("POSTGRES_HOST", "db.test")
	t.Setenv("POSTGRES_PORT", "26432")
	t.Setenv("POSTGRES_USER", "alice")
	binary := f.venvAlembic(t, "")
	docker := f.docker(t, "exit 1")
	target := f.target()
	target.Ports = map[string]int{"POSTGRES_HOST_PORT": 25432}
	if err := Upgrade(target, "", SchemaPrivate); err != nil {
		t.Fatal(err)
	}
	assertLines(t, calls(t, binary), []string{"-n schema_private upgrade head"})
	if got := calls(t, docker); len(got) != 0 {
		t.Fatalf("network target selected Docker: %v", got)
	}
	env, err := os.ReadFile(binary + ".env")
	if err != nil {
		t.Fatal(err)
	}
	for _, value := range []string{"host=db.test\n", "port=26432\n", "user=alice\n", "password=password\n"} {
		if !strings.Contains(string(env), value) {
			t.Fatalf("missing %q in private runtime environment", value)
		}
	}
}

func TestRun_fileNetworkHostNeverUsesDocker(t *testing.T) {
	f := newFixture(t)
	binary := f.venvAlembic(t, "")
	docker := f.docker(t, "exit 1")
	if err := os.MkdirAll(filepath.Join(f.root, ".vscode"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(f.root, ".vscode", ".env"), []byte("POSTGRES_HOST=remote.example\nPOSTGRES_PORT=26432\nPOSTGRES_PASSWORD=file-secret\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := Current(f.target(), SchemaDefault); err != nil {
		t.Fatal(err)
	}
	if got := calls(t, docker); len(got) != 0 {
		t.Fatalf("file network target selected Docker: %v", got)
	}
	env, err := os.ReadFile(binary + ".env")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(env), "host=remote.example\n") || !strings.Contains(string(env), "port=26432\n") {
		t.Fatal("file network target was not preserved")
	}
}

func TestRun_fileLoopbackAliasesUseSelectedComposePort(t *testing.T) {
	for _, host := range []string{"localhost.", "LOCALHOST", "127.0.0.2", "127.255.255.254", "[::1]"} {
		t.Run(host, func(t *testing.T) {
			f := newFixture(t)
			binary := f.venvAlembic(t, "")
			docker := f.docker(t, `case "$1 $2 $4" in
"inspect -f selected-relational_db-1") echo true ;;
"port selected-relational_db-1 "*) echo 0.0.0.0:25432 ;;
*) exit 1 ;;
esac`)
			if err := os.MkdirAll(filepath.Join(f.root, ".vscode"), 0755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(f.root, ".vscode", ".env"), []byte("POSTGRES_HOST="+host+"\nPOSTGRES_PORT=15432\n"), 0600); err != nil {
				t.Fatal(err)
			}
			target := f.target()
			target.Project = "selected"
			if err := Current(target, SchemaDefault); err != nil {
				t.Fatal(err)
			}
			env, err := os.ReadFile(binary + ".env")
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(string(env), "host=localhost\n") || !strings.Contains(string(env), "port=25432\n") {
				t.Fatalf("loopback file bypassed selected Compose binding: %s", env)
			}
			if got := calls(t, docker); len(got) < 2 || !strings.Contains(strings.Join(got, "\n"), "selected-relational_db-1") {
				t.Fatalf("selected project not inspected: %v", got)
			}
		})
	}
}

func TestRun_commandArguments(t *testing.T) {
	cases := []struct {
		name string
		run  func(devstack.Target) error
		want string
	}{
		{"upgrade", func(target devstack.Target) error { return Upgrade(target, "abc123", SchemaDefault) }, "upgrade abc123"},
		{"downgrade", func(target devstack.Target) error { return Downgrade(target, "-1", SchemaDefault) }, "downgrade -1"},
		{"current", func(target devstack.Target) error { return Current(target, SchemaPrivate) }, "-n schema_private current"},
		{"history", func(target devstack.Target) error { return History(target, SchemaDefault, false) }, "history"},
		{"verbose", func(target devstack.Target) error { return History(target, SchemaPrivate, true) }, "-n schema_private history -v"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			f := newFixture(t)
			t.Setenv("POSTGRES_HOST", "db.test")
			binary := f.venvAlembic(t, "")
			if err := c.run(f.target()); err != nil {
				t.Fatal(err)
			}
			assertLines(t, calls(t, binary), []string{c.want})
		})
	}
}

func TestRun_returnsTheAlembicExitStatus(t *testing.T) {
	f := newFixture(t)
	t.Setenv("POSTGRES_HOST", "db.test")
	f.venvAlembic(t, "exit 4")
	err := Current(f.target(), SchemaDefault)
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 4 {
		t.Fatalf("expected exit 4, got %v", err)
	}
}

func TestRun_usesTheSelectedRootEvenOutsideTheCheckout(t *testing.T) {
	f := newFixture(t)
	t.Setenv("POSTGRES_HOST", "db.test")
	binary := f.venvAlembic(t, "")
	t.Chdir(t.TempDir())
	if err := Current(f.target(), SchemaDefault); err != nil {
		t.Fatal(err)
	}
	assertLines(t, calls(t, binary), []string{"current"})
}

func TestRun_withoutAlembic(t *testing.T) {
	f := newFixture(t)
	t.Setenv("POSTGRES_HOST", "db.test")
	if err := Current(f.target(), SchemaDefault); err == nil || !strings.Contains(err.Error(), "alembic not found") {
		t.Fatalf("expected missing binary error, got %v", err)
	}
}

func TestRun_usesTheActualLeasedPostgresPort(t *testing.T) {
	f := newFixture(t)
	binary := f.venvAlembic(t, "")
	f.docker(t, `case "$1" in
inspect) echo true ;;
port) echo 0.0.0.0:25432 ;;
esac`)
	if err := os.MkdirAll(filepath.Join(f.root, ".vscode"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(f.root, ".vscode", ".env"), []byte("POSTGRES_PORT=5432\nPOSTGRES_PASSWORD=file-secret\n"), 0600); err != nil {
		t.Fatal(err)
	}
	target := f.target()
	target.Ports = map[string]int{"POSTGRES_HOST_PORT": 15432}
	if err := Current(target, SchemaDefault); err != nil {
		t.Fatal(err)
	}
	env, err := os.ReadFile(binary + ".env")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(env), "port=25432\n") || !strings.Contains(string(env), "password=file-secret\n") {
		t.Fatal("leased port or file credentials were not passed to Alembic")
	}
	if target.Ports["POSTGRES_HOST_PORT"] != 15432 {
		t.Fatal("Run mutated its caller's target")
	}
}

func TestFindAlembicContainer_rejectsUnrelatedAPIContainers(t *testing.T) {
	f := newFixture(t)
	docker := f.docker(t, `case "$4" in api_server|onyx-stack-api_server-1) echo true ;; *) exit 1 ;; esac`)
	if container, err := findAlembicContainer("onyx"); err == nil {
		t.Fatalf("selected unrelated API container %q", container)
	}
	assertLines(t, calls(t, docker), []string{"inspect -f {{.State.Running}} onyx-api_server-1"})
}

func TestRun_viaSelectedDockerExecWhenPortIsHidden(t *testing.T) {
	f := newFixture(t)
	binary := f.venvAlembic(t, "")
	docker := f.docker(t, `case "$1 $4" in
"inspect selected-relational_db-1"|"inspect selected-api_server-1") echo true ;;
inspect*) echo false ;;
port*) exit 1 ;;
exec*) exit 6 ;;
esac`)
	target := f.target()
	target.Project = "selected"
	err := History(target, SchemaPrivate, true)
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 6 {
		t.Fatalf("expected Docker exit 6, got %v", err)
	}
	got := calls(t, docker)
	if !strings.Contains(got[len(got)-1], "selected-api_server-1 alembic -n schema_private history -v") {
		t.Fatalf("wrong Alembic target: %v", got)
	}
	if !strings.Contains(got[len(got)-1], "POSTGRES_HOST=selected-relational_db-1 -e POSTGRES_PORT=5432") {
		t.Fatalf("container fallback did not pin the selected database: %v", got)
	}
	if len(calls(t, binary)) != 0 {
		t.Fatal("local Alembic ran for a hidden port")
	}
}

func TestRun_missingSelectedDatabaseNeverUsesAnotherProject(t *testing.T) {
	f := newFixture(t)
	binary := f.venvAlembic(t, "")
	docker := f.docker(t, `case "$4" in onyx-relational_db-1|onyx-api_server-1) echo true ;; *) exit 1 ;; esac`)
	target := f.target()
	target.Project = "missing"
	if err := Upgrade(target, "head", SchemaDefault); err == nil {
		t.Fatal("missing project was accepted")
	}
	assertLines(t, calls(t, docker), []string{"inspect -f {{.State.Running}} missing-relational_db-1"})
	if len(calls(t, binary)) != 0 {
		t.Fatal("Alembic ran against an unknown endpoint")
	}
}
