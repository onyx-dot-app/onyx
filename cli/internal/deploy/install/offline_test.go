package install

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
)

// offlineDockerHandler answers like a healthy host that already holds images
// for two releases (and a floating tag, which names nothing reproducible).
func offlineDockerHandler(c dockercmd.Command) (dockercmd.Result, error) {
	if strings.Contains(argv(c), "images --format") {
		return dockercmd.Result{Stdout: "edge\nv4.4.6\nv4.2.0\n"}, nil
	}
	return healthyDockerHandler(c)
}

// A host with no route to GitHub can still install from images it already
// holds, so the version it is offered has to be one of those — not edge,
// whose whole meaning is "whatever the registry has today".
func TestOfflineInstallOffersAVersionOnTheHost(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: offlineDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t)) // release lookup 404s
	deps.IOS.IsStdinTTY, deps.IOS.IsStdoutTTY = true, true
	deps.IOS.In = bytes.NewBufferString(strings.Repeat("\n", 8)) // accept every default

	err := RunInstall(context.Background(), deps, Options{Dir: t.TempDir(), NoWait: true})
	if err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	out := outBuf(deps).String()
	if !strings.Contains(out, "Version to deploy [default: v4.4.6]") {
		t.Errorf("the version question didn't offer the newest release on the host:\n%s", out)
	}
	if !strings.Contains(out, "already on this host") {
		t.Errorf("output doesn't say why that version was offered:\n%s", out)
	}

	// The point of offering it: a released tag is a fixed image, so compose is
	// allowed to use the copy already here instead of going back to the
	// registry — which is what an offline install depends on.
	var pull, up string
	for _, c := range runner.calls {
		switch {
		case strings.Contains(argv(c), " pull"):
			pull = argv(c)
		case strings.Contains(argv(c), " up -d"):
			up = argv(c)
		}
	}
	if !strings.Contains(pull, "--policy missing") {
		t.Errorf("pull would contact the registry for images already here: %s", pull)
	}
	if strings.Contains(up, "--pull always") {
		t.Errorf("up forces a re-pull of images already here: %s", up)
	}
}

// With nothing installable on the host there is nothing better to offer, and
// the run must still reach the question rather than stopping at the lookup.
func TestOfflineInstallFallsBackToEdgeWithNoLocalImages(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "images --format") {
			return dockercmd.Result{Stdout: "edge\n"}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, runner, notFoundServer(t))
	deps.IOS.IsStdinTTY, deps.IOS.IsStdoutTTY = true, true
	deps.IOS.In = bytes.NewBufferString(strings.Repeat("\n", 8))

	if err := RunInstall(context.Background(), deps, Options{Dir: t.TempDir(), NoWait: true}); err != nil {
		t.Fatalf("RunInstall: %v", err)
	}
	if out := outBuf(deps).String(); !strings.Contains(out, "Version to deploy [default: edge]") {
		t.Errorf("expected the edge fallback to still be asked about:\n%s", out)
	}
}

// --offline is a promise, not a preference: no compose invocation in the run
// may be one that can reach a registry, whatever the tag turns out to be.
func TestOfflineInstallNeverReachesTheRegistry(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "config --images") {
			return dockercmd.Result{Stdout: "onyxdotapp/onyx-backend:v4.4.6\nonyxdotapp/code-interpreter:latest\n"}, nil
		}
		return offlineDockerHandler(c)
	}}
	// The release server would answer, and is still never asked.
	deps := testDeps(t, runner, rawServer(t, "fetched"))

	err := RunInstall(context.Background(), deps, Options{
		Dir: t.TempDir(), NoPrompt: true, NoWait: true, Offline: true,
	})
	if err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	var up string
	for _, c := range runner.calls {
		a := argv(c)
		if strings.Contains(a, " pull") {
			t.Errorf("--offline still pulled: %s", a)
		}
		if strings.Contains(a, " up -d") {
			up = a
		}
	}
	if !strings.Contains(up, "--pull never") {
		t.Errorf("up may still consult the registry: %s", up)
	}
	// Config files come from the embedded copies, so the fetch server that
	// would have answered is left alone.
	if out := outBuf(deps).String(); !strings.Contains(out, "v4.4.6") {
		t.Errorf("expected the host's own version to be deployed:\n%s", out)
	}
}

// The images a deployment needs don't all follow IMAGE_TAG, so having the
// version's own images is not the same as being able to start. Saying which
// one is absent is the whole difference between a fixable error and a puzzle.
func TestOfflineInstallNamesTheMissingImage(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	const missing = "onyxdotapp/code-interpreter:latest"
	runner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		a := argv(c)
		switch {
		case strings.Contains(a, "config --images"):
			return dockercmd.Result{Stdout: "onyxdotapp/onyx-backend:v4.4.6\n" + missing + "\n"}, nil
		case strings.Contains(a, "image inspect "+missing):
			return dockercmd.Result{}, errors.New("Error: No such image")
		}
		return offlineDockerHandler(c)
	}}
	deps := testDeps(t, runner, notFoundServer(t))

	err := RunInstall(context.Background(), deps, Options{
		Dir: t.TempDir(), NoPrompt: true, NoWait: true, Offline: true,
	})
	if err == nil {
		t.Fatal("expected the install to stop rather than start without an image")
	}
	if out := outBuf(deps).String() + deps.IOS.ErrOut.(*bytes.Buffer).String(); !strings.Contains(out, missing) {
		t.Errorf("the error doesn't say which image is missing:\n%s", out)
	}
	for _, c := range runner.calls {
		if strings.Contains(argv(c), " up -d") {
			t.Error("started services despite a missing image")
		}
	}
}

func TestLocalAppTagPicksTheNewestRelease(t *testing.T) {
	shimDockerOnPath(t)
	cases := map[string]string{
		"v4.2.0\nv4.4.6\nv4.10.0\n":  "v4.10.0", // ordered as versions, not text
		"edge\nlatest\nv4.4.6-dev\n": "",        // nothing reproducible on disk
		"":                           "",
		"v4.4.6\n":                   "v4.4.6",
	}
	for out, want := range cases {
		runner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
			if strings.Contains(argv(c), "images --format") {
				return dockercmd.Result{Stdout: out}, nil
			}
			return healthyDockerHandler(c)
		}}
		in := newInstaller(testDeps(t, runner, notFoundServer(t)), Options{})
		if got := in.localAppTag(context.Background()); got != want {
			t.Errorf("localAppTag(%q) = %q, want %q", out, got, want)
		}
	}
}
