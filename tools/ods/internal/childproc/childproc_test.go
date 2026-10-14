package childproc

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// helperEnv makes the test binary act as an ods command that wraps the given
// shell command through Run; see TestHelperProcess.
const helperEnv = "CHILDPROC_HELPER_COMMAND"

func TestHelperProcess(t *testing.T) {
	command, ok := os.LookupEnv(helperEnv)
	if !ok {
		return
	}
	Run(exec.Command("sh", "-c", command), "wrapped tool")
	os.Exit(0)
}

// runHelper re-runs this test binary as a process that calls Run, since Run
// exits the process on failure.
func runHelper(t *testing.T, command string) (int, string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the wrapped command is a shell script")
	}
	c := exec.Command(os.Args[0], "-test.run=^TestHelperProcess$")
	c.Env = append(os.Environ(), helperEnv+"="+command)
	out, err := c.CombinedOutput()
	var exitErr *exec.ExitError
	if err != nil && !errors.As(err, &exitErr) {
		t.Fatalf("failed to start helper: %v", err)
	}
	return c.ProcessState.ExitCode(), string(out)
}

func TestRun_returnsWhenChildSucceeds(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the wrapped command is a shell script")
	}
	marker := filepath.Join(t.TempDir(), "ran")
	c := exec.Command("touch", marker)

	Run(c, "touch")

	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("expected the child to run: %v", err)
	}
	if c.Stdout != os.Stdout || c.Stderr != os.Stderr || c.Stdin != os.Stdin {
		t.Fatal("expected the child to inherit our stdio")
	}
}

func TestRun_exitsWithChildExitCode(t *testing.T) {
	code, out := runHelper(t, "echo child-stderr >&2; exit 7")

	if code != 7 {
		t.Fatalf("expected exit code 7, got %d (output %q)", code, out)
	}
	if strings.Contains(out, "Failed to run") {
		t.Fatalf("expected no extra failure message, got %q", out)
	}
	if !strings.Contains(out, "child-stderr") {
		t.Fatalf("expected the child's stderr to pass through, got %q", out)
	}
}

func TestRun_reportsChildKilledBySignal(t *testing.T) {
	code, out := runHelper(t, "kill -9 $$")

	if code != 1 {
		t.Fatalf("expected exit code 1, got %d (output %q)", code, out)
	}
	if !strings.Contains(out, "Failed to run wrapped tool: signal: killed") {
		t.Fatalf("expected a failure message naming the tool, got %q", out)
	}
}
