package install

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/release"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

// fakeRunner scripts every external command RunInstall issues.
type fakeRunner struct {
	calls   []dockercmd.Command
	handler func(c dockercmd.Command) (dockercmd.Result, error)
}

func (f *fakeRunner) Run(_ context.Context, c dockercmd.Command) (dockercmd.Result, error) {
	f.calls = append(f.calls, c)
	if f.handler != nil {
		return f.handler(c)
	}
	return dockercmd.Result{}, nil
}

func argv(c dockercmd.Command) string {
	return strings.Join(append([]string{c.Name}, c.Args...), " ")
}

// healthyDockerHandler answers like a host with docker + compose plugin, a
// running daemon, and no Onyx containers.
func healthyDockerHandler(c dockercmd.Command) (dockercmd.Result, error) {
	a := argv(c)
	switch {
	case a == "docker compose version":
		return dockercmd.Result{Stdout: "Docker Compose version v2.32.0"}, nil
	case a == "docker --version":
		return dockercmd.Result{Stdout: "Docker version 27.4.0, build x"}, nil
	case a == "docker info":
		return dockercmd.Result{}, nil
	case a == "docker system info":
		return dockercmd.Result{Stdout: " Total Memory: 31.0GiB\n"}, nil
	case strings.Contains(a, "ps -q"):
		return dockercmd.Result{Stdout: ""}, nil
	}
	return dockercmd.Result{}, nil
}

// shimDockerOnPath makes exec.LookPath("docker") succeed without a real
// docker install (actual invocations are intercepted by fakeRunner).
func shimDockerOnPath(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	shim := filepath.Join(dir, "docker")
	if err := os.WriteFile(shim, []byte("#!/bin/sh\nexit 0\n"), 0755); err != nil {
		t.Fatalf("shim: %v", err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
}

// rawServer serves deployment files with recognizable fetched content.
func rawServer(t *testing.T, body string) *httptest.Server {
	t.Helper()
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(s.Close)
	return s
}

func notFoundServer(t *testing.T) *httptest.Server {
	t.Helper()
	s := httptest.NewServer(http.NotFoundHandler())
	t.Cleanup(s.Close)
	return s
}

func testDeps(t *testing.T, runner *fakeRunner, raw *httptest.Server) Deps {
	t.Helper()
	ios := &iostreams.IOStreams{
		In:     &bytes.Buffer{},
		Out:    &bytes.Buffer{},
		ErrOut: &bytes.Buffer{},
	}
	api := notFoundServer(t)
	return Deps{
		IOS:    ios,
		Runner: runner,
		Release: &release.Client{
			HTTP:       &http.Client{Timeout: 2 * time.Second},
			APIBase:    api.URL,
			RawBase:    raw.URL,
			RetryDelay: time.Millisecond,
		},
		CLIVersion: "test",
	}
}

func outBuf(d Deps) *bytes.Buffer { return d.IOS.Out.(*bytes.Buffer) }

func isolateEnv(t *testing.T) {
	t.Helper()
	t.Setenv("ONYX_DEPLOYMENT_DIR", "")
	t.Setenv("INSTALL_PREFIX", "")
	t.Setenv("SANDBOX_DOCKER_NETWORK", "")
}

func TestRunInstallFreshLiteNoPrompt(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t)) // offline: embedded fallback
	root := t.TempDir()

	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, // non-interactive default mode is Lite
		Tag:      "edge",
		Dir:      root,
		NoWait:   true,
	})
	if err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	// Files: base set + lite overlay from the embedded copies.
	for _, rel := range []string{
		"deployment/docker-compose.yml",
		"deployment/docker-compose.onyx-lite.yml",
		"deployment/env.template",
		"deployment/.env",
		"README.md",
		"data/nginx/app.conf.template",
		"data/nginx/run-nginx.sh",
	} {
		if _, err := os.Stat(filepath.Join(root, filepath.FromSlash(rel))); err != nil {
			t.Errorf("missing %s: %v", rel, err)
		}
	}

	// run-nginx.sh keeps its exec bit.
	info, err := os.Stat(filepath.Join(root, "data", "nginx", "run-nginx.sh"))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm()&0111 == 0 {
		t.Errorf("run-nginx.sh not executable: %v", info.Mode())
	}

	env, err := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if err != nil {
		t.Fatal(err)
	}
	envStr := string(env)
	if Var(envStr, "IMAGE_TAG") != "edge" {
		t.Errorf("IMAGE_TAG = %q", Var(envStr, "IMAGE_TAG"))
	}
	for _, key := range []string{"MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "S3_AWS_ACCESS_KEY_ID", "S3_AWS_SECRET_ACCESS_KEY"} {
		if v := Var(envStr, key); v == "minioadmin" || v == "" {
			t.Errorf("%s not randomized: %q", key, v)
		}
	}
	if len(Var(envStr, "USER_AUTH_SECRET")) != 64 {
		t.Errorf("USER_AUTH_SECRET not generated: %q", Var(envStr, "USER_AUTH_SECRET"))
	}
	if Var(envStr, "FILE_STORE_BACKEND") != "postgres" || Var(envStr, "COMPOSE_PROFILES") != "" {
		t.Error("lite .env adjustments missing")
	}

	m, err := state.Load(root)
	if err != nil || m == nil {
		t.Fatalf("manifest: %v, %v", m, err)
	}
	if m.InstalledTag != "edge" || m.Mode != state.ModeLite || m.IncludeCraft {
		t.Errorf("manifest = %+v", m)
	}
	if len(m.Files) < 6 {
		t.Errorf("manifest files = %v", m.Files)
	}

	// The up invocation: floating tag forces pull/recreate, lite overlay
	// stacked, --wait skipped (NoWait), env carried.
	var up *dockercmd.Command
	for i := range runner.calls {
		if strings.Contains(argv(runner.calls[i]), "up -d") {
			up = &runner.calls[i]
		}
	}
	if up == nil {
		t.Fatal("compose up never ran")
	}
	a := argv(*up)
	for _, want := range []string{
		"-f docker-compose.yml", "-f docker-compose.onyx-lite.yml",
		"--pull always", "--force-recreate",
	} {
		if !strings.Contains(a, want) {
			t.Errorf("up argv missing %q: %s", want, a)
		}
	}
	if strings.Contains(a, "--wait") {
		t.Errorf("--no-wait ignored: %s", a)
	}
	if up.Env["IMAGE_TAG"] != "edge" || up.Env["HOST_PORT"] == "" {
		t.Errorf("up env = %+v", up.Env)
	}
}

