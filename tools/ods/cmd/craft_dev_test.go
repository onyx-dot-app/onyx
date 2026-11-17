package cmd

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestCraftDev_buildsTheLauncherArgv(t *testing.T) {
	const (
		launch = "deployment/helm/dev/launch.py"
		dev    = "deployment/helm/dev/dev.py"
		vm     = "deployment/helm/dev/craft_fc_vm.py"
	)
	// uv records the script and its args; the root is added per case.
	uv := func(script string, args ...string) []string {
		return append([]string{script}, args...)
	}
	cases := []struct {
		name string
		args []string
		want []string
	}{
		{"doctor", []string{"doctor"}, uv(dev, "--target", "craft-dev", "doctor")},
		{"doctor with profile and context", []string{"--profile", "/p.yaml", "doctor", "--context", "ctx"},
			uv(dev, "--target", "craft-dev", "--profile", "/p.yaml", "--context", "ctx", "doctor")},
		{"api with port and uvicorn args", []string{"api", "--port", "8081", "--", "--log-level", "debug"},
			uv(launch, "--target", "craft-dev", "--port", "8081", "api", "--", "--log-level", "debug")},
		{"web", []string{"web"}, uv(launch, "--target", "craft-dev", "web")},
		{"skills push", []string{"skills", "push", "./s", "--wake", "--mount", "spaces", "--user", "me@example.com"},
			uv(vm, "--user", "me@example.com", "skills", "push", "--mount=spaces", "--wake", "./s")},
		{"vms", []string{"vms", "--verbose"}, uv(vm, "--verbose", "vms")},
		{"exec keeps the command", []string{"exec", "--cwd", "/w", "--", "ls", "-la"},
			uv(vm, "exec", "--cwd=/w", "--", "ls", "-la")},
		{"logs", []string{"logs", "--tail", "5", "--agent"}, uv(vm, "logs", "--agent", "--tail=5")},
		{"logs follow", []string{"logs", "-f", "--since", "2h"}, uv(vm, "logs", "--follow", "--since=2h")},
		{"reset", []string{"--context", "ctx", "reset", "--force"}, uv(vm, "--context", "ctx", "reset", "--force")},
		{"false booleans are not forwarded", []string{"reset", "--force=false", "--verbose=false"}, uv(vm, "reset")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := devtoolBinDir(t)
			root := devtoolRepo(t)
			uvCalls := devtoolFakeTool(t, binDir, "uv", "")

			cmd := NewCraftDevCommand()
			cmd.SetArgs(c.args)
			if err := cmd.Execute(); err != nil {
				t.Fatal(err)
			}

			args := append([]string{"run", "--project", root, "--frozen", "python", filepath.Join(root, c.want[0])}, c.want[1:]...)
			want := []devtoolCall{{Dir: root, Args: args}}
			if got := devtoolCalls(t, uvCalls); !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}

func TestCraftDev_keepsTheCallerDirectoryForRelativePaths(t *testing.T) {
	binDir := devtoolBinDir(t)
	root := devtoolRepo(t)
	sub := filepath.Join(root, "work")
	if err := os.Mkdir(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(sub)
	uvCalls := devtoolFakeTool(t, binDir, "uv", "")

	cmd := NewCraftDevCommand()
	cmd.SetArgs([]string{"--profile", "p.yaml", "skills", "push", "./skills"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}

	script := filepath.Join(root, "deployment/helm/dev/craft_fc_vm.py")
	want := []devtoolCall{{Dir: sub, Args: []string{
		"run", "--project", root, "--frozen", "python", script,
		"--profile", "p.yaml", "skills", "push", "./skills",
	}}}
	if got := devtoolCalls(t, uvCalls); !reflect.DeepEqual(got, want) {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestCraftDev_execNeedsACommand(t *testing.T) {
	cmd := NewCraftDevCommand()
	cmd.SetArgs([]string{"exec"})
	cmd.SilenceUsage, cmd.SilenceErrors = true, true
	if err := cmd.Execute(); err == nil {
		t.Fatal("expected an error without a command")
	}
}
