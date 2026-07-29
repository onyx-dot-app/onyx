package install

import (
	"bytes"
	"context"
	"errors"
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

// notFoundServer 404s every download (exercising the embedded fallback) but
// answers ref-existence HEAD probes, so pinned test tags validate.
func notFoundServer(t *testing.T) *httptest.Server {
	t.Helper()
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodHead {
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(s.Close)
	return s
}

// refServer answers HEAD probes only for the given refs (plus main, which
// validation probes as its control) and 404s everything else: a healthy
// GitHub that simply doesn't have the requested version.
func refServer(t *testing.T, refs ...string) *httptest.Server {
	t.Helper()
	known := map[string]bool{"main": true}
	for _, r := range refs {
		known[r] = true
	}
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodHead {
			for ref := range known {
				if strings.Contains(r.URL.Path, "/"+ref+"/") {
					return
				}
			}
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(s.Close)
	return s
}

// blackholeServer 404s everything, HEAD probes included — the captive-portal
// / broken-proxy case, where no ref can be confirmed to exist.
func blackholeServer(t *testing.T) *httptest.Server {
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

// Quitting kills the compose command, which comes back as an error like any
// other. The run must not dress that up as a failure: nothing failed, and the
// output compose was in the middle of writing explains nothing.
func TestCancelledComposePhaseIsNotReportedAsFailure(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	in := newInstaller(deps, Options{Verbose: true})
	in.compose = dockercmd.DetectCompose(ctx, dockercmd.NewDocker(runner))
	runner.handler = func(dockercmd.Command) (dockercmd.Result, error) {
		cancel()
		return dockercmd.Result{}, errors.New("signal: killed")
	}

	err := in.runComposePhase(ctx, composePhase{title: "Starting services", dir: t.TempDir()})
	if err == nil {
		t.Fatal("a killed command must still surface as an error")
	}
	if out := outBuf(deps).String(); strings.Contains(out, "failed") {
		t.Errorf("cancelled phase reported a failure:\n%s", out)
	}
}

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

	// A floating tag moves under its own name, so nothing on the host can be
	// assumed current.
	for _, c := range runner.calls {
		if strings.Contains(argv(c), " pull") && strings.Contains(argv(c), "--policy") {
			t.Errorf("floating tag pull must not skip present images: %s", argv(c))
		}
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

	// A released tag is immutable, so images already on the host are taken as
	// final instead of being re-checked against the registry one by one.
	var pull string
	for _, c := range runner.calls {
		if strings.Contains(argv(c), " pull") {
			pull = argv(c)
		}
	}
	if !strings.Contains(pull, "--policy missing") {
		t.Errorf("pull argv = %q", pull)
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
	if !strings.Contains(err.Error(), "--force") || !strings.Contains(err.Error(), "onyx-cli deploy stop") {
		t.Errorf("guard error must carry both remedies: %v", err)
	}
}

// A rerun over a live deployment asks once. Restart and Upgrade both replace
// the running services, so the choice is the sign-off — a second "this
// restarts things, continue?" question would only ask it again.
func TestRerunAsksOnceAndCancels(t *testing.T) {
	seed := func(t *testing.T) (string, *fakeRunner) {
		t.Helper()
		isolateEnv(t)
		shimDockerOnPath(t)
		root := t.TempDir()
		if err := os.MkdirAll(filepath.Join(root, "deployment"), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, "deployment", ".env"), []byte("IMAGE_TAG=v1.0.0\n"), 0600); err != nil {
			t.Fatal(err)
		}
		return root, &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
			if strings.Contains(argv(c), "ps -q") {
				return dockercmd.Result{Stdout: "abc123\n"}, nil // containers up
			}
			return healthyDockerHandler(c)
		}}
	}
	interactive := func(deps Deps, answer string) Deps {
		deps.IOS = &iostreams.IOStreams{
			In:          strings.NewReader(answer + "\n"),
			Out:         &bytes.Buffer{},
			ErrOut:      &bytes.Buffer{},
			IsStdinTTY:  true,
			IsStdoutTTY: true,
		}
		return deps
	}

	// Cancel (option 3) leaves the deployment alone.
	root, runner := seed(t)
	deps := interactive(testDeps(t, runner, notFoundServer(t)), "3")
	err := RunInstall(context.Background(), deps, Options{Dir: root, NoWait: true, Local: true})
	if err == nil || !strings.Contains(err.Error(), "services left running") {
		t.Fatalf("err = %v, want the run cancelled with the services untouched", err)
	}
	for _, c := range runner.calls {
		if strings.Contains(argv(c), "up -d") || strings.Contains(argv(c), " pull") {
			t.Errorf("cancelled run still touched the deployment: %s", argv(c))
		}
	}

	// Restart (option 1) proceeds, having asked nothing else.
	root, runner = seed(t)
	deps = interactive(testDeps(t, runner, notFoundServer(t)), "1")
	if err := RunInstall(context.Background(), deps, Options{Dir: root, NoWait: true, Local: true}); err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	out := outBuf(deps).String()
	if n := strings.Count(out, "What would you like to do?"); n != 1 {
		t.Errorf("the rerun question was asked %d times:\n%s", n, out)
	}
	if strings.Contains(out, "Continue") {
		t.Errorf("restarting was confirmed twice:\n%s", out)
	}
	var up string
	for _, c := range runner.calls {
		if strings.Contains(argv(c), "up -d") {
			up = argv(c)
		}
	}
	if !strings.Contains(up, "--force-recreate") {
		t.Errorf("up must replace the running containers: %s", up)
	}
}

// A rerun over a running deployment never stops anything up front: the
// containers keep serving while the images download and `up --force-recreate`
// replaces them at the end.
func TestRerunForceRecreatesInsteadOfStopping(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
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

	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true,
		Force:    true,
		Dir:      root,
		Tag:      "v1.0.0",
		NoWait:   true,
		Local:    true,
	})
	if err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	var up string
	for _, c := range runner.calls {
		a := argv(c)
		if strings.Contains(a, "compose") && strings.HasSuffix(a, " stop") {
			t.Errorf("services were stopped: %s", a)
		}
		if strings.Contains(a, "up -d") {
			up = a
		}
	}
	if up == "" {
		t.Fatal("compose up never ran")
	}
	if !strings.Contains(up, "--force-recreate") {
		t.Errorf("up must recreate the running containers: %s", up)
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

// A dry run must run no commands and touch no disk, whether or not docker is
// around: with docker absent it must not need it, and with docker present it
// must not go probing it (a background preflight that outlives the command
// would make the promise a matter of timing).
func TestDryRunHasNoSideEffects(t *testing.T) {
	for _, tc := range []struct {
		name         string
		dockerOnPath bool
	}{
		{"docker absent", false},
		{"docker present", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			isolateEnv(t)
			if tc.dockerOnPath {
				shimDockerOnPath(t)
			}
			runner := &fakeRunner{handler: healthyDockerHandler}
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
		})
	}
}

func TestInstallRejectsUnknownVersion(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, refServer(t))
	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v9.9.9", Dir: root, NoWait: true,
	})
	if err == nil || !strings.Contains(err.Error(), "not found") {
		t.Fatalf("err = %v, want unknown-version rejection", err)
	}
	if _, statErr := os.Stat(filepath.Join(root, "deployment", ".env")); !os.IsNotExist(statErr) {
		t.Error("rejected install must not create .env")
	}
}