func TestRunInstallPinnedTagFetchesConfigs(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: healthyDockerHandler}
	fetched := "# fetched-from-tag\nname: onyx\n"
	deps := testDeps(t, runner, rawServer(t, fetched))
	root := t.TempDir()

	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true,
		Tag:      "v4.2.0",
		Dir:      root,
		NoWait:   true,
	})
	if err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	compose, err := os.ReadFile(filepath.Join(root, "deployment", "docker-compose.yml"))
	if err != nil {
		t.Fatal(err)
	}
	if string(compose) != fetched {
		t.Errorf("compose file not fetched from the pinned tag: %q", compose)
	}

	var up string
	for _, c := range runner.calls {
		if strings.Contains(argv(c), "up -d") {
			up = argv(c)
			if c.Env["IMAGE_TAG"] != "v4.2.0" {
				t.Errorf("up env = %+v", c.Env)
			}
		}
	}
	if up == "" {
		t.Fatal("compose up never ran")
	}
	if strings.Contains(up, "--force-recreate") {
		t.Errorf("pinned tag must not force-recreate: %s", up)
	}

	m, _ := state.Load(root)
	if m == nil || m.InstalledTag != "v4.2.0" {
		t.Fatalf("manifest = %+v", m)
	}
}

func TestRerunRefusesWhileRunning(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	// Seed an existing install.
	if err := os.MkdirAll(filepath.Join(root, "deployment"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "deployment", ".env"), []byte("IMAGE_TAG=v1.0.0\n"), 0600); err != nil {
		t.Fatal(err)
	}

	runner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -q") {
			return dockercmd.Result{Stdout: "abc123\n"}, nil // containers up
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, runner, notFoundServer(t))

	err := RunInstall(context.Background(), deps, Options{NoPrompt: true, Dir: root, Tag: "v1.0.0"})
	if err == nil {
		t.Fatal("expected refusal while services are running")
	}
	if !strings.Contains(err.Error(), "onyx-cli deploy stop") {
		t.Errorf("guard error must carry the remedy: %v", err)
	}
}

