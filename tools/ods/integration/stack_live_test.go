//go:build integration

package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

const testPassword = "TestPassword123!"

type liveStack struct {
	root   string
	binary string
	client *http.Client
}

func TestStackLiveLifecycle(t *testing.T) {
	a := configuredStack(t, "ODS_STACK_LIVE_ROOT_A")
	b := configuredStack(t, "ODS_STACK_LIVE_ROOT_B")
	if a.root == b.root {
		t.Fatal("live roots must be different disposable worktrees")
	}
	if os.Getenv("ODS_STACK_KEEP_RUNNING") != "1" {
		t.Cleanup(func() {
			for _, stack := range []liveStack{a, b} {
				if _, err := stack.command("stack", "down"); err != nil {
					t.Errorf("cleanup %s: %v", stack.root, err)
				}
			}
		})
	}

	stacks := []liveStack{a, b}
	results := make([][]byte, len(stacks))
	startupErrors := make([]error, len(stacks))
	var startup sync.WaitGroup
	for i, stack := range stacks {
		startup.Go(func() {
			results[i], startupErrors[i] = stack.command("stack", "up", "--profile", "minimal", "--timeout", "12m", "--json")
		})
	}
	startup.Wait()
	states := make([]devstack.Status, len(stacks))
	for i := range stacks {
		if startupErrors[i] != nil {
			t.Fatal(startupErrors[i])
		}
		if err := json.Unmarshal(results[i], &states[i]); err != nil || !states[i].Ready {
			t.Fatalf("worktree %s did not become ready: parse=%v status=%+v", stacks[i].root, err, states[i])
		}
	}
	sa, sb := &states[0], &states[1]
	if sa.Project == sb.Project {
		t.Fatal("worktrees share a Compose project")
	}
	for name, port := range sa.Ports {
		for otherName, otherPort := range sb.Ports {
			if port > 0 && port == otherPort {
				t.Errorf("worktrees share %s/%s port %d", name, otherName, port)
			}
		}
	}
	a.ready(t, sa)
	b.ready(t, sb)

	t.Run("databases and authentication are isolated", func(t *testing.T) {
		for _, stack := range []struct {
			stack liveStack
			state *devstack.Status
		}{{a, sa}, {b, sb}} {
			stack.stack.register(t, stack.state, "admin_user@example.com")
		}
		a.register(t, sa, "ods-stack-a@example.com")
		if status := a.login(t, sa, "ods-stack-a@example.com"); status != http.StatusNoContent {
			t.Fatalf("login on owning stack: HTTP %d", status)
		}
		if status := b.login(t, sb, "ods-stack-a@example.com"); status < 400 || status >= 500 {
			t.Fatalf("credentials leaked across stacks: HTTP %d", status)
		}
	})

	t.Run("concurrent up preserves healthy processes and ports", func(t *testing.T) {
		before := a.status(t)
		var wg sync.WaitGroup
		errors := make(chan error, 2)
		for range 2 {
			wg.Go(func() {
				_, err := a.command("stack", "up", "--profile", "minimal", "--skip-prepare", "--timeout", "12m", "--json")
				errors <- err
			})
		}
		wg.Wait()
		close(errors)
		for err := range errors {
			if err != nil {
				t.Fatal(err)
			}
		}
		after := a.status(t)
		if !reflect.DeepEqual(before.Ports, after.Ports) {
			t.Fatalf("healthy ports changed: %v -> %v", before.Ports, after.Ports)
		}
		if !reflect.DeepEqual(servicePIDs(before), servicePIDs(after)) {
			t.Fatal("healthy service processes were replaced")
		}
	})

	t.Run("stop and restart preserve data and the other stack", func(t *testing.T) {
		before := a.status(t)
		if _, err := a.command("stack", "stop"); err != nil {
			t.Fatal(err)
		}
		if a.status(t).Ready {
			t.Fatal("stopped stack still reports ready")
		}
		b.ready(t, b.status(t))
		after := a.start(t)
		if !reflect.DeepEqual(before.Ports, after.Ports) {
			t.Fatal("restart did not reuse durable ports")
		}
		if status := a.login(t, after, "ods-stack-a@example.com"); status != http.StatusNoContent {
			t.Fatalf("restart lost database data: HTTP %d", status)
		}
	})

	t.Run("occupied application port moves safely", func(t *testing.T) {
		before := a.status(t)
		if _, err := a.command("stack", "stop"); err != nil {
			t.Fatal(err)
		}
		listener, err := net.Listen("tcp", fmt.Sprintf(":%d", before.Ports["web"]))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = listener.Close() }()
		after := a.start(t)
		if after.Ports["web"] == before.Ports["web"] {
			t.Fatal("stack did not replace occupied port")
		}
		if after.Ports["api"] != before.Ports["api"] {
			t.Fatal("unaffected API port changed")
		}
		a.ready(t, after)
		b.ready(t, b.status(t))
	})

	t.Run("down and up preserve volumes and durable assignments", func(t *testing.T) {
		before := a.status(t)
		if _, err := a.command("stack", "down"); err != nil {
			t.Fatal(err)
		}
		containers := dockerOutput(t, "ps", "--filter", "label=com.docker.compose.project="+before.Project, "--format", "{{.ID}}")
		if containers != "" {
			t.Fatalf("down left infrastructure containers running: %s", containers)
		}
		volumes := dockerOutput(t, "volume", "ls", "--filter", "label=com.docker.compose.project="+before.Project, "--format", "{{.Name}}")
		if volumes == "" {
			t.Fatal("down removed persistent volumes")
		}
		b.ready(t, b.status(t))
		after := a.up(t)
		if !reflect.DeepEqual(before.Ports, after.Ports) {
			t.Fatal("down/up did not reuse assigned ports")
		}
		if status := a.login(t, after, "ods-stack-a@example.com"); status != http.StatusNoContent {
			t.Fatalf("down/up lost database data: HTTP %d", status)
		}
	})
}

