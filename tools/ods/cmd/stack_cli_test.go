//go:build !windows

package cmd

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

func TestStackStopAndDownCommandsPreserveDataAndPorts(t *testing.T) {
	for _, action := range []string{"stop", "down"} {
		t.Run(action, func(t *testing.T) {
			_, calls := stackTestRepo(t)
			stack, _ := openStack()
			if err := stack.WriteState(&devstack.State{Phase: devstack.PhaseReady, Profile: "minimal", Ports: map[string]int{"web": 3100}}); err != nil {
				t.Fatal(err)
			}
			cmd := NewRootCommand()
			cmd.SetArgs([]string{"stack", action, "--timeout", "100ms", "--lock-wait", "1s"})
			if err := cmd.Execute(); err != nil {
				t.Fatal(err)
			}
			state, err := stack.ReadState()
			if err != nil || state == nil || state.Phase != devstack.PhaseStopped || state.Ports["web"] != 3100 {
				t.Fatalf("shutdown must preserve durable ports: state=%+v err=%v", state, err)
			}
			dockerCalls := devtoolCalls(t, calls["docker"])
			if action == "stop" {
				if len(dockerCalls) != 0 {
					t.Fatalf("stop touched infrastructure: %v", dockerCalls)
				}
				return
			}
			if len(dockerCalls) != 1 || !slices.Contains(dockerCalls[0].Args, "down") {
				t.Fatalf("down did not stop Compose: %v", dockerCalls)
			}
			if slices.Contains(dockerCalls[0].Args, "--volumes") || slices.Contains(dockerCalls[0].Args, "-v") {
				t.Fatalf("normal shutdown deletes volumes: %v", dockerCalls)
			}
		})
	}
}

func TestStackStatusCommandJSONUsesWorktreePorts(t *testing.T) {
	root, _ := stackTestRepo(t)
	stack, _ := openStack()
	if err := stack.WriteState(&devstack.State{
		Phase: devstack.PhaseReady, Profile: "full", Ports: map[string]int{"web": 3101, "api": 8181},
		Services: []devstack.ServiceRecord{{Name: "Slack Bot", Slug: "slack-bot", Skipped: "credentials missing", Optional: true}},
	}); err != nil {
		t.Fatal(err)
	}
	cmd := NewRootCommand()
	cmd.SetArgs([]string{"stack", "status", "--json"})
	out := composeCapture(t, &os.Stdout, func() {
		if err := cmd.Execute(); err != nil {
			t.Error(err)
		}
	})
	var status devstack.Status
	if err := json.Unmarshal([]byte(out), &status); err != nil {
		t.Fatalf("status stdout is not one JSON document: %v: %s", err, out)
	}
	if status.Root != root || status.Project != stack.Project || status.URLs["web"] != "http://localhost:3101" || status.URLs["api"] != "http://localhost:8181" {
		t.Fatalf("wrong worktree discovery: %+v", status)
	}
	if len(status.Services) != 1 || status.Services[0].Reason != "credentials missing" {
		t.Fatalf("optional-service explanation missing: %+v", status.Services)
	}
}

func TestStackLogsCommandAcceptsLaunchName(t *testing.T) {
	root, calls := stackTestRepo(t)
	stack, _ := openStack()
	logPath := filepath.Join(root, "api.log")
	if err := stack.WriteState(&devstack.State{Services: []devstack.ServiceRecord{{Name: "API Server", Slug: "api", Log: logPath}}}); err != nil {
		t.Fatal(err)
	}
	cmd := NewRootCommand()
	cmd.SetArgs([]string{"stack", "logs", "API Server", "--lines", "7", "--follow"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	tail := devtoolCalls(t, calls["tail"])
	if len(tail) != 1 || !slices.Equal(tail[0].Args, []string{"-n", "7", "-F", logPath}) {
		t.Fatalf("logs invocation: %v", tail)
	}
}

func TestStackCommandsRejectUnexpectedArgumentsBeforeSetup(t *testing.T) {
	_, calls := stackTestRepo(t)
	for _, action := range []string{"up", "start", "restart", "stop", "down", "status", "plan"} {
		cmd := NewRootCommand()
		cmd.SetArgs([]string{"stack", action, "unexpected"})
		if err := cmd.Execute(); err == nil || !strings.Contains(err.Error(), "unknown command") {
			t.Errorf("%s accepted an unexpected argument: %v", action, err)
		}
	}
	for tool, path := range calls {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Errorf("argument validation invoked %s: %v", tool, err)
		}
	}
}

func TestStackPrepareReportsDockerAndDependencyFailures(t *testing.T) {
	for _, tool := range []string{"docker", "uv"} {
		t.Run(tool, func(t *testing.T) {
			_, calls := stackTestRepo(t)
			bin, err := exec.LookPath(tool)
			if err != nil {
				t.Fatal(err)
			}
			devtoolFakeTool(t, filepath.Dir(bin), tool, "exit 42\n")
			_, provider := openStack()
			err = provider.Prepare(context.Background())
			if err == nil || !strings.Contains(err.Error(), tool) || !strings.Contains(err.Error(), "exit status 42") {
				t.Fatalf("missing actionable setup failure: %v", err)
			}
			if got := devtoolCalls(t, calls["bun"]); len(got) != 0 {
				t.Fatalf("continued installation after failure: %v", got)
			}
		})
	}
}

func TestStackLifecycleCommandsReportFailedSetup(t *testing.T) {
	for _, action := range []string{"up", "start", "restart"} {
		t.Run(action, func(t *testing.T) {
			_, _ = stackTestRepo(t)
			uv, err := exec.LookPath("uv")
			if err != nil {
				t.Fatal(err)
			}
			devtoolFakeTool(t, filepath.Dir(uv), "uv", "exit 42\n")
			logger := log.StandardLogger()
			originalExit := logger.ExitFunc
			originalHook := exitHook
			t.Cleanup(func() { logger.ExitFunc = originalExit; exitHook = originalHook })
			type exitCode int
			logger.ExitFunc = func(code int) { panic(exitCode(code)) }
			exitHook = func(code int) { panic(exitCode(code)) }
			cmd := NewRootCommand()
			cmd.SetArgs([]string{"stack", action, "--timeout", "100ms", "--lock-wait", "1s"})
			func() {
				defer func() {
					if got := recover(); got != exitCode(1) {
						t.Fatalf("setup failure exit = %v, want 1", got)
					}
				}()
				_ = cmd.Execute()
			}()
			stack, _ := openStack()
			state, err := stack.ReadState()
			if err != nil || state == nil || state.Phase != devstack.PhaseFailed || len(state.Errors) != 1 || !strings.Contains(state.Errors[0], "exit status 42") {
				t.Fatalf("failed setup was not recorded: state=%+v err=%v", state, err)
			}
		})
	}
}
