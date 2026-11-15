package cmd

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestRunDesktopScript_installsAtTheRootThenRunsNpm(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want []string
	}{
		{"script only", []string{"dev"}, []string{"run", "dev"}},
		{"flags get a separator", []string{"build", "--debug"}, []string{"run", "build", "--", "--debug"}},
		{"separator is not repeated", []string{"build", "--", "--debug"}, []string{"run", "build", "--", "--debug"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := devtoolBinDir(t)
			root := devtoolRepo(t)
			desktopDir := filepath.Join(root, "desktop")
			if err := os.MkdirAll(desktopDir, 0o755); err != nil {
				t.Fatal(err)
			}
			calls := desktopSharedCallLog(t, binDir, "bun", "npm")

			if err := runDesktopScript(c.args); err != nil {
				t.Fatalf("runDesktopScript failed: %v", err)
			}

			// desktop is a root workspace member, so dependencies install at the root
			// before npm runs the script.
			want := []devtoolCall{
				{Dir: root, Args: []string{"bun", "install", "--frozen-lockfile"}},
				{Dir: desktopDir, Args: append([]string{"npm"}, c.want...)},
			}
			if got := devtoolCalls(t, calls); !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}

func TestRunDesktopScript_failures(t *testing.T) {
	t.Run("outside a repository", func(t *testing.T) {
		devtoolBinDir(t)
		gitrelChdirOutsideRepo(t)

		err := runDesktopScript([]string{"dev"})

		if err == nil || !strings.HasPrefix(err.Error(), "Failed to find desktop directory: ") {
			t.Fatalf("expected a desktop directory error, got %v", err)
		}
	})

	t.Run("bun install fails", func(t *testing.T) {
		binDir := devtoolBinDir(t)
		devtoolRepo(t)
		devtoolFakeTool(t, binDir, "bun", "exit 3")
		npmCalls := devtoolFakeTool(t, binDir, "npm", "")

		err := runDesktopScript([]string{"dev"})

		if err == nil || err.Error() != "Failed to run bun install: exit status 3" {
			t.Fatalf("expected a bun install error, got %v", err)
		}
		if calls := devtoolCalls(t, npmCalls); calls != nil {
			t.Fatalf("expected npm not to run, got %q", calls)
		}
	})
}

// desktopSharedCallLog installs a fake for each tool that records
// its calls into one shared log in the devtoolCalls format, with the tool name
// as the first argument, so tests can check call order.
func desktopSharedCallLog(t *testing.T, binDir string, tools ...string) string {
	t.Helper()
	calls := filepath.Join(binDir, "shared.calls")
	for _, tool := range tools {
		script := "#!/bin/sh\nprintf '%s\\0' \"$(pwd -P)\" \"$(($# + 1))\" \"${0##*/}\" \"$@\" >> \"${0%/*}/shared.calls\"\n"
		if err := os.WriteFile(filepath.Join(binDir, tool), []byte(script), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	return calls
}