func configuredStack(t *testing.T, variable string) liveStack {
	t.Helper()
	root := os.Getenv(variable)
	binary := os.Getenv("ODS_STACK_LIVE_BINARY")
	if root == "" || binary == "" {
		t.Skip("set ODS_STACK_LIVE_BINARY and both ODS_STACK_LIVE_ROOT_A/B to disposable worktrees")
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		t.Fatal(err)
	}
	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	return liveStack{root: abs, binary: binary, client: &http.Client{Jar: jar, Timeout: 30 * time.Second}}
}

func (s liveStack) command(args ...string) ([]byte, error) {
	if len(args) > 0 && args[0] == "stack" {
		args = append([]string{"stack", "--isolated"}, args[1:]...)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, s.binary, args...)
	cmd.Dir = s.root
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		return stdout.Bytes(), fmt.Errorf("ods %s in %s: %w\n%s", strings.Join(args, " "), s.root, err, stderr.String())
	}
	return stdout.Bytes(), nil
}

func (s liveStack) up(t *testing.T) *devstack.Status {
	t.Helper()
	return s.lifecycle(t, "up")
}

func (s liveStack) start(t *testing.T) *devstack.Status {
	t.Helper()
	return s.lifecycle(t, "start")
}

func (s liveStack) lifecycle(t *testing.T, action string) *devstack.Status {
	t.Helper()
	data, err := s.command("stack", action, "--profile", "minimal", "--timeout", "12m", "--json")
	if err != nil {
		t.Fatal(err)
	}
	var status devstack.Status
	if err := json.Unmarshal(data, &status); err != nil {
		t.Fatalf("invalid lifecycle JSON: %v", err)
	}
	if !status.Ready {
		t.Fatalf("stack is not ready: %v", status.Errors)
	}
	return &status
}

func (s liveStack) status(t *testing.T) *devstack.Status {
	t.Helper()
	data, err := s.command("stack", "status", "--json")
	var status devstack.Status
	if parseErr := json.Unmarshal(data, &status); parseErr != nil {
		t.Fatalf("invalid status JSON: %v, command: %v", parseErr, err)
	}
	return &status
}

func (s liveStack) ready(t *testing.T, status *devstack.Status) {
	t.Helper()
	response, err := s.client.Get(status.URLs["web"] + "/api/auth/type")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("frontend API proxy readiness: HTTP %d", response.StatusCode)
	}
}

func (s liveStack) register(t *testing.T, status *devstack.Status, email string) {
	t.Helper()
	data, err := json.Marshal(map[string]string{"email": email, "username": email, "password": testPassword})
	if err != nil {
		t.Fatal(err)
	}
	response, err := s.client.Post(status.URLs["web"]+"/api/auth/register", "application/json", bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = response.Body.Close() }()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode >= 300 && !bytes.Contains(body, []byte("REGISTER_USER_ALREADY_EXISTS")) {
		t.Fatalf("registration: HTTP %d", response.StatusCode)
	}
}

func (s liveStack) login(t *testing.T, status *devstack.Status, email string) int {
	t.Helper()
	response, err := s.client.PostForm(status.URLs["web"]+"/api/auth/login", url.Values{"username": {email}, "password": {testPassword}})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = response.Body.Close() }()
	return response.StatusCode
}

func servicePIDs(status *devstack.Status) map[string]int {
	pids := map[string]int{}
	for _, service := range status.Services {
		pids[service.Slug] = service.PID
	}
	return pids
}

func dockerOutput(t *testing.T, args ...string) string {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	data, err := exec.CommandContext(ctx, "docker", args...).CombinedOutput()
	if err != nil {
		t.Fatalf("docker %v: %v, %s", args, err, data)
	}
	return strings.TrimSpace(string(data))
}
