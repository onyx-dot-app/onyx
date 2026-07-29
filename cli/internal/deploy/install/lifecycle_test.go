package install

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/charmbracelet/x/ansi"

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

// Markers are not authorization: a deployment/ under $HOME makes $HOME look
// like an install, and uninstall removes the root recursively.
func TestUninstallRefusesBroadRootWithMarkers(t *testing.T) {
	isolateEnv(t)
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	runner := &fakeRunner{handler: healthyDockerHandler}
	// A real deployment, but installed straight into the home directory.
	if err := os.MkdirAll(filepath.Join(home, "deployment"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, "deployment", ".env"), []byte("IMAGE_TAG=v4.0.0\n"), 0600); err != nil {
		t.Fatal(err)
	}
	keep := filepath.Join(home, "taxes.pdf")
	if err := os.WriteFile(keep, []byte("mine"), 0600); err != nil {
		t.Fatal(err)
	}

	deps := testDeps(t, runner, notFoundServer(t))
	err := RunUninstall(context.Background(), deps, Options{Dir: home, Force: true})
	if err == nil || !strings.Contains(err.Error(), "refusing to delete everything under") {
		t.Fatalf("err = %v, want a refusal", err)
	}
	if _, statErr := os.Stat(keep); statErr != nil {
		t.Fatal("refused uninstall deleted the home directory")
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

// The status list is read by eye, so a container that needs attention has to
// look different from one that doesn't.
func TestStatusColorsUnhealthyContainers(t *testing.T) {
	t.Setenv("TERM", "xterm-256color")
	t.Setenv("NO_COLOR", "")
	deps := testDeps(t, &fakeRunner{}, notFoundServer(t))
	deps.IOS.IsStdoutTTY = true
	in := newInstaller(deps, Options{})

	// The verdict and the state carry the color; the elapsed time stays out
	// of the way.
	up := "Up 2 hours (healthy)"
	cases := map[string]string{
		up:                                in.paint.Dim("Up 2 hours ") + in.paint.Ok("(healthy)"),
		"Up 2 hours":                      in.paint.Dim("Up 2 hours"),
		"Up 3 seconds (unhealthy)":        in.paint.Dim("Up 3 seconds ") + in.paint.Err("(unhealthy)"),
		"Exited (137) 1 minute ago":       in.paint.Err("Exited (137)") + in.paint.Dim(" 1 minute ago"),
		"Up 3 seconds (health: starting)": in.paint.Dim("Up 3 seconds ") + in.paint.Warn("(health: starting)"),
		// A container that keeps restarting is crash-looping, not starting.
		"Restarting (1) 2 seconds ago": in.paint.Err("Restarting (1)") + in.paint.Dim(" 2 seconds ago"),
		"Created":                      in.paint.Warn("Created"),
	}
	for status, want := range cases {
		if got := in.paintStatus(status); got != want {
			t.Errorf("paintStatus(%q) = %q, want %q", status, got, want)
		}
		if plain := ansi.Strip(in.paintStatus(status)); plain != status {
			t.Errorf("styling changed the text: %q became %q", status, plain)
		}
	}
	if in.paintStatus(up) == in.paintStatus("Up 3 seconds (unhealthy)") {
		t.Error("healthy and unhealthy containers render alike")
	}

	// Color isn't the only signal: the mark says the same thing to a pipe.
	marks := map[string]string{
		up:                         "✓",
		"Up 3 seconds (unhealthy)": "✗",
		"Exited (0) 1 minute ago":  "✗",
		"Created":                  "⚠",
	}
	for status, want := range marks {
		if got := severityOf(status).mark(); got != want {
			t.Errorf("mark for %q = %q, want %q", status, got, want)
		}
	}

	// Redirected output carries no escapes, so `deploy status > file` and the
	// tests below keep reading plain text.
	plain := newInstaller(testDeps(t, &fakeRunner{}, notFoundServer(t)), Options{})
	if got := plain.paintStatus("Up 3 seconds (unhealthy)"); got != "Up 3 seconds (unhealthy)" {
		t.Errorf("non-terminal status should stay plain, got %q", got)
	}
}

// A container that keeps dying is the worst state on the board and the one
// `docker ps` explains least: "Restarting" says nothing about how many times
// or why. Status has to supply both, and name the command that shows the rest.
func TestStatusExplainsCrashLoop(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	psOut := "onyx-nginx-1\tnginx:1.25.5-alpine\tUp 2 hours\t0.0.0.0:3000->80/tcp\tnginx\n" +
		"onyx-api_server-1\tonyxdotapp/onyx-backend:v4.2.0\tRestarting (255) 13 seconds ago\t\tapi_server\n"
	inspectOut := `{"name":"/onyx-api_server-1","restarts":18,"exit":255,"oom":false,"error":"","health":null}`
	statusRunner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		switch {
		case strings.Contains(argv(c), "ps -a"):
			return dockercmd.Result{Stdout: psOut}, nil
		case strings.Contains(argv(c), "inspect"):
			return dockercmd.Result{Stdout: inspectOut}, nil
		}
		return healthyDockerHandler(c)
	}}
	shimDockerOnPath(t)
	deps := testDeps(t, statusRunner, notFoundServer(t))
	err := RunStatus(context.Background(), deps, Options{Dir: root}, false)
	if err == nil || !strings.Contains(err.Error(), "partially stopped") {
		t.Fatalf("err = %v, want a degraded exit", err)
	}

	out := outBuf(deps).String()
	for _, want := range []string{
		"18 restarts",
		"api_server has restarted 18 times (exit 255)",
		"crash-looping",
		// The hint names the compose service, which is what logs takes, not
		// the container that happens to run it — and repeats the --dir this
		// run was given, so it works verbatim.
		"onyx-cli deploy logs --dir " + strconv.Quote(root) + " api_server\n",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("output missing %q:\n%s", want, out)
		}
	}

	// Only containers in trouble are inspected: a healthy one has nothing to
	// explain and shouldn't cost a round-trip.
	for _, c := range statusRunner.calls {
		if strings.Contains(argv(c), "inspect") && strings.Contains(argv(c), "nginx") {
			t.Errorf("healthy container inspected: %s", argv(c))
		}
	}
}

