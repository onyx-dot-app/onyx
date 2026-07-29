package install

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

func TestStopNothingInstalled(t *testing.T) {
	isolateEnv(t)
	deps := testDeps(t, &fakeRunner{}, notFoundServer(t))
	err := RunStop(context.Background(), deps, Options{Dir: filepath.Join(t.TempDir(), "none")})
	if err != nil {
		t.Fatalf("stop on nothing must be a no-op success: %v", err)
	}
	if !strings.Contains(outBuf(deps).String(), "Nothing to shut down") {
		t.Errorf("output:\n%s", outBuf(deps).String())
	}
}

func TestStopAutoDetectsOverlays(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0") // lite install: overlay on disk

	stopRunner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, stopRunner, notFoundServer(t))
	if err := RunStop(context.Background(), deps, Options{Dir: root}); err != nil {
		t.Fatalf("RunStop: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	var stop string
	for _, c := range stopRunner.calls {
		if strings.HasSuffix(argv(c), " stop") {
			stop = argv(c)
		}
	}
	if stop == "" {
		t.Fatal("compose stop never ran")
	}
	if !strings.Contains(stop, "-f docker-compose.onyx-lite.yml") {
		t.Errorf("lite overlay not auto-detected: %s", stop)
	}
}

func TestUninstallNonInteractiveRequiresForce(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	err := RunUninstall(context.Background(), deps, Options{Dir: root})
	if err == nil {
		t.Fatal("expected refusal without --force")
	}
	if _, statErr := os.Stat(root); statErr != nil {
		t.Fatal("refused uninstall must not delete anything")
	}
}

func TestUninstallForceRemovesEverything(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	unRunner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, unRunner, notFoundServer(t))
	if err := RunUninstall(context.Background(), deps, Options{Dir: root, Force: true}); err != nil {
		t.Fatalf("RunUninstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Error("install dir still exists")
	}
	var down string
	for _, c := range unRunner.calls {
		if strings.Contains(argv(c), "down -v") {
			down = argv(c)
		}
	}
	if down == "" {
		t.Fatal("compose down -v never ran")
	}
}

// --dir, ONYX_DEPLOYMENT_DIR and INSTALL_PREFIX name the deletion root
// freely, so a path that isn't recognizably an Onyx deployment must not be
// handed to RemoveAll.
func TestUninstallRefusesUnrecognizedDir(t *testing.T) {
	isolateEnv(t)
	root := t.TempDir()
	keep := filepath.Join(root, "someone-elses-data.txt")
	if err := os.WriteFile(keep, []byte("important"), 0600); err != nil {
		t.Fatal(err)
	}

	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	err := RunUninstall(context.Background(), deps, Options{Dir: root, Force: true})
	if err == nil || !strings.Contains(err.Error(), "doesn't look like an Onyx deployment") {
		t.Fatalf("err = %v, want a refusal", err)
	}
	if _, statErr := os.Stat(keep); statErr != nil {
		t.Fatal("refused uninstall deleted unrelated data")
	}
}

// Removing the directory after a failed teardown would strand the containers
// and volumes with nothing left describing them.
func TestUninstallKeepsFilesWhenTeardownFails(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	failDown := func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "down -v") {
			return dockercmd.Result{}, errors.New("permission denied while removing volume")
		}
		return healthyDockerHandler(c)
	}

	deps := testDeps(t, &fakeRunner{handler: failDown}, notFoundServer(t))
	deps.IOS = &iostreams.IOStreams{
		In:          strings.NewReader("DELETE\n"),
		Out:         &bytes.Buffer{},
		ErrOut:      &bytes.Buffer{},
		IsStdinTTY:  true,
		IsStdoutTTY: true,
	}
	err := RunUninstall(context.Background(), deps, Options{Dir: root, Force: false})
	if err == nil || !strings.Contains(err.Error(), "still present") {
		t.Fatalf("err = %v, want the teardown failure to stop the delete", err)
	}
	if _, statErr := os.Stat(root); statErr != nil {
		t.Fatal("deployment files were deleted despite the failed teardown")
	}

	// --force means "delete it regardless".
	deps2 := testDeps(t, &fakeRunner{handler: failDown}, notFoundServer(t))
	if err := RunUninstall(context.Background(), deps2, Options{Dir: root, Force: true}); err != nil {
		t.Fatalf("--force must delete anyway: %v\noutput:\n%s", err, outBuf(deps2).String())
	}
	if _, statErr := os.Stat(root); !os.IsNotExist(statErr) {
		t.Error("install dir still exists after --force")
	}
}

