package cmd

import (
	"path/filepath"
	"slices"
	"testing"
)

func TestRunTest_runsGoTestInTheSuiteDir(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want string
	}{
		{"bare suite covers the module", []string{"ods"}, "test -race ./..."},
		{"runner flags follow the catch-all target", []string{"ods", "--", "-run", "TestX"}, "test -race ./... -run TestX"},
		{"a path picks the package", []string{"tools/ods/internal/foo/foo_test.go", "--", "-v"}, "test -race ./internal/foo -v"},
		{"only the first separator is dropped", []string{"ods", "-args", "--", "x", "--", "y"}, "test -race ./... -args x -- y"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := devtoolBinDir(t)
			root := devtoolRepo(t)
			suiteDir := filepath.Join(root, "tools", "ods")
			writeFile(t, filepath.Join(suiteDir, "internal", "foo", "foo_test.go"), "package foo\n")
			goCalls := devtoolFakeTool(t, binDir, "go", "")

			runTest(NewTestCommand(), c.args)

			want := []string{suiteDir + "|" + c.want}
			if got := devtoolCalls(t, goCalls); !slices.Equal(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}

func TestRunTest_resolvesPathsFromTheWorkingDirectory(t *testing.T) {
	binDir := devtoolBinDir(t)
	root := devtoolRepo(t)
	suiteDir := filepath.Join(root, "tools", "ods")
	writeFile(t, filepath.Join(suiteDir, "internal", "foo", "foo_test.go"), "package foo\n")
	goCalls := devtoolFakeTool(t, binDir, "go", "")
	t.Chdir(filepath.Join(suiteDir, "internal"))

	runTest(NewTestCommand(), []string{"foo"})

	want := []string{suiteDir + "|test -race ./internal/foo"}
	if got := devtoolCalls(t, goCalls); !slices.Equal(got, want) {
		t.Fatalf("expected %q, got %q", want, got)
	}
}
