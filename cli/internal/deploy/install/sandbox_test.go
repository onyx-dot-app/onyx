package install

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
)

func lastUp(t *testing.T, runner *fakeRunner) string {
	t.Helper()
	var up *dockercmd.Command
	for i := range runner.calls {
		if strings.Contains(argv(runner.calls[i]), "up -d") {
			up = &runner.calls[i]
		}
	}
	if up == nil {
		t.Fatal("compose up never ran")
	}
	return argv(*up)
}

func TestIncludeSandboxStacksTheOverlayAndRecordsIt(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := t.TempDir()
	deps := testDeps(t, runner, notFoundServer(t))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, IncludeSandbox: true, SandboxDockerRuntime: "runsc",
		Tag: "edge", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	if _, err := os.Stat(filepath.Join(root, "deployment", "docker-compose.sandbox.yml")); err != nil {
		t.Fatalf("sandbox overlay not written: %v", err)
	}
	if a := lastUp(t, runner); !strings.Contains(a, "-f docker-compose.sandbox.yml") ||
		strings.Contains(a, "docker-compose.onyx-lite.yml") {
		t.Errorf("up argv = %s, want the sandbox overlay on standard mode", a)
	}
	env, err := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if err != nil {
		t.Fatal(err)
	}
	if got := Var(string(env), "SANDBOX_DOCKER_RUNTIME"); got != "runsc" {
		t.Errorf("SANDBOX_DOCKER_RUNTIME = %q, want runsc", got)
	}
	m, err := state.Load(root)
	if err != nil || m == nil {
		t.Fatalf("manifest: %v, %v", m, err)
	}
	if !m.IncludeSandbox || m.Mode != state.ModeStandard {
		t.Errorf("manifest = %+v, want sandbox on standard mode", m)
	}
	var network, volume bool
	for _, c := range runner.calls {
		a := argv(c)
		network = network || strings.Contains(a, "network") && strings.Contains(a, "onyx_craft_sandbox")
		volume = volume || strings.Contains(a, "volume") && strings.Contains(a, "sandbox_proxy_ca")
	}
	if !network || !volume {
		t.Errorf("sandbox network/volume not ensured (network=%t volume=%t)", network, volume)
	}
	if out := outBuf(deps).String(); !strings.Contains(out, "docker.sock") {
		t.Errorf("no Docker socket warning:\n%s", out)
	}

	// A rerun without the flag keeps the overlay (the manifest records it).
	runner2 := &fakeRunner{handler: healthyDockerHandler}
	deps2 := testDeps(t, runner2, notFoundServer(t))
	if err := RunInstall(context.Background(), deps2, Options{NoPrompt: true, Dir: root, NoWait: true}); err != nil {
		t.Fatalf("rerun: %v\noutput:\n%s", err, outBuf(deps2).String())
	}
	if a := lastUp(t, runner2); !strings.Contains(a, "-f docker-compose.sandbox.yml") {
		t.Errorf("rerun dropped the sandbox overlay: %s", a)
	}
}

func TestDefaultInstallHasNoSandboxOverlay(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := t.TempDir()
	deps := testDeps(t, runner, notFoundServer(t))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, IncludeCraft: true, Tag: "edge", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	if a := lastUp(t, runner); strings.Contains(a, "docker-compose.sandbox.yml") {
		t.Errorf("sandbox overlay stacked without --include-sandbox: %s", a)
	}
	if _, err := os.Stat(filepath.Join(root, "deployment", "docker-compose.sandbox.yml")); !os.IsNotExist(err) {
		t.Errorf("sandbox overlay written without --include-sandbox: %v", err)
	}
}

func TestSandboxFlagConflicts(t *testing.T) {
	for name, opts := range map[string]Options{
		"lite":             {Lite: true, IncludeSandbox: true},
		"runtime-alone":    {SandboxDockerRuntime: "runsc"},
		"runtime-and-lite": {Lite: true, SandboxDockerRuntime: "runsc"},
	} {
		t.Run(name, func(t *testing.T) {
			isolateEnv(t)
			opts.NoPrompt, opts.Dir = true, t.TempDir()
			deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
			err := RunInstall(context.Background(), deps, opts)
			var coded *exitcodes.ExitError
			if !errors.As(err, &coded) || coded.Code != exitcodes.BadRequest {
				t.Fatalf("err = %v, want a bad-request error", err)
			}
		})
	}
}

func TestSandboxOverlayFollowsCraftInComposeFiles(t *testing.T) {
	in := &installer{craft: true, sandbox: true}
	got := strings.Join(in.managedComposeFiles(false), " ")
	if got != "docker-compose.yml docker-compose.craft.yml docker-compose.sandbox.yml" {
		t.Errorf("compose files = %q", got)
	}
	in = &installer{prod: true, sandbox: true}
	if got := strings.Join(in.managedComposeFiles(false), " "); got != "docker-compose.prod.yml docker-compose.sandbox.yml" {
		t.Errorf("prod compose files = %q", got)
	}
}