// A container compose created but never started is not running and not
// crash-looping. The verdict counts it either way, so the explanation under
// the verdict has to account for it too.
func TestStatusExplainsEveryContainerItCounted(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.2.0")

	psOut := "onyx-nginx-1\tnginx:1.25.5-alpine\tCreated\t\tnginx\n" +
		"onyx-api_server-1\tonyxdotapp/onyx-backend:v4.2.0\tUp 2 hours (healthy)\t\tapi_server\n" +
		"onyx-code-interpreter-1\tonyxdotapp/onyx-backend:v4.2.0\tExited (0) 6 seconds ago\t\tcode-interpreter\n"
	inspectOut := `{"name":"/onyx-nginx-1","restarts":0,"exit":0,"oom":false,"error":"","health":null}` + "\n" +
		`{"name":"/onyx-code-interpreter-1","restarts":0,"exit":0,"oom":false,"error":"","health":null}`
	statusRunner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		switch {
		case strings.Contains(argv(c), "ps -a"):
			return dockercmd.Result{Stdout: psOut}, nil
		case strings.Contains(argv(c), "inspect"):
			return dockercmd.Result{Stdout: inspectOut}, nil
		}
		return healthyDockerHandler(c)
	}}
	shimDockerOnPath(t)
	deps := testDeps(t, statusRunner, notFoundServer(t))
	if err := RunStatus(context.Background(), deps, Options{Dir: root}, false); err == nil {
		t.Fatal("expected a degraded exit")
	}

	out := outBuf(deps).String()
	for _, want := range []string{
		"2 of 3 containers are not running",
		"nginx was created but never started",
		"code-interpreter is not running (exit 0",
		"logs --dir " + strconv.Quote(root) + " nginx code-interpreter\n",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("output missing %q:\n%s", want, out)
		}
	}
	// The healthy service is neither counted nor explained.
	if strings.Contains(out, "api_server is") || strings.Contains(out, "logs api_server") {
		t.Errorf("healthy service dragged into the failure report:\n%s", out)
	}
}

// The hint is the one line in the report the reader is meant to act on, so
// the command carries the accent and the words around it don't.
func TestFailureHintHighlightsTheCommand(t *testing.T) {
	t.Setenv("TERM", "xterm-256color")
	t.Setenv("NO_COLOR", "")
	deps := testDeps(t, &fakeRunner{}, notFoundServer(t))
	deps.IOS.IsStdoutTTY = true
	in := newInstaller(deps, Options{})
	in.explainFailures([]Service{{
		Name:      "onyx-api_server-1",
		Service:   "api_server",
		Status:    "Restarting (255) 13 seconds ago",
		Diagnosis: "is crash-looping",
	}}, notRunning)

	out := outBuf(deps).String()
	if !strings.Contains(out, in.paint.Accent("onyx-cli deploy logs api_server")) {
		t.Errorf("the command to run isn't highlighted:\n%q", out)
	}
	if strings.Contains(out, in.paint.Accent("See why")) {
		t.Errorf("the label is highlighted too, so nothing stands out:\n%q", out)
	}
	if plain := ansi.Strip(out); !strings.Contains(plain, "See why: onyx-cli deploy logs api_server\n") {
		t.Errorf("styling changed the text:\n%q", plain)
	}
}

// The reason `deploy logs` exists: triage shouldn't begin with finding the
// deployment directory and remembering which overlays it was installed with.
func TestLogsRunsAgainstTheDetectedOverlays(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0") // lite install: overlay on disk

	logRunner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, logRunner, notFoundServer(t))
	logOpts := LogOptions{Services: []string{"api_server"}, Tail: "200"}
	if err := RunLogs(context.Background(), deps, Options{Dir: root}, logOpts); err != nil {
		t.Fatalf("RunLogs: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	var logs string
	for _, c := range logRunner.calls {
		if strings.Contains(argv(c), " logs") {
			logs = argv(c)
		}
	}
	if logs == "" {
		t.Fatal("compose logs never ran")
	}
	for _, want := range []string{"-f docker-compose.onyx-lite.yml", "logs --tail 200 api_server"} {
		if !strings.Contains(logs, want) {
			t.Errorf("compose logs missing %q: %s", want, logs)
		}
	}
}

func TestLogsWithoutAnInstall(t *testing.T) {
	isolateEnv(t)
	deps := testDeps(t, &fakeRunner{}, notFoundServer(t))
	err := RunLogs(context.Background(), deps, Options{Dir: filepath.Join(t.TempDir(), "none")}, LogOptions{})
	if err == nil || !strings.Contains(err.Error(), "not installed") {
		t.Fatalf("err = %v", err)
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
