//go:build !windows

package cmd

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	log "github.com/sirupsen/logrus"
)

// runStackCommandExit runs "ods stack <args>" and returns stdout, stderr
// (including the log) and the exit code a log.Fatal or os.Exit would use.
func runStackCommandExit(t *testing.T, args ...string) (stdout, stderr string, code int) {
	t.Helper()
	logger := log.StandardLogger()
	var logBuf bytes.Buffer
	originalOut, originalExit := logger.Out, logger.ExitFunc
	logger.SetOutput(&logBuf)
	t.Cleanup(func() { logger.SetOutput(originalOut); logger.ExitFunc = originalExit })
	type exitCode int
	logger.ExitFunc = func(c int) { panic(exitCode(c)) }

	cmd := NewRootCommand()
	cmd.SetArgs(append([]string{"stack"}, args...))
	stderr = composeCapture(t, &os.Stderr, func() {
		stdout = composeCapture(t, &os.Stdout, func() {
			defer func() {
				if got := recover(); got != nil {
					c, ok := got.(exitCode)
					if !ok {
						panic(got)
					}
					code = int(c)
				}
			}()
			if err := cmd.Execute(); err != nil {
				t.Error(err)
			}
		})
	})
	return stdout, stderr + logBuf.String(), code
}

func stackFailureRepo(t *testing.T, python, launch string) string {
	t.Helper()
	root, _ := stackTestRepo(t)
	python = strings.Replace(python, "#!/bin/sh\n", "#!/bin/sh\nif [ \"$1\" = -c ]; then exit 10; fi\n", 1)
	writeFile(t, filepath.Join(root, ".venv", "bin", "python"), python)
	if err := os.Chmod(filepath.Join(root, ".venv", "bin", "python"), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(root, ".vscode", "launch.json"), launch)
	stack, _ := openStack(nil)
	t.Cleanup(func() {
		if err := stack.Stop(context.Background(), devstack.Options{StopTimeout: time.Second, LockWait: time.Second}); err != nil {
			t.Errorf("fixture cleanup: %v", err)
		}
	})
	return root
}

const workerOnlyLaunch = `{
  "compounds": [{"name": "Run All Onyx Services", "configurations": ["Celery primary"]}],
  "configurations": [
    {"name": "Celery primary", "type": "debugpy", "request": "launch", "program": "${workspaceFolder}/backend/scripts/dev_celery_reload.py", "cwd": "${workspaceFolder}/backend", "args": ["-A", "primary"]}
  ]
}`

func TestStackUp_reportsMigrationFailure(t *testing.T) {
	root := stackFailureRepo(t, "#!/bin/sh\nexec /bin/sleep 300\n", workerOnlyLaunch)
	writeFile(t, filepath.Join(root, ".venv", "bin", "alembic"), "#!/bin/sh\necho 'INFO  [alembic.runtime.migration] Running upgrade abc -> def'\necho 'sqlalchemy.exc.ProgrammingError: relation \"user\" already exists' >&2\nexit 1\n")
	stdout, stderr, code := runStackCommandExit(t, "up", "--profile", "full", "--skip-prepare", "--timeout", "10s", "--json")
	t.Logf("exit=%d\nstdout:\n%s\nstderr:\n%s", code, stdout, stderr)
	if code == 0 {
		t.Fatal("migration failure exited 0")
	}
	if !strings.Contains(stdout, `"phase": "failed"`) {
		t.Errorf("stdout has no failed status JSON")
	}
	if !strings.Contains(stdout, "already exists") {
		t.Errorf("status JSON does not carry the alembic error")
	}
}

func TestStackUp_reportsServiceExit(t *testing.T) {
	stackFailureRepo(t, "#!/bin/sh\necho 'ModuleNotFoundError: No module named celery' >&2\nexit 3\n", workerOnlyLaunch)
	stdout, stderr, code := runStackCommandExit(t, "up", "--profile", "full", "--skip-prepare", "--timeout", "10s", "--json")
	t.Logf("exit=%d\nstdout:\n%s\nstderr:\n%s", code, stdout, stderr)
	if code == 0 {
		t.Fatal("service exit exited 0")
	}
	if !strings.Contains(stdout, `"state": "exited"`) || !strings.Contains(stdout, "ModuleNotFoundError") {
		t.Errorf("status JSON does not show the exited service with its log tail")
	}
}

func TestStackUp_reportsUnhealthyService(t *testing.T) {
	stackFailureRepo(t, "#!/bin/sh\necho 'listening but never healthy'\nexec /bin/sleep 300\n", `{
  "compounds": [{"name": "Run All Onyx Services", "configurations": ["API Server"]}],
  "configurations": [
    {"name": "API Server", "type": "debugpy", "request": "launch", "module": "uvicorn", "cwd": "${workspaceFolder}/backend", "args": ["onyx.main:app", "--port", "8080"]}
  ]
}`)
	stdout, stderr, code := runStackCommandExit(t, "up", "--profile", "minimal", "--skip-prepare", "--timeout", "3s", "--json")
	t.Logf("exit=%d\nstdout:\n%s\nstderr:\n%s", code, stdout, stderr)
	if code != 2 {
		t.Errorf("not-ready exit = %d, want 2", code)
	}
	if !strings.Contains(stdout, `"healthy": false`) || !strings.Contains(stdout, "never healthy") {
		t.Errorf("status JSON does not show the unhealthy service with its log tail")
	}
}
