package install

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
)

// --dev writes the dev overlay next to the mode's own files and stacks it
// last, so its published ports are what survives the compose merge.
func TestInstallDevOverlayStacksLast(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t))
	root := t.TempDir()

	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, // non-interactive default mode is Lite
		Dev:      true,
		Tag:      "v4.2.0",
		Dir:      root,
		NoWait:   true,
	})
	if err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	overlay := filepath.Join(root, "deployment", "docker-compose.dev.yml")
	if _, err := os.Stat(overlay); err != nil {
		t.Fatalf("dev overlay not written: %v", err)
	}

	m, err := state.Load(root)
	if err != nil || m == nil {
		t.Fatalf("manifest: %v, %v", m, err)
	}
	// Dev is an overlay, not a mode: lite stays recorded as the mode.
	if !m.Dev || m.Mode != state.ModeLite {
		t.Errorf("manifest = %+v, want dev with mode lite", m)
	}
	if _, ok := m.Files["deployment/docker-compose.dev.yml"]; !ok {
		t.Errorf("dev overlay not recorded as managed: %v", m.Files)
	}

	var up string
	for _, c := range runner.calls {
		if strings.Contains(argv(c), "up -d") {
			up = argv(c)
		}
	}
	if up == "" {
		t.Fatal("compose up never ran")
	}
	base := strings.Index(up, "-f docker-compose.yml")
	lite := strings.Index(up, "-f docker-compose.onyx-lite.yml")
	dev := strings.Index(up, "-f docker-compose.dev.yml")
	if base < 0 || lite < 0 || dev < 0 || base >= lite || lite >= dev {
		t.Errorf("dev overlay must come last in the -f list: %s", up)
	}

	if !strings.Contains(outBuf(deps).String(), "Dev overlay") {
		t.Errorf("published ports not called out:\n%s", outBuf(deps).String())
	}
}

// The dev overlay survives a rerun that doesn't repeat --dev (a rerun never
// changes the deployment's shape on its own), and the lifecycle verbs pick it
// up off disk the way they do the lite overlay.
func TestDevOverlayStaysOnRerunAndIsAutoDetected(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	installDeps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	if err := RunInstall(context.Background(), installDeps, Options{
		NoPrompt: true, Dev: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("install: %v\noutput:\n%s", err, outBuf(installDeps).String())
	}

	rerunRunner := &fakeRunner{handler: healthyDockerHandler}
	rerunDeps := testDeps(t, rerunRunner, notFoundServer(t))
	if err := RunInstall(context.Background(), rerunDeps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("rerun: %v\noutput:\n%s", err, outBuf(rerunDeps).String())
	}
	if _, err := os.Stat(filepath.Join(root, "deployment", "docker-compose.dev.yml")); err != nil {
		t.Fatalf("rerun dropped the dev overlay: %v", err)
	}
	m, err := state.Load(root)
	if err != nil || m == nil || !m.Dev {
		t.Fatalf("manifest = %+v (err %v), want dev preserved", m, err)
	}

	stopRunner := &fakeRunner{handler: healthyDockerHandler}
	stopDeps := testDeps(t, stopRunner, notFoundServer(t))
	if err := RunStop(context.Background(), stopDeps, Options{Dir: root}); err != nil {
		t.Fatalf("RunStop: %v\noutput:\n%s", err, outBuf(stopDeps).String())
	}
	var stop string
	for _, c := range stopRunner.calls {
		if strings.HasSuffix(argv(c), " stop") {
			stop = argv(c)
		}
	}
	if !strings.Contains(stop, "-f docker-compose.dev.yml") {
		t.Errorf("dev overlay not auto-detected by stop: %s", stop)
	}

	statusRunner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -a") {
			return dockercmd.Result{Stdout: "onyx-api_server-1\tonyxdotapp/onyx-backend:v4.2.0\tUp 2 hours (healthy)\t0.0.0.0:8080->8080/tcp\tapi_server\n"}, nil
		}
		return healthyDockerHandler(c)
	}}
	statusDeps := testDeps(t, statusRunner, notFoundServer(t))
	if err := RunStatus(context.Background(), statusDeps, Options{Dir: root}, true); err != nil {
		t.Fatalf("RunStatus: %v\noutput:\n%s", err, outBuf(statusDeps).String())
	}
	var st Status
	if err := json.Unmarshal(outBuf(statusDeps).Bytes(), &st); err != nil {
		t.Fatalf("status output is not JSON: %v\n%s", err, outBuf(statusDeps).String())
	}
	if !st.Dev {
		t.Errorf("status = %+v, want dev reported", st)
	}
}

// Prod runs the standalone compose file and keeps its services behind nginx;
// publishing them is refused before anything is written.
func TestInstallRejectsProdWithDev(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Prod: true, Dev: true, Dir: t.TempDir(), NoWait: true,
	})
	if err == nil || !strings.Contains(err.Error(), "--prod and --dev cannot be used together") {
		t.Fatalf("err = %v, want the prod/dev conflict refusal", err)
	}
}

// A prod deployment adopted with --dev is refused on the rerun path too,
// where the mode comes off disk rather than the flag.
func TestInstallRejectsDevOnExistingProdDeployment(t *testing.T) {
	root := prodFixture(t, "v4.2.0")
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Dev: true, Dir: root, NoWait: true, Force: true,
	})
	if err == nil || !strings.Contains(err.Error(), "--dev cannot be applied") {
		t.Fatalf("err = %v, want the prod deployment refusal", err)
	}
}
