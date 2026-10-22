package auditcmd

import (
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

// exitHelperEnv selects the error a re-executed test binary passes to
// exitOnError, because exitOnError ends the process.
const exitHelperEnv = "AUDITCMD_EXIT_HELPER"

func TestExitOnErrorHelper(t *testing.T) {
	switch os.Getenv(exitHelperEnv) {
	case "":
		t.Skip("only runs as the subprocess of TestExitOnError")
	case "nil":
		exitOnError(nil)
		os.Exit(0)
	case "blocking":
		exitOnError(&blockingError{count: 2, failOn: audit.SeverityHigh})
	case "command":
		exitOnError(failf("Audit failed: %v", errors.New("boom")))
	}
	os.Exit(3) // exitOnError returned for an error
}

func TestExitOnError(t *testing.T) {
	cases := []struct {
		helper   string
		wantCode int
		wantLog  string
	}{
		{"nil", 0, ""},
		{"blocking", 1, `level=error msg="2 finding(s) at or above high severity must be resolved or suppressed"`},
		{"command", 1, `level=fatal msg="Audit failed: boom"`},
	}
	for _, tc := range cases {
		t.Run(tc.helper, func(t *testing.T) {
			cmd := exec.Command(os.Args[0], "-test.run=^TestExitOnErrorHelper$")
			cmd.Env = append(os.Environ(), exitHelperEnv+"="+tc.helper)
			out, err := cmd.CombinedOutput()

			code := 0
			var exitErr *exec.ExitError
			if errors.As(err, &exitErr) {
				code = exitErr.ExitCode()
			} else if err != nil {
				t.Fatalf("running the helper: %v", err)
			}
			if code != tc.wantCode {
				t.Fatalf("expected exit code %d, got %d\n%s", tc.wantCode, code, out)
			}
			if tc.wantLog != "" && !strings.Contains(string(out), tc.wantLog) {
				t.Fatalf("expected the log line %s, got:\n%s", tc.wantLog, out)
			}
		})
	}
}