// A network that 404s everything (captive portal, broken proxy) must not be
// able to veto an install: verification is best-effort, so the run proceeds.
func TestInstallProceedsWhenExistenceCannotBeConfirmed(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, blackholeServer(t))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.0.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("unverifiable version must not block the install: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if got := Var(string(env), "IMAGE_TAG"); got != "v4.0.0" {
		t.Errorf("IMAGE_TAG = %q", got)
	}
}

// Image tags that aren't git refs (hand-built images, -dev twins) are
// pullable and must skip the repo lookup rather than be rejected.
func TestInstallAcceptsNonReleaseImageTag(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, refServer(t))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.0.0-dev", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("non-release image tag must be accepted: %v", err)
	}
}

func TestInstallAddsMissingVersionPrefix(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, refServer(t, "v4.0.0"))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Tag: "4.0.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if got := Var(string(env), "IMAGE_TAG"); got != "v4.0.0" {
		t.Errorf("IMAGE_TAG = %q, want the v-prefixed form", got)
	}
}

// A dry run writes nothing and pulls nothing, so it must not need GitHub.
func TestInstallDryRunStaysOffline(t *testing.T) {
	isolateEnv(t)
	raw := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Errorf("dry run made a network request: %s %s", r.Method, r.URL.Path)
		http.NotFound(w, r)
	}))
	t.Cleanup(raw.Close)
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, raw)
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, DryRun: true, Tag: "v4.0.0", Dir: t.TempDir(),
	}); err != nil {
		t.Fatalf("RunInstall: %v", err)
	}
}