func TestRerunRestartKeepsEnvUntouched(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "deployment"), 0755); err != nil {
		t.Fatal(err)
	}
	seeded := "IMAGE_TAG=v1.0.0\nUSER_AUTH_SECRET=\"keepme\"\nCUSTOM_VAR=user-added\n"
	if err := os.WriteFile(filepath.Join(root, "deployment", ".env"), []byte(seeded), 0600); err != nil {
		t.Fatal(err)
	}

	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t))

	// No --tag: non-interactive rerun takes the restart branch.
	err := RunInstall(context.Background(), deps, Options{NoPrompt: true, Dir: root, NoWait: true, Local: true})
	if err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	env, err := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if err != nil {
		t.Fatal(err)
	}
	envStr := string(env)
	if Var(envStr, "IMAGE_TAG") != "v1.0.0" {
		t.Errorf("restart changed IMAGE_TAG: %q", envStr)
	}
	if !strings.Contains(envStr, `USER_AUTH_SECRET="keepme"`) || !strings.Contains(envStr, "CUSTOM_VAR=user-added") {
		t.Errorf("restart rewrote user config: %q", envStr)
	}

	// Restart must run compose with the existing pinned tag.
	for _, c := range runner.calls {
		if strings.Contains(argv(c), "up -d") && c.Env["IMAGE_TAG"] != "v1.0.0" {
			t.Errorf("up used tag %q", c.Env["IMAGE_TAG"])
		}
	}
}

func TestUserEditedFileKeptWithoutForce(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := t.TempDir()

	// First install writes the manifest baseline.
	deps := testDeps(t, runner, notFoundServer(t))
	if err := RunInstall(context.Background(), deps, Options{NoPrompt: true, Tag: "edge", Dir: root, NoWait: true}); err != nil {
		t.Fatalf("first install: %v", err)
	}

	// Hand-edit the compose file, then re-run (non-interactive, no --force):
	// the edit must survive and a warning must be printed.
	composePath := filepath.Join(root, "deployment", "docker-compose.yml")
	edited := "# my custom compose\nname: onyx\n"
	if err := os.WriteFile(composePath, []byte(edited), 0644); err != nil {
		t.Fatal(err)
	}

	deps2 := testDeps(t, runner, rawServer(t, "# upstream change\n"))
	if err := RunInstall(context.Background(), deps2, Options{NoPrompt: true, Dir: root, NoWait: true}); err != nil {
		t.Fatalf("re-run: %v\noutput:\n%s", err, outBuf(deps2).String())
	}

	got, err := os.ReadFile(composePath)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != edited {
		t.Errorf("hand-edited file was overwritten without --force")
	}
	if !strings.Contains(outBuf(deps2).String(), "differs from what the CLI last wrote") {
		t.Errorf("no user-edit warning printed:\n%s", outBuf(deps2).String())
	}
}

func TestUserEditedFileOverwrittenWithForceAndBackedUp(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := t.TempDir()

	deps := testDeps(t, runner, notFoundServer(t))
	if err := RunInstall(context.Background(), deps, Options{NoPrompt: true, Tag: "edge", Dir: root, NoWait: true}); err != nil {
		t.Fatalf("first install: %v", err)
	}

	composePath := filepath.Join(root, "deployment", "docker-compose.yml")
	if err := os.WriteFile(composePath, []byte("# my edit\n"), 0644); err != nil {
		t.Fatal(err)
	}

	upstream := "# upstream v2\nname: onyx\n"
	deps2 := testDeps(t, runner, rawServer(t, upstream))
	if err := RunInstall(context.Background(), deps2, Options{NoPrompt: true, Dir: root, NoWait: true, Force: true, Tag: "v9.0.0"}); err != nil {
		t.Fatalf("forced re-run: %v\noutput:\n%s", err, outBuf(deps2).String())
	}

	got, _ := os.ReadFile(composePath)
	if string(got) != upstream {
		t.Errorf("--force did not refresh the file: %q", got)
	}

	backups, err := filepath.Glob(composePath + ".bak-*")
	if err != nil || len(backups) == 0 {
		t.Fatalf("no backup created: %v %v", backups, err)
	}
	backup, _ := os.ReadFile(backups[0])
	if string(backup) != "# my edit\n" {
		t.Errorf("backup content = %q", backup)
	}
}

func TestDryRunHasNoSideEffects(t *testing.T) {
	isolateEnv(t)
	// No docker shim: dry-run must not even need docker.
	runner := &fakeRunner{}
	deps := testDeps(t, runner, notFoundServer(t))
	root := filepath.Join(t.TempDir(), "never-created")

	err := RunInstall(context.Background(), deps, Options{DryRun: true, Tag: "v1.0.0", Dir: root})
	if err != nil {
		t.Fatalf("RunInstall: %v", err)
	}
	if len(runner.calls) != 0 {
		t.Errorf("dry-run executed commands: %v", runner.calls)
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Error("dry-run created the install dir")
	}
	if !strings.Contains(outBuf(deps).String(), "Dry run complete") {
		t.Errorf("output:\n%s", outBuf(deps).String())
	}
}
