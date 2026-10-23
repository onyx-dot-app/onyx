package cmd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

func TestRuntimeCommandsUseTheSameSavedProjectAndDatabasePort(t *testing.T) {
	root := composeRepo(t)
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	stack, err := devstack.Open(root, "shared-data", devstack.Shared)
	if err != nil {
		t.Fatal(err)
	}
	if err := stack.WriteState(&devstack.State{Phase: devstack.PhaseStopped, Ports: map[string]int{"POSTGRES_HOST_PORT": 15439}}); err != nil {
		t.Fatal(err)
	}
	bin := composeFakeBin(t)
	composeFakeTool(t, bin, "docker", `case "$1" in
inspect) echo true ;;
port) case "$2" in shared-data-relational_db-1) echo 127.0.0.1:15439 ;; *) exit 1 ;; esac ;;
esac`)
	if err := os.MkdirAll(filepath.Join(root, ".vscode"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".vscode", ".env"), []byte("POSTGRES_PORT=5432\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := runEnv(false); err != nil {
		t.Fatal(err)
	}
	if got := composeReadFile(t, filepath.Join(root, ".vscode", ".env")); !strings.Contains(got, "POSTGRES_PORT=15439") {
		t.Fatalf("env lost actual port: %s", got)
	}
	if err := runComposeLogs([]string{"api_server"}, &LogsOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := runComposePull(&PullOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := runCompose("dev", &ComposeOptions{Down: true}); err != nil {
		t.Fatal(err)
	}
	for _, call := range composeCalls(t, bin, "docker") {
		if strings.HasPrefix(call, "compose ") && !strings.Contains(call, "-p shared-data ") {
			t.Fatalf("different infrastructure target: %s", call)
		}
		if strings.HasPrefix(call, "port ") && !strings.Contains(call, "shared-data-") {
			t.Fatalf("different endpoint target: %s", call)
		}
	}
}

func TestComposeCannotBypassManagedOwnershipOrProcessSupervision(t *testing.T) {
	for _, foreign := range []bool{false, true} {
		t.Run(map[bool]string{false: "active owner", true: "other checkout"}[foreign], func(t *testing.T) {
			root := composeRepo(t)
			t.Setenv("XDG_DATA_HOME", t.TempDir())
			stack, err := devstack.Open(root, "shared-data", devstack.Shared)
			if err != nil {
				t.Fatal(err)
			}
			owner := root
			if foreign {
				owner = t.TempDir()
			}
			if err := stack.WriteState(&devstack.State{Root: owner, Phase: devstack.PhaseReady, Services: []devstack.ServiceRecord{{Slug: "api", PID: 123}}}); err != nil {
				t.Fatal(err)
			}
			bin := composeFakeBin(t)
			composeFakeTool(t, bin, "docker", "exit 0")
			if err := runCompose("dev", &ComposeOptions{Down: true}); err == nil {
				t.Fatal("raw shutdown bypassed managed stack")
			}
			if got := composeCalls(t, bin, "docker"); len(got) != 0 {
				t.Fatalf("rejected command changed containers: %v", got)
			}
		})
	}
}

func TestFrontendPortArgumentsPreserveTrackedBindings(t *testing.T) {
	for _, args := range [][]string{{"--port", "3101"}, {"--port=3101"}, {"-p", "3101"}, {"-p3101"}, {"-p=3101"}} {
		port, forwarded, err := frontendArgs(append(args, "--hostname", "127.0.0.1"))
		if err != nil || port != 3101 || strings.Join(forwarded, " ") != "--hostname 127.0.0.1" {
			t.Fatalf("incorrect forwarded port: %v %d %v %v", args, port, forwarded, err)
		}
	}
	for _, args := range [][]string{{"--port"}, {"--port", "0"}, {"--port=bad"}, {"-p65536"}, {"--port", "3101", "-p3102"}} {
		if _, _, err := frontendArgs(args); err == nil {
			t.Fatalf("invalid port accepted: %v", args)
		}
	}
}

func TestRuntimeMutationRechecksNewOwnershipAfterResolution(t *testing.T) {
	root := composeRepo(t)
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	target, err := devstack.ResolveTarget(root, "shared-data", devstack.Shared)
	if err != nil {
		t.Fatal(err)
	}
	if target.Managed {
		t.Fatal("fresh target must not have an owner")
	}
	stack := stackForTarget(target)
	owner := t.TempDir()
	if err := stack.WriteState(&devstack.State{Root: owner, Phase: devstack.PhaseReady}); err != nil {
		t.Fatal(err)
	}
	release, err := lockRuntimeTarget(target, true)
	if err == nil {
		release()
		t.Fatal("mutation accepted an owner assigned after target resolution")
	}
	if !strings.Contains(err.Error(), owner) {
		t.Fatalf("missing current owner in error: %v", err)
	}
	if err := stack.WriteState(&devstack.State{Root: root, Phase: devstack.PhaseReady}); err != nil {
		t.Fatal(err)
	}
	release, err = lockRuntimeTarget(target, true)
	if err == nil {
		release()
		t.Fatal("mutation accepted stale unmanaged ports after same-checkout startup")
	}
}
