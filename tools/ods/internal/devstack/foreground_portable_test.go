package devstack

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

func TestPortableForegroundChild(t *testing.T) {
	if os.Getenv("ODS_PORTABLE_CHILD") != "1" {
		return
	}
	input, _ := io.ReadAll(os.Stdin)
	_, _ = fmt.Fprintf(os.Stdout, "%s|%s|%s", input, os.Getenv("PORT"), os.Args[len(os.Args)-1])
	fmt.Fprint(os.Stderr, "child error")
	os.Exit(7)
}

func TestPortableForegroundUsesServiceSpecAndTerminalIO(t *testing.T) {
	root := t.TempDir()
	ports := map[string]int{"web": 3001}
	for _, service := range docker.InfraServices {
		for _, port := range service.Ports {
			ports[port.ComposeVar] = 12345
		}
	}
	launch := &Launch{Configurations: []LaunchConfig{{
		Name: "Web Server", Type: "node", Request: "launch", RuntimeExecutable: os.Args[0],
		RuntimeArgs: []string{"-test.run=^TestPortableForegroundChild$"},
		Cwd:         root, Env: map[string]string{"ODS_PORTABLE_CHILD": "1"},
	}}}
	var stdout, stderr bytes.Buffer
	prepared := false
	err := RunForegroundService(context.Background(), Target{Root: root, Ports: ports}, launch, "web", ServiceOptions{
		PreferredPort: 3050, Args: []string{"--", "two words"},
		IO: ServiceIO{Stdin: strings.NewReader("input"), Stdout: &stdout, Stderr: &stderr},
		BeforeStart: func(_ context.Context, sp Spec) error {
			prepared = true
			if sp.Port != 3050 || sp.Dir != root {
				t.Fatalf("spec = %+v", sp)
			}
			return nil
		},
	})
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 7 {
		t.Fatalf("exit = %v, want exit status 7", err)
	}
	if !prepared || stdout.String() != "input|3050|two words" || stderr.String() != "child error" {
		t.Fatalf("prepared=%v stdout=%q stderr=%q", prepared, stdout.String(), stderr.String())
	}
	if ports["web"] != 3001 {
		t.Fatal("foreground launch changed the caller's port state")
	}
}

func TestPortableForegroundCancellationPreventsPreparation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	prepared := false
	err := RunForegroundService(ctx, Target{Root: t.TempDir()}, &Launch{Configurations: []LaunchConfig{{
		Name: "Web Server", Type: "node", Request: "launch", RuntimeExecutable: os.Args[0],
	}}}, "web", ServiceOptions{BeforeStart: func(context.Context, Spec) error {
		prepared = true
		return nil
	}})
	if !errors.Is(err, context.Canceled) || prepared {
		t.Fatalf("err=%v prepared=%v", err, prepared)
	}
}