func TestUninstallTypedDeleteConfirmation(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	// Wrong confirmation text: cancelled, nothing removed.
	ios := &iostreams.IOStreams{
		In:          strings.NewReader("delete\n"),
		Out:         &bytes.Buffer{},
		ErrOut:      &bytes.Buffer{},
		IsStdinTTY:  true,
		IsStdoutTTY: true,
	}
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	deps.IOS = ios
	if err := RunUninstall(context.Background(), deps, Options{Dir: root}); err != nil {
		t.Fatalf("cancelled uninstall must not error: %v", err)
	}
	if _, err := os.Stat(root); err != nil {
		t.Fatal("cancelled uninstall deleted data")
	}

	// Exact DELETE: proceeds.
	ios2 := &iostreams.IOStreams{
		In:          strings.NewReader("DELETE\n"),
		Out:         &bytes.Buffer{},
		ErrOut:      &bytes.Buffer{},
		IsStdinTTY:  true,
		IsStdoutTTY: true,
	}
	deps2 := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	deps2.IOS = ios2
	if err := RunUninstall(context.Background(), deps2, Options{Dir: root}); err != nil {
		t.Fatalf("RunUninstall: %v", err)
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Error("install dir still exists after DELETE confirmation")
	}
}

func TestStatusNotInstalled(t *testing.T) {
	isolateEnv(t)
	deps := testDeps(t, &fakeRunner{}, notFoundServer(t))
	err := RunStatus(context.Background(), deps, Options{Dir: filepath.Join(t.TempDir(), "none")}, false)
	if err == nil || !strings.Contains(err.Error(), "not installed") {
		t.Fatalf("err = %v", err)
	}
}

func TestStatusHealthyAndDrift(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	// nginx (a stock image, listed first like the real deployment) must not
	// be mistaken for the running Onyx version.
	psOut := "onyx-nginx-1\tnginx:1.25.5-alpine\tUp 2 hours\t0.0.0.0:3000->80/tcp\n" +
		"onyx-api_server-1\tonyxdotapp/onyx-backend:v4.2.0\tUp 2 hours (healthy)\t\n"
	statusRunner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -a") {
			return dockercmd.Result{Stdout: psOut}, nil
		}
		return healthyDockerHandler(c)
	}}
	shimDockerOnPath(t)
	deps := testDeps(t, statusRunner, notFoundServer(t))
	if err := RunStatus(context.Background(), deps, Options{Dir: root}, false); err != nil {
		t.Fatalf("RunStatus: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	out := outBuf(deps).String()
	for _, want := range []string{"v4.2.0", "All 2 services are up", "http://localhost:3000"} {
		if !strings.Contains(out, want) {
			t.Errorf("output missing %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, "drift") {
		t.Errorf("false drift warning:\n%s", out)
	}

	// Running tag differs from .env/manifest: drift is flagged, exit degraded
	// only if unhealthy — here still healthy, so err stays nil.
	driftRunner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -a") {
			return dockercmd.Result{Stdout: strings.ReplaceAll(psOut, "v4.2.0", "v4.0.0")}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps2 := testDeps(t, driftRunner, notFoundServer(t))
	if err := RunStatus(context.Background(), deps2, Options{Dir: root}, false); err != nil {
		t.Fatalf("RunStatus: %v", err)
	}
	if !strings.Contains(outBuf(deps2).String(), "drift") {
		t.Errorf("drift not flagged:\n%s", outBuf(deps2).String())
	}
}

func TestStatusStoppedExitsNonZero(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	stopped := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -a") {
			return dockercmd.Result{Stdout: ""}, nil
		}
		return healthyDockerHandler(c)
	}}
	shimDockerOnPath(t)
	deps := testDeps(t, stopped, notFoundServer(t))
	err := RunStatus(context.Background(), deps, Options{Dir: root}, false)
	if err == nil || !strings.Contains(err.Error(), "stopped") {
		t.Fatalf("err = %v", err)
	}
}

func TestStatusJSON(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	psOut := "onyx-nginx-1\tnginx:1.25.5-alpine\tUp 1 minute\t0.0.0.0:3000->80/tcp\n" +
		"onyx-api_server-1\tonyxdotapp/onyx-backend:v4.2.0\tUp 1 minute (healthy)\t\n"
	statusRunner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -a") {
			return dockercmd.Result{Stdout: psOut}, nil
		}
		return healthyDockerHandler(c)
	}}
	shimDockerOnPath(t)
	deps := testDeps(t, statusRunner, notFoundServer(t))
	if err := RunStatus(context.Background(), deps, Options{Dir: root}, true); err != nil {
		t.Fatalf("RunStatus: %v\noutput:\n%s", err, outBuf(deps).String())
	}
	out := outBuf(deps).String()
	for _, want := range []string{`"installed": true`, `"env_tag": "v4.2.0"`, `"running_tag": "v4.2.0"`, `"access_url": "http://localhost:3000"`} {
		if !strings.Contains(out, want) {
			t.Errorf("JSON missing %q:\n%s", want, out)
		}
	}
}

func TestPublishedHostPort(t *testing.T) {
	cases := map[string]string{
		"0.0.0.0:3000->80/tcp, [::]:3000->80/tcp": "3000",
		"[::]:8080->80/tcp":                       "8080",
		"127.0.0.1:3001->80/tcp":                  "3001",
		"80/tcp":                                  "",
		"":                                        "",
	}
	for in, want := range cases {
		if got := publishedHostPort(in); got != want {
			t.Errorf("publishedHostPort(%q) = %q, want %q", in, got, want)
		}
	}
}
