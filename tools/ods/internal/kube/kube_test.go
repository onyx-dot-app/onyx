package kube

import (
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
)

// fakeTools puts shell scripts named after each key on PATH, and nothing else.
// Every call appends its argv (tool name first) to a log that calls reads back.
func fakeTools(t *testing.T, scripts map[string]string) func() [][]string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake tools are shell scripts")
	}
	dir := t.TempDir()
	logPath := filepath.Join(dir, "calls.log")
	for name, body := range scripts {
		script := "#!/bin/sh\n" +
			"printf '%s\\037' " + name + " \"$@\" >> \"${0%/*}/calls.log\"\n" +
			"printf '\\n' >> \"${0%/*}/calls.log\"\n" +
			body
		if err := os.WriteFile(filepath.Join(dir, name), []byte(script), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", dir)

	return func() [][]string {
		data, err := os.ReadFile(logPath)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			t.Fatal(err)
		}
		var calls [][]string
		for _, line := range strings.Split(strings.TrimSuffix(string(data), "\n"), "\n") {
			calls = append(calls, strings.Split(strings.TrimSuffix(line, "\x1f"), "\x1f"))
		}
		return calls
	}
}

func testCluster() *Cluster {
	return &Cluster{Name: "prod", Region: "us-east-2", Namespace: "onyx"}
}

func TestEnsureContext_skipsAWSWhenTheContextExists(t *testing.T) {
	calls := fakeTools(t, map[string]string{"kubectl": "exit 0\n", "aws": "exit 0\n"})

	if err := testCluster().EnsureContext(); err != nil {
		t.Fatalf("EnsureContext: %v", err)
	}

	want := [][]string{{"kubectl", "config", "get-contexts", "prod", "--no-headers"}}
	if got := calls(); !slices.EqualFunc(got, want, slices.Equal) {
		t.Fatalf("expected calls %q, got %q", want, got)
	}
}

func TestEnsureContext_fetchesKubeconfigWhenTheContextIsMissing(t *testing.T) {
	calls := fakeTools(t, map[string]string{"kubectl": "exit 1\n", "aws": "exit 0\n"})

	if err := testCluster().EnsureContext(); err != nil {
		t.Fatalf("EnsureContext: %v", err)
	}

	got := calls()
	want := []string{"aws", "eks", "update-kubeconfig", "--region", "us-east-2", "--name", "prod", "--alias", "prod"}
	if len(got) != 2 || !slices.Equal(got[1], want) {
		t.Fatalf("expected the second call to be %q, got %q", want, got)
	}
}

func TestEnsureContext_reportsTheAWSOutputOnFailure(t *testing.T) {
	fakeTools(t, map[string]string{"kubectl": "exit 1\n", "aws": "echo 'token expired' >&2\nexit 255\n"})

	err := testCluster().EnsureContext()
	if err == nil {
		t.Fatal("expected an error")
	}
	if !strings.Contains(err.Error(), "aws eks update-kubeconfig failed") || !strings.Contains(err.Error(), "token expired") {
		t.Fatalf("expected the aws failure and its output, got %q", err)
	}
}

func TestFindPod_returnsTheFirstReadyMatch(t *testing.T) {
	// Scripts only have shell builtins: PATH holds nothing but the fakes.
	calls := fakeTools(t, map[string]string{"kubectl": `printf '%s\n' \
  'web-server-abc        True' \
  'api-server-starting   False' \
  'malformed-line' \
  'api-server-ready      True' \
  'api-server-later      True'
`})

	pod, err := testCluster().FindPod("api-server")
	if err != nil {
		t.Fatalf("FindPod: %v", err)
	}
	if pod != "api-server-ready" {
		t.Fatalf("expected %q, got %q", "api-server-ready", pod)
	}

	want := []string{
		"kubectl", "--context", "prod", "--namespace", "onyx", "get", "po",
		"--field-selector", "status.phase=Running",
		"--no-headers",
		"-o", "custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type=='Ready')].status",
	}
	if got := calls(); len(got) != 1 || !slices.Equal(got[0], want) {
		t.Fatalf("expected calls [%q], got %q", want, got)
	}
}

func TestFindPod_errorsWhenNoPodIsReady(t *testing.T) {
	fakeTools(t, map[string]string{"kubectl": "echo 'api-server-x False'\n"})

	_, err := testCluster().FindPod("api-server")
	if err == nil || err.Error() != `no ready pod found matching "api-server"` {
		t.Fatalf("expected the no-ready-pod error, got %v", err)
	}
}

func TestFindPod_includesKubectlStderr(t *testing.T) {
	fakeTools(t, map[string]string{"kubectl": "echo 'forbidden' >&2\nexit 1\n"})

	_, err := testCluster().FindPod("api-server")
	if err == nil || !strings.Contains(err.Error(), "kubectl get po failed") || !strings.Contains(err.Error(), "forbidden") {
		t.Fatalf("expected the kubectl failure with stderr, got %v", err)
	}
}

func TestFindPod_errorsWhenKubectlIsMissing(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("PATH lookup differs on Windows")
	}
	t.Setenv("PATH", t.TempDir())

	_, err := testCluster().FindPod("api-server")
	if err == nil || !strings.HasPrefix(err.Error(), "kubectl get po failed: exec: ") {
		t.Fatalf("expected a lookup failure, got %v", err)
	}
}

func TestExecOnPod_passesTheCommandAndReturnsStdout(t *testing.T) {
	calls := fakeTools(t, map[string]string{"kubectl": "echo 'row 1'\necho 'noise' >&2\n"})

	out, err := testCluster().ExecOnPod("api-server-1", "pginto", "-c", "SELECT 1;")
	if err != nil {
		t.Fatalf("ExecOnPod: %v", err)
	}
	if out != "row 1\n" {
		t.Fatalf("expected %q, got %q", "row 1\n", out)
	}

	want := []string{"kubectl", "--context", "prod", "--namespace", "onyx", "exec", "api-server-1", "--", "pginto", "-c", "SELECT 1;"}
	if got := calls(); len(got) != 1 || !slices.Equal(got[0], want) {
		t.Fatalf("expected calls [%q], got %q", want, got)
	}
}

func TestExecOnPod_includesStderrOnFailure(t *testing.T) {
	fakeTools(t, map[string]string{"kubectl": "echo 'relation does not exist' >&2\nexit 1\n"})

	_, err := testCluster().ExecOnPod("api-server-1", "pginto")
	if err == nil || !strings.Contains(err.Error(), "kubectl exec failed") || !strings.Contains(err.Error(), "relation does not exist") {
		t.Fatalf("expected the exec failure with stderr, got %v", err)
	}
}
