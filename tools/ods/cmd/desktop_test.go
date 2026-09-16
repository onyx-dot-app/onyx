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
			bunCalls := devtoolFakeTool(t, binDir, "bun", "")
			npmCalls := devtoolFakeTool(t, binDir, "npm", "")

			if err := runDesktopScript(c.args); err != nil {
				t.Fatalf("runDesktopScript failed: %v", err)
			}

			// desktop is a root workspace member, so dependencies install at the root.
			if got, want := devtoolCalls(t, bunCalls), []devtoolCall{{Dir: root, Args: []string{"install", "--frozen-lockfile"}}}; !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
			if got, want := devtoolCalls(t, npmCalls), []devtoolCall{{Dir: desktopDir, Args: c.want}}; !reflect.DeepEqual(got, want) {
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
