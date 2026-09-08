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
	if err == nil || !strings.Contains(err.Error(), "--allow-downgrade") {
		t.Fatalf("err = %v, want downgrade refusal", err)
	}

	// Nothing changed.
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if Var(string(env), "IMAGE_TAG") != "v4.2.0" {
		t.Errorf("IMAGE_TAG modified by refused downgrade: %q", Var(string(env), "IMAGE_TAG"))
	}
}

func TestUpgradeDowngradeAllowedWithAllowDowngrade(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	deps := testDeps(t, runner, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.0.0", Dir: root, NoWait: true, AllowDowngrade: true,
	})
	if err != nil {
		t.Fatalf("RunUpgrade: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if Var(string(env), "IMAGE_TAG") != "v4.0.0" {
		t.Errorf("IMAGE_TAG = %q", Var(string(env), "IMAGE_TAG"))
	}
}

// Force alone no longer implies a downgrade: the two consents are separate,
// so a scripted rollback doesn't have to opt into overwriting edited files.
func TestUpgradeForceAloneDoesNotAllowDowngrade(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	deps := testDeps(t, runner, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.0.0", Dir: root, NoWait: true, Force: true,
	})
	if err == nil || !strings.Contains(err.Error(), "--allow-downgrade") {
		t.Fatalf("err = %v, want downgrade refusal despite --force", err)
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

// Installs created by install.sh never recorded HOST_PORT. Defaulting to
// 3000 would silently move a deployment that runs on another port, so the
// port is recovered from the containers that are still running.
func TestUpgradeRecoversUnrecordedPortFromContainers(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	// A legacy .env: no HOST_PORT line at all.
	envPath := filepath.Join(root, "deployment", ".env")
	env, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatal(err)
	}
	legacy := strings.ReplaceAll(string(env), "HOST_PORT=3000\n", "")
	if err := os.WriteFile(envPath, []byte(legacy), 0600); err != nil {
		t.Fatal(err)
	}

	running := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "{{.Ports}}") {
			return dockercmd.Result{Stdout: "0.0.0.0:3001->80/tcp, [::]:3001->80/tcp\n"}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, running, notFoundServer(t))
	if err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("RunUpgrade: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	got, _ := os.ReadFile(envPath)
	if p := Var(string(got), "HOST_PORT"); p != "3001" {
		t.Errorf("HOST_PORT = %q, want the observed 3001", p)
	}
	for _, c := range running.calls {
		if strings.Contains(argv(c), " up ") && c.Env["HOST_PORT"] != "3001" {
			t.Errorf("up ran with HOST_PORT=%q, want 3001", c.Env["HOST_PORT"])
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

func TestUpgradeRejectsUnknownVersion(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	deps := testDeps(t, runner, refServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v9.9.9", Dir: root, NoWait: true,
	})
	if err == nil || !strings.Contains(err.Error(), "not found") {
		t.Fatalf("err = %v, want unknown-version rejection", err)
	}
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if Var(string(env), "IMAGE_TAG") != "v4.0.0" {
		t.Error("rejected upgrade must not touch .env")
	}
}

func TestUpgradePullFailureRollsBackEnv(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	failPull := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), " pull") {
			return dockercmd.Result{}, errors.New("manifest for tag not found")
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, failPull, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	})
	if err == nil {
		t.Fatal("upgrade must fail when the pull fails")
	}
	// The deployment still runs the old version; .env and the manifest must
	// keep saying so.
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if got := Var(string(env), "IMAGE_TAG"); got != "v4.0.0" {
		t.Errorf("IMAGE_TAG = %q after failed pull, want the original v4.0.0", got)
	}
	m, merr := state.Load(root)
	if merr != nil || m == nil {
		t.Fatalf("manifest: %+v, %v", m, merr)
	}
	if m.InstalledTag != "v4.0.0" {
		t.Errorf("manifest tag = %q after failed pull, want v4.0.0", m.InstalledTag)
	}
}

// A failed start is not a failed pull: containers that came up are already on
// the new images, so .env stays on the target (reverting it would put the old
// version back over data the new one may have migrated). The manifest still
// records what was last deployed successfully, and the user is told both.
func TestUpgradeStartFailureKeepsTargetAndExplains(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	failUp := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "up -d") {
			return dockercmd.Result{}, errors.New("container onyx-index-1 is unhealthy")
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, failUp, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	})
	if err == nil {
		t.Fatal("upgrade must fail when the start fails")
	}

	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if got := Var(string(env), "IMAGE_TAG"); got != "v4.2.0" {
		t.Errorf("IMAGE_TAG = %q after a failed start, want the target v4.2.0 kept", got)
	}
	m, merr := state.Load(root)
	if merr != nil || m == nil {
		t.Fatalf("manifest: %+v, %v", m, merr)
	}
	if m.InstalledTag != "v4.0.0" {
		t.Errorf("manifest tag = %q, want the last version that actually started", m.InstalledTag)
	}
	out := outBuf(deps).String()
	for _, want := range []string{"Partially deployed", "deploy upgrade --tag v4.0.0"} {
		if !strings.Contains(out, want) {
			t.Errorf("output missing %q:\n%s", want, out)
		}
	}
}

