package cmd

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"

	log "github.com/sirupsen/logrus"
	logtest "github.com/sirupsen/logrus/hooks/test"
	"github.com/spf13/cobra"
)

// kubeFakeTools replaces PATH with a directory holding one shell script per
// key. Scripts only have shell builtins (plus absolute paths such as
// /bin/mkdir), so a missing fake can never fall through to a real tool. Every
// call appends its argv, tool name first, to a log that the returned function
// reads back.
func kubeFakeTools(t *testing.T, scripts map[string]string) func() [][]string {
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

// kubeGitScript is a fake git that reports root as the repository top level
// and branch as the current branch. The values reach the script through the
// environment.
func kubeGitScript(t *testing.T, root, branch string) string {
	t.Setenv("ODS_TEST_GIT_ROOT", root)
	t.Setenv("ODS_TEST_GIT_BRANCH", branch)
	return `case "$1" in
  rev-parse) printf '%s\n' "$ODS_TEST_GIT_ROOT" ;;
  branch) printf '%s\n' "$ODS_TEST_GIT_BRANCH" ;;
esac
`
}

// kubeCallsTo returns the calls made to one tool, without the tool name.
func kubeCallsTo(calls [][]string, tool string) [][]string {
	var out [][]string
	for _, c := range calls {
		if c[0] == tool {
			out = append(out, c[1:])
		}
	}
	return out
}

func kubeAssertCalls(t *testing.T, got, want [][]string) {
	t.Helper()
	if !slices.EqualFunc(got, want, slices.Equal) {
		t.Fatalf("expected calls %q, got %q", want, got)
	}
}

// kubeExecute runs cmd with args and returns what it wrote to stdout.
func kubeExecute(t *testing.T, cmd *cobra.Command, args ...string) string {
	t.Helper()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetArgs(append([]string{}, args...))
	if err := cmd.Execute(); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	return out.String()
}

// kubeCaptureLogs records logrus entries for the rest of the test.
func kubeCaptureLogs(t *testing.T) *logtest.Hook {
	t.Helper()
	logger := log.StandardLogger()
	hook := new(logtest.Hook)
	previous := logger.ReplaceHooks(make(log.LevelHooks))
	logger.AddHook(hook)
	t.Cleanup(func() { logger.ReplaceHooks(previous) })
	return hook
}
