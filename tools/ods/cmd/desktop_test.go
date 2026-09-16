package cmd

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestRunDesktopScript_installsAtTheRootThenRunsNpm(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want string
	}{
		{"script only", []string{"dev"}, "run dev"},
		{"flags get a separator", []string{"build", "--debug"}, "run build -- --debug"},
		{"separator is not repeated", []string{"build", "--", "--debug"}, "run build -- --debug"},
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

			runDesktopScript(c.args)

			// desktop is a root workspace member, so dependencies install at the root.
			if got, want := devtoolCalls(t, bunCalls), []string{root + "|install --frozen-lockfile"}; !slices.Equal(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
			if got, want := devtoolCalls(t, npmCalls), []string{desktopDir + "|" + c.want}; !slices.Equal(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}