// Everything that can fail on disk happens before .env is rewritten, so a
// refresh that fails leaves the deployment naming the version it is actually
// running — not one it never pulled.
func TestUpgradeConfigFailureLeavesVersionAlone(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	// A managed file the refresh cannot get at: reading it fails outright.
	readme := filepath.Join(root, "README.md")
	if err := os.Remove(readme); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(readme, 0755); err != nil {
		t.Fatal(err)
	}

	upgradeRunner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, upgradeRunner, rawServer(t, "# compose at v4.2.0\nname: onyx\n"))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	})
	if err == nil {
		t.Fatalf("upgrade must fail when a managed file can't be refreshed\noutput:\n%s", outBuf(deps).String())
	}

	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if got := Var(string(env), "IMAGE_TAG"); got != "v4.0.0" {
		t.Errorf("IMAGE_TAG = %q after a failed config refresh, want the running v4.0.0", got)
	}
	m, merr := state.Load(root)
	if merr != nil || m == nil {
		t.Fatalf("manifest: %+v, %v", m, merr)
	}
	if m.InstalledTag != "v4.0.0" {
		t.Errorf("manifest tag = %q after a failed config refresh, want v4.0.0", m.InstalledTag)
	}
	// Nothing should have been deployed either.
	for _, c := range upgradeRunner.calls {
		if line := argv(c); strings.Contains(line, " pull") || strings.Contains(line, "up -d") {
			t.Errorf("deployed despite the failure: %s", line)
		}
	}
}

// nginx resolves the upstreams named in its config once, at load. An upgrade
// replaces api_server with a container on a new address but leaves the proxy
// running, so without a reload nginx keeps answering 502 from the address the
// old container had.
func TestUpgradeReloadsProxyAfterRecreate(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	running := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -q") {
			return dockercmd.Result{Stdout: "abc\n"}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, running, notFoundServer(t))
	if err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("upgrade failed: %v", err)
	}

	up, reload := -1, -1
	for i, c := range running.calls {
		line := argv(c)
		switch {
		case strings.Contains(line, "up -d"):
			up = i
		case strings.Contains(line, "exec -T nginx nginx -s reload"):
			reload = i
		}
	}
	if reload < 0 {
		t.Fatal("upgrade must reload the proxy, or it keeps routing to the replaced containers")
	}
	if up < 0 {
		t.Fatal("expected an `up` call")
	}
	if reload < up {
		t.Errorf("reloaded the proxy at call %d, before `up` at %d — it must re-resolve after the containers move", reload, up)
	}
}

// A proxy that is not running holds no address to re-resolve, so there is
// nothing to reload and nothing to warn about.
func TestUpgradeSkipsProxyReloadWhenNotRunning(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	running := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		a := argv(c)
		if strings.HasSuffix(a, "ps -q "+proxyService) {
			return dockercmd.Result{Stdout: ""}, nil
		}
		if strings.Contains(a, "ps -q") {
			return dockercmd.Result{Stdout: "abc\n"}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, running, notFoundServer(t))
	if err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("upgrade failed: %v", err)
	}

	for _, c := range running.calls {
		if strings.Contains(argv(c), "exec -T "+proxyService) {
			t.Errorf("ran %q against a proxy that is not running", argv(c))
		}
	}
}

// A failed probe is not the same as an absent proxy: a running proxy could
// still be holding the replaced container's address, so the run must say the
// state is unknown rather than report a clean upgrade.
func TestUpgradeWarnsWhenProxyStateUnknown(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	running := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		a := argv(c)
		if strings.HasSuffix(a, "ps -q "+proxyService) {
			return dockercmd.Result{}, errors.New("docker daemon unreachable")
		}
		if strings.Contains(a, "ps -q") {
			return dockercmd.Result{Stdout: "abc\n"}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, running, notFoundServer(t))
	if err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("an unreadable proxy state must not fail the upgrade: %v", err)
	}

	if got := outBuf(deps).String(); !strings.Contains(got, "Could not tell whether "+proxyService) {
		t.Errorf("probe failure was swallowed; output was %q", got)
	}
	for _, c := range running.calls {
		if strings.Contains(argv(c), "nginx -s reload") {
			t.Error("reloaded a proxy whose state could not be read")
		}
	}
}

// nginx keeps its running workers when a reload would load a broken config, so
// the upgrade says so instead of reporting a reload that did not take effect.
func TestUpgradeDoesNotReloadProxyWithBrokenConfig(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	running := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		a := argv(c)
		if strings.Contains(a, "ps -q") {
			return dockercmd.Result{Stdout: "abc\n"}, nil
		}
		if strings.Contains(a, "nginx -t") {
			return dockercmd.Result{}, errors.New("nginx: configuration file test failed")
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, running, notFoundServer(t))
	if err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("a proxy that fails its config test must not fail the upgrade: %v", err)
	}

	for _, c := range running.calls {
		if strings.Contains(argv(c), "nginx -s reload") {
			t.Error("reloaded the proxy even though `nginx -t` failed")
		}
	}
}
