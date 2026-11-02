//go:build !windows

package cmd

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

const webRuntimeLaunch = `{"configurations":[
  {"name":"Web Server","type":"node","request":"launch","cwd":"${workspaceFolder}/web","runtimeExecutable":"bun","runtimeArgs":["run","dev"],"args":["--port","3000"]},
  {"name":"API Server","type":"node","request":"launch","cwd":"${workspaceFolder}/backend","runtimeExecutable":"/bin/sleep","runtimeArgs":["300"]}
]}`

func webRuntimeAPI(t *testing.T, healthy bool) (string, *devstack.Stack, string) {
	t.Helper()
	root, calls := stackTestRepo(t)
	writeFile(t, filepath.Join(root, ".vscode", "launch.json"), webRuntimeLaunch)
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if !healthy {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
	})}
	t.Cleanup(func() { _ = server.Close() })
	port := devtoolFreePort(t)
	owner, err := devstack.Open(root, "", devstack.Shared)
	if err != nil {
		t.Fatal(err)
	}
	owner.Registry = runtimeRegistry()
	launch, err := devstack.LoadLaunch(filepath.Join(root, ".vscode", "launch.json"))
	if err != nil {
		t.Fatal(err)
	}
	target, err := resolveRuntimeTarget()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- owner.RunService(ctx, target, launch, "api", devstack.ServiceOptions{
			PreferredPort: port, IO: devstack.ServiceIO{Stdout: io.Discard, Stderr: io.Discard}, StopTimeout: time.Second,
		})
	}()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("managed API did not stop")
		}
	})
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		select {
		case err := <-done:
			cancel()
			done <- err
			t.Fatalf("managed API startup: %v", err)
		default:
		}
		state, err := owner.ReadState()
		if err != nil {
			t.Fatal(err)
		}
		if state != nil && len(state.Services) == 1 && state.Services[0].PID > 0 {
			listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", state.Ports["api"]))
			if err != nil {
				t.Fatal(err)
			}
			go func() { _ = server.Serve(listener) }()
			return root, owner, calls["bun"]
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("managed API was not registered")
	return "", nil, ""
}

func TestWebRuntimePreviewPreservesAPIAndForwardsArguments(t *testing.T) {
	root, owner, calls := webRuntimeAPI(t, true)
	before := devtoolReadFile(t, filepath.Join(owner.StateDir, "state.json"))
	envPath := filepath.Join(root, "web.env")
	t.Setenv("ODS_WEB_ENV", envPath)
	devtoolFakeTool(t, os.Getenv("PATH"), "bun", "printf 'API=%s\\nPORT=%s\\n' \"$INTERNAL_URL\" \"$PORT\" > \"$ODS_WEB_ENV\"\n")
	webPort := devtoolFreePort(t)
	port := strconv.Itoa(webPort)
	if err := runWebDev([]string{"--port", port, "--hostname", "127.0.0.1"}); err != nil {
		t.Fatal(err)
	}
	want := []devtoolCall{
		{Dir: filepath.Join(root, "web"), Args: []string{"install", "--frozen-lockfile"}},
		{Dir: filepath.Join(root, "web"), Args: []string{"run", "dev", "--port", port, "--", "--hostname", "127.0.0.1"}},
	}
	if got := devtoolCalls(t, calls); !reflect.DeepEqual(got, want) {
		t.Fatalf("bun calls=%v, want %v", got, want)
	}
	state, err := owner.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	wantEnv := fmt.Sprintf("API=http://localhost:%d\nPORT=%s\n", state.Ports["api"], port)
	if got := devtoolReadFile(t, envPath); got != wantEnv {
		t.Fatalf("web environment=%q, want %q", got, wantEnv)
	}
	if after := devtoolReadFile(t, filepath.Join(owner.StateDir, "state.json")); after != before {
		t.Fatal("frontend preview changed the managed API state")
	}
	preview, err := devstack.Open(root, owner.Project, devstack.Frontend)
	if err != nil {
		t.Fatal(err)
	}
	previewState, err := preview.ReadState()
	if err != nil || previewState == nil || previewState.Ports["web"] != webPort || len(previewState.Services) != 1 || previewState.Services[0].PID != 0 {
		t.Fatalf("completed preview=%+v, err=%v", previewState, err)
	}
}

