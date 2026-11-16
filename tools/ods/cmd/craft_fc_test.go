package cmd

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// craftFCFakeKubectl answers "get pods" with $ODS_TEST_PODS, copies the stdin
// of "exec" to $ODS_TEST_STDIN, prints a report and exits $ODS_TEST_EXIT.
const craftFCFakeKubectl = `for a in "$@"; do
  case "$a" in
    get) printf '%s' "$ODS_TEST_PODS"; exit 0 ;;
    exec)
      while IFS= read -r line || [ -n "$line" ]; do printf '%s\n' "$line"; done > "$ODS_TEST_STDIN"
      printf 'RESULT from pod\n'
      exit "$ODS_TEST_EXIT" ;;
  esac
done
exit 9
`

func craftFCSmokeRepo(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	script := filepath.Join(root, craftFCSmokeScript)
	if err := os.MkdirAll(filepath.Dir(script), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(script, []byte("print('smoke')\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return root
}

func craftFCSmokeEnv(t *testing.T, pods string, exit string) string {
	t.Helper()
	stdin := filepath.Join(t.TempDir(), "stdin")
	t.Setenv("ODS_TEST_PODS", pods)
	t.Setenv("ODS_TEST_STDIN", stdin)
	t.Setenv("ODS_TEST_EXIT", exit)
	return stdin
}

func TestCraftFCSmoke_sendsTheScriptToARunningAPIPod(t *testing.T) {
	calls := kubeFakeTools(t, map[string]string{"kubectl": craftFCFakeKubectl})
	stdin := craftFCSmokeEnv(t, "onyx-api-server-a\nonyx-api-server-b\n", "0")
	root := craftFCSmokeRepo(t)
	opts := &craftFCSmokeOptions{
		context: "ctx", namespace: "ns", selector: "app=api-server", container: "api-server",
		tenantID: "t1", egressURL: "https://example.com/", cleanupLeaked: true, verbose: true,
	}
	var out bytes.Buffer

	code, err := runCraftFCSmoke(opts, root, &out, &out)

	if err != nil || code != 0 {
		t.Fatalf("expected success, got code %d err %v", code, err)
	}
	if out.String() != "RESULT from pod\n" {
		t.Fatalf("expected the pod output, got %q", out.String())
	}
	got, err := os.ReadFile(stdin)
	if err != nil || string(got) != "print('smoke')\n" {
		t.Fatalf("expected the script on stdin, got %q (%v)", got, err)
	}
	tmpl := `{{range .items}}{{if not .metadata.deletionTimestamp}}{{.metadata.name}}{{"\n"}}{{end}}{{end}}`
	kubeAssertCalls(t, kubeCallsTo(calls(), "kubectl"), [][]string{
		{"--context", "ctx", "--namespace", "ns", "get", "pods", "-l", "app=api-server",
			"--field-selector", "status.phase=Running", "-o", "go-template=" + tmpl},
		{"--context", "ctx", "--namespace", "ns", "exec", "-i", "onyx-api-server-a", "-c", "api-server",
			"--", "python", "-", "--tenant-id", "t1", "--egress-url", "https://example.com/",
			"--cleanup-leaked", "--verbose"},
	})
}

func TestCraftFCSmoke_returnsTheScriptExitCode(t *testing.T) {
	kubeFakeTools(t, map[string]string{"kubectl": craftFCFakeKubectl})
	craftFCSmokeEnv(t, "pod-a\n", "1")
	opts := &craftFCSmokeOptions{context: "ctx", namespace: "onyx", selector: "app=api-server", container: "api-server", skipEgress: true}
	var out bytes.Buffer

	code, err := runCraftFCSmoke(opts, craftFCSmokeRepo(t), &out, &out)

	if err != nil || code != 1 {
		t.Fatalf("expected exit code 1, got %d err %v", code, err)
	}
}

func TestCraftFCSmoke_refusesToRunWithoutAPod(t *testing.T) {
	calls := kubeFakeTools(t, map[string]string{"kubectl": craftFCFakeKubectl})
	craftFCSmokeEnv(t, "", "0")
	opts := &craftFCSmokeOptions{context: "ctx", namespace: "onyx", selector: "app=api-server", container: "api-server"}

	_, err := runCraftFCSmoke(opts, craftFCSmokeRepo(t), &bytes.Buffer{}, &bytes.Buffer{})

	if err == nil || !strings.Contains(err.Error(), "no running pod") {
		t.Fatalf("expected a no-pod error, got %v", err)
	}
	if n := len(kubeCallsTo(calls(), "kubectl")); n != 1 {
		t.Fatalf("expected no exec after the pod lookup, got %d calls", n)
	}
}

func TestCraftFCSmoke_rejectsBadFlags(t *testing.T) {
	cases := []struct {
		name string
		opts craftFCSmokeOptions
		want string
	}{
		{"no context", craftFCSmokeOptions{namespace: "onyx"}, "--context is required"},
		{"egress flags together", craftFCSmokeOptions{context: "ctx", skipEgress: true, egressURL: "https://x/"}, "cannot be used together"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := kubeFakeTools(t, map[string]string{"kubectl": craftFCFakeKubectl})
			_, err := runCraftFCSmoke(&c.opts, craftFCSmokeRepo(t), &bytes.Buffer{}, &bytes.Buffer{})
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("expected %q, got %v", c.want, err)
			}
			if got := calls(); len(got) != 0 {
				t.Fatalf("expected no kubectl call, got %q", got)
			}
		})
	}
}

func TestCraftFCSmoke_needsTheContextFlag(t *testing.T) {
	cmd := NewCraftFCCommand()
	cmd.SetArgs([]string{"smoke"})
	cmd.SilenceUsage, cmd.SilenceErrors = true, true
	if err := cmd.Execute(); err == nil || !strings.Contains(err.Error(), "context") {
		t.Fatalf("expected a required-flag error, got %v", err)
	}
}
