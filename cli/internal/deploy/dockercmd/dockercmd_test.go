package dockercmd

import (
	"context"
	"errors"
	"strings"
	"testing"
)

// fakeRunner records invocations and delegates results to handler.
type fakeRunner struct {
	calls   []Command
	handler func(c Command) (Result, error)
}

func (f *fakeRunner) Run(_ context.Context, c Command) (Result, error) {
	f.calls = append(f.calls, c)
	if f.handler != nil {
		return f.handler(c)
	}
	return Result{}, nil
}

func argv(c Command) string {
	return strings.Join(append([]string{c.Name}, c.Args...), " ")
}

func TestDockerCommandWithoutSudo(t *testing.T) {
	d := NewDocker(&fakeRunner{})
	cmd := d.Command(map[string]string{"IMAGE_TAG": "v1.0.0"}, "info")
	if got := argv(cmd); got != "docker info" {
		t.Fatalf("argv = %q", got)
	}
	if cmd.Env["IMAGE_TAG"] != "v1.0.0" {
		t.Fatalf("env not carried: %+v", cmd.Env)
	}
}

// TestSudoEnvAnchorArgv asserts the exact sudo argv form: env vars must ride
// as positional arguments to `env` so sudo's env_reset cannot strip them
// (mirrors install.sh's DOCKER_SUDO=(sudo env) workaround).
func TestSudoEnvAnchorArgv(t *testing.T) {
	d := NewDocker(&fakeRunner{})
	d.sudo = true
	cmd := d.Command(map[string]string{"IMAGE_TAG": "edge", "HOST_PORT": "3000"}, "compose", "up", "-d")
	want := "sudo env HOST_PORT=3000 IMAGE_TAG=edge docker compose up -d"
	if got := argv(cmd); got != want {
		t.Fatalf("argv = %q, want %q", got, want)
	}
	if len(cmd.Env) != 0 {
		t.Fatalf("sudo form must not rely on process env: %+v", cmd.Env)
	}
}

func TestDetectComposePrefersPlugin(t *testing.T) {
	r := &fakeRunner{handler: func(c Command) (Result, error) {
		if argv(c) == "docker compose version" {
			return Result{Stdout: "Docker Compose version v2.32.1"}, nil
		}
		return Result{}, errors.New("not found")
	}}
	c := DetectCompose(context.Background(), NewDocker(r))
	if c == nil || c.standalone {
		t.Fatalf("got %+v, want plugin compose", c)
	}
	if c.TypeName() != "plugin" {
		t.Fatalf("TypeName = %s", c.TypeName())
	}
}

func TestDetectComposeFallsBackToStandalone(t *testing.T) {
	r := &fakeRunner{handler: func(c Command) (Result, error) {
		if c.Name == "docker-compose" {
			return Result{Stdout: "docker-compose version 1.29.2"}, nil
		}
		return Result{}, errors.New("no plugin")
	}}
	c := DetectCompose(context.Background(), NewDocker(r))
	if c == nil || !c.standalone {
		t.Fatalf("got %+v, want standalone compose", c)
	}
}

func TestDetectComposeNeither(t *testing.T) {
	r := &fakeRunner{handler: func(Command) (Result, error) {
		return Result{}, errors.New("nope")
	}}
	if c := DetectCompose(context.Background(), NewDocker(r)); c != nil {
		t.Fatalf("got %+v, want nil", c)
	}
}

func TestComposeVersionParsesAndFallsBackToDev(t *testing.T) {
	r := &fakeRunner{handler: func(c Command) (Result, error) {
		return Result{Stdout: "Docker Compose version v2.24.5-desktop.1"}, nil
	}}
	c := &Compose{docker: NewDocker(r)}
	if v := c.Version(context.Background()); v != "2.24.5" {
		t.Fatalf("Version = %q", v)
	}

	r.handler = func(Command) (Result, error) { return Result{Stdout: "dev build"}, nil }
	if v := c.Version(context.Background()); v != "dev" {
		t.Fatalf("Version = %q, want dev", v)
	}
}

func TestComposeCommandStacksFilesInOrder(t *testing.T) {
	c := &Compose{docker: NewDocker(&fakeRunner{})}
	cmd := c.Command("/root/deployment",
		map[string]string{"HOST_PORT": "3000"},
		[]string{"docker-compose.yml", "docker-compose.onyx-lite.yml"},
		"up", "-d", "--wait", "--wait-timeout", "600")
	want := "docker compose -f docker-compose.yml -f docker-compose.onyx-lite.yml up -d --wait --wait-timeout 600"
	if got := argv(cmd); got != want {
		t.Fatalf("argv = %q, want %q", got, want)
	}
	if cmd.Dir != "/root/deployment" {
		t.Fatalf("dir = %q", cmd.Dir)
	}
}

func TestComposeCommandSudoStandalone(t *testing.T) {
	d := NewDocker(&fakeRunner{})
	d.sudo = true
	c := &Compose{docker: d, standalone: true}
	cmd := c.Command("/x", map[string]string{"IMAGE_TAG": "edge"}, []string{"docker-compose.yml"}, "stop")
	want := "sudo env IMAGE_TAG=edge docker-compose -f docker-compose.yml stop"
	if got := argv(cmd); got != want {
		t.Fatalf("argv = %q, want %q", got, want)
	}
}

func TestEnsureNetworkOnlyCreatesWhenMissing(t *testing.T) {
	r := &fakeRunner{handler: func(c Command) (Result, error) {
		if strings.Contains(argv(c), "inspect existing") {
			return Result{}, nil
		}
		if strings.Contains(argv(c), "inspect") {
			return Result{}, errors.New("no such network")
		}
		return Result{}, nil
	}}
	d := NewDocker(r)

	created, err := d.EnsureNetwork(context.Background(), "existing")
	if err != nil || created {
		t.Fatalf("existing network: created=%v err=%v", created, err)
	}

	created, err = d.EnsureNetwork(context.Background(), "missing")
	if err != nil || !created {
		t.Fatalf("missing network: created=%v err=%v", created, err)
	}
	last := argv(r.calls[len(r.calls)-1])
	if last != "docker network create missing" {
		t.Fatalf("last call = %q", last)
	}
}

func TestDockerVersionParse(t *testing.T) {
	r := &fakeRunner{handler: func(Command) (Result, error) {
		return Result{Stdout: "Docker version 27.4.0, build bde2b89"}, nil
	}}
	if v := NewDocker(r).Version(context.Background()); v != "27.4.0" {
		t.Fatalf("Version = %q", v)
	}
}