func TestWebRuntimeRejectsUnavailableAPIAndPreparationFailure(t *testing.T) {
	for _, scenario := range []string{"missing API", "unhealthy API", "install failure"} {
		t.Run(scenario, func(t *testing.T) {
			root, owner, calls := webRuntimeAPI(t, scenario != "unhealthy API")
			if scenario == "missing API" {
				state, err := owner.ReadState()
				if err != nil {
					t.Fatal(err)
				}
				state.Services = nil
				if err := owner.WriteState(state); err != nil {
					t.Fatal(err)
				}
			}
			before := devtoolReadFile(t, filepath.Join(owner.StateDir, "state.json"))
			want := "no healthy managed API"
			if scenario == "install failure" {
				devtoolFakeTool(t, os.Getenv("PATH"), "bun", "exit 23\n")
				want = "bun install --frozen-lockfile"
			}
			if err := runWebDev(nil); err == nil || !strings.Contains(err.Error(), want) {
				t.Fatalf("runWebDev error=%v, want %q", err, want)
			}
			if got := devtoolCalls(t, calls); scenario == "install failure" {
				if !reflect.DeepEqual(got, []devtoolCall{{Dir: filepath.Join(root, "web"), Args: []string{"install", "--frozen-lockfile"}}}) {
					t.Fatalf("preparation calls=%v", got)
				}
			} else if len(got) != 0 {
				t.Fatalf("unavailable API started frontend preparation: %v", got)
			}
			if got := devtoolReadFile(t, filepath.Join(owner.StateDir, "state.json")); got != before {
				t.Fatal("failed preview changed the API owner")
			}
		})
	}
}

func TestWebRuntimeUsesTheFullStackWebOwner(t *testing.T) {
	root, owner, calls := webRuntimeAPI(t, true)
	devtoolFakeTool(t, os.Getenv("PATH"), "bun", "printf 'managed-web-ready\\n'\nexec /bin/sleep 300\n")
	target, err := resolveRuntimeTarget()
	if err != nil {
		t.Fatal(err)
	}
	launch, err := devstack.LoadLaunch(filepath.Join(root, ".vscode", "launch.json"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	port := devtoolFreePort(t)
	go func() {
		done <- owner.RunService(ctx, target, launch, "web", devstack.ServiceOptions{
			PreferredPort: port, RequireAPI: true, StopTimeout: time.Second,
		})
	}()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("managed web did not stop")
		}
	})
	deadline := time.Now().Add(5 * time.Second)
	for {
		state, err := owner.ReadState()
		if err != nil {
			t.Fatal(err)
		}
		if state != nil && len(state.Services) == 2 {
			data, err := os.ReadFile(filepath.Join(owner.LogDir(), "web.log"))
			if err == nil && strings.Contains(string(data), "managed-web-ready") {
				break
			}
		}
		if time.Now().After(deadline) {
			t.Fatal("managed web was not registered")
		}
		time.Sleep(10 * time.Millisecond)
	}
	before, err := owner.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	if err := runWebDev([]string{"--hostname", "different-host"}); err == nil || !strings.Contains(err.Error(), "already runs with another configuration") {
		t.Fatalf("existing full-stack web configuration error=%v", err)
	}
	if got := devtoolCalls(t, calls); len(got) != 1 || !reflect.DeepEqual(got[0].Args, []string{"run", "dev", "--port", strconv.Itoa(port)}) {
		t.Fatalf("existing web was prepared or restarted: %v", got)
	}
	after, err := owner.ReadState()
	if err != nil || after == nil {
		t.Fatalf("owner after rejected command=%+v, err=%v", after, err)
	}
	after.UpdatedAt = before.UpdatedAt
	if !reflect.DeepEqual(before, after) {
		t.Fatal("configuration mismatch changed the full-stack owner")
	}
}

func TestWebRuntimeArguments(t *testing.T) {
	port, forwarded, err := frontendArgs([]string{"--", "-p3100", "--hostname", "localhost"})
	if err != nil || port != 3100 || !reflect.DeepEqual(forwarded, []string{"--hostname", "localhost"}) {
		t.Fatalf("frontendArgs after --=%d,%v,%v", port, forwarded, err)
	}
	for _, args := range [][]string{{"--port"}, {"-p"}, {"--port=bad"}, {"-p0"}, {"--port", "65536"}, {"-p3100", "--port", "3200"}} {
		want := "invalid web port"
		if len(args) == 1 && (args[0] == "--port" || args[0] == "-p") {
			want = "requires a port"
		} else if len(args) == 3 && args[0] == "-p3100" {
			want = "specify one web port"
		}
		if err := runWebDev(args); err == nil || !strings.Contains(err.Error(), want) {
			t.Fatalf("runWebDev(%v) error=%v, want %q", args, err, want)
		}
	}
}
