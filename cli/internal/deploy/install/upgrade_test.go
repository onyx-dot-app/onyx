package install

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
)

// installFixture runs a real (fake-backed) fresh install and returns the root.
func installFixture(t *testing.T, runner *fakeRunner, tag string) string {
	t.Helper()
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	deps := testDeps(t, runner, notFoundServer(t))
	if err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Tag: tag, Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("fixture install: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	return root
}

func TestUpgradeRewritesOnlyImageTag(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	// Simulate user configuration between install and upgrade.
	envPath := filepath.Join(root, "deployment", ".env")
	env, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatal(err)
	}
	customized := string(env) + "GEN_AI_API_KEY=sk-user-added\n"
	if err := os.WriteFile(envPath, []byte(customized), 0600); err != nil {
		t.Fatal(err)
	}

	upstream := "# compose at v4.2.0\nname: onyx\n"
	deps := testDeps(t, runner, rawServer(t, upstream))
	err = RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	})
	if err != nil {
		t.Fatalf("RunUpgrade: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	got, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatal(err)
	}
	gotStr := string(got)
	if Var(gotStr, "IMAGE_TAG") != "v4.2.0" {
		t.Errorf("IMAGE_TAG = %q", Var(gotStr, "IMAGE_TAG"))
	}
	if !strings.Contains(gotStr, "GEN_AI_API_KEY=sk-user-added") {
		t.Error("user-added .env line lost on upgrade")
	}
	// Secrets generated at install must be untouched.
	if Var(gotStr, "USER_AUTH_SECRET") != Var(customized, "USER_AUTH_SECRET") {
		t.Error("USER_AUTH_SECRET changed on upgrade")
	}

	// Managed files refreshed to the target ref.
	compose, _ := os.ReadFile(filepath.Join(root, "deployment", "docker-compose.yml"))
	if string(compose) != upstream {
		t.Errorf("compose not refreshed: %q", compose)
	}

	m, err := state.Load(root)
	if err != nil || m == nil {
		t.Fatalf("manifest: %+v, %v", m, err)
	}
	if m.InstalledTag != "v4.2.0" {
		t.Errorf("manifest tag = %q", m.InstalledTag)
	}
	if m.Mode != state.ModeLite {
		t.Errorf("mode changed on upgrade: %q", m.Mode)
	}
}

func TestUpgradeRefusesDowngradeNonInteractively(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	deps := testDeps(t, runner, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.0.0", Dir: root, NoWait: true,
	})
	if err == nil || !strings.Contains(err.Error(), "--force") {
		t.Fatalf("err = %v, want downgrade refusal", err)
	}

	// Nothing changed.
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if Var(string(env), "IMAGE_TAG") != "v4.2.0" {
		t.Errorf("IMAGE_TAG modified by refused downgrade: %q", Var(string(env), "IMAGE_TAG"))
	}
}

func TestUpgradeDowngradeAllowedWithForce(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	deps := testDeps(t, runner, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.0.0", Dir: root, NoWait: true, Force: true,
	})
	if err != nil {
		t.Fatalf("RunUpgrade: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if Var(string(env), "IMAGE_TAG") != "v4.0.0" {
		t.Errorf("IMAGE_TAG = %q", Var(string(env), "IMAGE_TAG"))
	}
}

func TestUpgradeRequiresExistingInstall(t *testing.T) {
	isolateEnv(t)
	deps := testDeps(t, &fakeRunner{}, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: filepath.Join(t.TempDir(), "empty"),
	})
	if err == nil || !strings.Contains(err.Error(), "deploy install") {
		t.Fatalf("err = %v", err)
	}
}

func TestUpgradeRecreatesWithoutStopping(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	// Give the fixture a non-default recorded port, as a user might have.
	envPath := filepath.Join(root, "deployment", ".env")
	env, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(envPath, []byte(SetVar(string(env), "HOST_PORT", "8080")), 0600); err != nil {
		t.Fatal(err)
	}

	running := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -q") {
			return dockercmd.Result{Stdout: "abc\n"}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, running, notFoundServer(t))
	err = RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	})
	if err != nil {
		t.Fatalf("upgrade must proceed with services running: %v", err)
	}
	for _, c := range running.calls {
		if strings.HasSuffix(argv(c), " stop") {
			t.Error("upgrade must not stop services — up recreates them with less downtime")
		}
	}
	// The old stack keeps its port: no re-scan, the recorded value is reused.
	for _, c := range running.calls {
		if strings.Contains(argv(c), " up ") && c.Env["HOST_PORT"] != "8080" {
			t.Errorf("up ran with HOST_PORT=%q, want the recorded 8080", c.Env["HOST_PORT"])
		}
	}
}

func TestUpgradeDryRun(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")
	before, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))

	deps := testDeps(t, runner, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, DryRun: true,
	})
	if err != nil {
		t.Fatalf("RunUpgrade: %v", err)
	}
	if !strings.Contains(outBuf(deps).String(), "v4.0.0 → v4.2.0") {
		t.Errorf("output:\n%s", outBuf(deps).String())
	}
	after, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if string(before) != string(after) {
		t.Error("dry run modified .env")
	}
}