func TestInstallPullFailureRemovesFreshEnv(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	failPull := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), " pull") {
			return dockercmd.Result{}, errors.New("manifest for tag not found")
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, failPull, notFoundServer(t))
	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.0.0", Dir: root, NoWait: true,
	})
	if err == nil {
		t.Fatal("install must fail when the pull fails")
	}
	// A version that never ran must not be recorded anywhere: no .env, and
	// no InstalledTag in the manifest.
	if _, statErr := os.Stat(filepath.Join(root, "deployment", ".env")); !os.IsNotExist(statErr) {
		t.Error("failed fresh install must not leave .env behind")
	}
	if m, _ := state.Load(root); m != nil && m.InstalledTag != "" {
		t.Errorf("manifest tag = %q after failed fresh install, want empty", m.InstalledTag)
	}
}

// Leaving lite mode has to undo lite's .env adjustments, or the "standard"
// deployment keeps storing files in Postgres and never starts MinIO.
func TestInstallRestoresStandardFileStoreWhenLeavingLite(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0") // lite

	// --include-craft implies standard mode on a rerun.
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, IncludeCraft: true, Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	env, err := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if err != nil {
		t.Fatal(err)
	}
	envStr := string(env)
	if got := Var(envStr, "COMPOSE_PROFILES"); got != "s3-filestore" {
		t.Errorf("COMPOSE_PROFILES = %q, want the standard s3-filestore", got)
	}
	if got := Var(envStr, "FILE_STORE_BACKEND"); got != "s3" {
		t.Errorf("FILE_STORE_BACKEND = %q, want s3", got)
	}
	if _, statErr := os.Stat(filepath.Join(root, "deployment", "docker-compose.onyx-lite.yml")); !os.IsNotExist(statErr) {
		t.Error("lite overlay still on disk after switching to standard")
	}
}

// COMPOSE_PROFILES is a list the CLI shares with the user: switching modes
// owns the s3-filestore entry and nothing else. Clearing the list would stop
// services the CLI never started, and it could not name them again on the way
// back.
func TestInstallModeSwitchKeepsUserProfiles(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0") // lite
	envPath := filepath.Join(root, "deployment", ".env")

	// Make it a standard deployment carrying a profile of the user's.
	env, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatal(err)
	}
	envStr := SetVar(string(env), "COMPOSE_PROFILES", "s3-filestore,my-monitoring")
	envStr = SetVar(envStr, "FILE_STORE_BACKEND", "s3")
	if err := os.WriteFile(envPath, []byte(envStr), 0600); err != nil {
		t.Fatal(err)
	}
	m, err := state.Load(root)
	if err != nil || m == nil {
		t.Fatalf("manifest: %+v, %v", m, err)
	}
	m.Mode = state.ModeStandard
	if err := m.Save(root); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(root, "deployment", "docker-compose.onyx-lite.yml")); err != nil {
		t.Fatal(err)
	}

	// Into lite: only the entry the CLI put there goes.
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Lite: true, Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("switch to lite: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	env, _ = os.ReadFile(envPath)
	if got := Var(string(env), "COMPOSE_PROFILES"); got != "my-monitoring" {
		t.Errorf("COMPOSE_PROFILES = %q in lite mode, want the user's profile kept", got)
	}

	// And back out: s3-filestore returns alongside it.
	deps = testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, IncludeCraft: true, Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("switch back to standard: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	env, _ = os.ReadFile(envPath)
	if got := Var(string(env), "COMPOSE_PROFILES"); got != "my-monitoring,s3-filestore" {
		t.Errorf("COMPOSE_PROFILES = %q leaving lite, want both profiles", got)
	}
}

// A file that a pinned ref simply doesn't carry must not take the rest of the
// deployment with it: the files that do exist at that ref still come from it.
func TestInstallMissingFileAtRefDoesNotDisableFetching(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	const upstream = "# compose at v4.2.0\nname: onyx\n"
	raw := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodHead {
			return
		}
		// The craft overlay is fetched before the nginx files but after the
		// compose file; only it is absent at this ref.
		if strings.HasSuffix(r.URL.Path, "docker-compose.craft.yml") {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(upstream))
	}))
	t.Cleanup(raw.Close)

	root := t.TempDir()
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, raw)
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, IncludeCraft: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	// Fetched after the missing overlay: still sourced from the ref.
	nginx, err := os.ReadFile(filepath.Join(root, "data", "nginx", "app.conf.template"))
	if err != nil {
		t.Fatal(err)
	}
	if string(nginx) != upstream {
		t.Errorf("nginx config fell back to embedded after an unrelated 404:\n%s", nginx)
	}
	craft, err := os.ReadFile(filepath.Join(root, "deployment", "docker-compose.craft.yml"))
	if err != nil {
		t.Fatal(err)
	}
	if string(craft) == upstream {
		t.Error("craft overlay should have come from the embedded copy")
	}
}
