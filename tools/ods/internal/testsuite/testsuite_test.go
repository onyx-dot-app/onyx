package testsuite

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// newRepo builds a temp directory holding the paths a caller might name, so
// Resolve's existence checks have something real to stat.
func newRepo(t *testing.T, paths ...string) string {
	t.Helper()
	root := t.TempDir()
	for _, p := range paths {
		full := filepath.Join(root, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

func TestResolveByName(t *testing.T) {
	cases := []struct {
		arg  string
		want string
	}{
		{"ods", "ods"},
		{"cli", "cli"},
		{"terraform", "terraform"},
		{"tf", "terraform"},
	}

	root := t.TempDir()
	for _, tc := range cases {
		t.Run(tc.arg, func(t *testing.T) {
			suite, rest, err := Resolve(root, root, []string{tc.arg})
			if err != nil {
				t.Fatalf("Resolve(%q) failed: %v", tc.arg, err)
			}
			if suite.Name != tc.want {
				t.Fatalf("Resolve(%q) = %q, want %q", tc.arg, suite.Name, tc.want)
			}
			if len(rest) != 0 {
				t.Fatalf("expected no remaining args, got %v", rest)
			}
		})
	}
}

// go test takes packages, not files, so targets are shaped into "./..."
// patterns and node ids into -run filters.
func TestResolveGoTargets(t *testing.T) {
	root := newRepo(t,
		"tools/ods/main.go",
		"tools/ods/cmd/env_test.go",
		"tools/ods/internal/testsuite/testsuite_test.go",
		"cli/internal/tui/tui_test.go",
		"terraform-provider-onyx/internal/provider/provider_test.go",
	)

	cases := []struct {
		name      string
		args      []string
		wantSuite string
		want      []string
	}{
		{
			name:      "package directory",
			args:      []string{"tools/ods/internal/testsuite"},
			wantSuite: "ods",
			want:      []string{"./internal/testsuite"},
		},
		{
			name:      "file runs its package",
			args:      []string{"tools/ods/internal/testsuite/testsuite_test.go"},
			wantSuite: "ods",
			want:      []string{"./internal/testsuite"},
		},
		{
			name:      "module root",
			args:      []string{"tools/ods"},
			wantSuite: "ods",
			want:      []string{"./..."},
		},
		{
			name:      "node id becomes a run filter",
			args:      []string{"tools/ods/cmd/env_test.go::TestGenerateEnv"},
			wantSuite: "ods",
			want:      []string{"./cmd", "-run", "^TestGenerateEnv$"},
		},
		{
			name:      "path after a suite name",
			args:      []string{"ods", "tools/ods/cmd"},
			wantSuite: "ods",
			want:      []string{"./cmd"},
		},
		{
			name:      "a second module",
			args:      []string{"cli/internal/tui"},
			wantSuite: "cli",
			want:      []string{"./internal/tui"},
		},
		{
			name:      "a third module",
			args:      []string{"terraform-provider-onyx/internal/provider"},
			wantSuite: "terraform",
			want:      []string{"./internal/provider"},
		},
		{
			name:      "path relative to the module",
			args:      []string{"ods", "internal/testsuite"},
			wantSuite: "ods",
			want:      []string{"./internal/testsuite"},
		},
		{
			name:      "node id relative to the module",
			args:      []string{"cli", "internal/tui/tui_test.go::TestChat"},
			wantSuite: "cli",
			want:      []string{"./internal/tui", "-run", "^TestChat$"},
		},
		{
			name:      "flags pass through",
			args:      []string{"ods", "-run", "TestResolve", "-v"},
			wantSuite: "ods",
			want:      []string{"-run", "TestResolve", "-v"},
		},
		{
			// A path outside the named suite is left alone, so go test
			// reports it rather than us silently pointing somewhere else.
			name:      "path outside the suite is left for the runner to report",
			args:      []string{"ods", "cli/internal/tui"},
			wantSuite: "ods",
			want:      []string{"cli/internal/tui"},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			suite, args, err := Resolve(root, root, tc.args)
			if err != nil {
				t.Fatalf("Resolve(%v) failed: %v", tc.args, err)
			}
			if suite.Name != tc.wantSuite {
				t.Fatalf("suite = %q, want %q", suite.Name, tc.wantSuite)
			}
			if !reflect.DeepEqual(args, tc.want) {
				t.Errorf("args = %v, want %v", args, tc.want)
			}
		})
	}
}

func TestResolvePathRelativeToWorkingDirectory(t *testing.T) {
	root := newRepo(t, "tools/ods/internal/testsuite/testsuite_test.go")
	cwd := filepath.Join(root, "tools", "ods")

	suite, rest, err := Resolve(root, cwd, []string{"internal/testsuite"})
	if err != nil {
		t.Fatalf("Resolve failed: %v", err)
	}
	if suite.Name != "ods" {
		t.Fatalf("suite = %q, want ods", suite.Name)
	}
	if !reflect.DeepEqual(rest, []string{"./internal/testsuite"}) {
		t.Fatalf("args = %v", rest)
	}
}

// A bare filename is still a target when it is the suite selector, so it has
// to be anchored even though the same word would be left alone later in the
// argument list.
func TestResolveBareFilenameAsSelector(t *testing.T) {
	root := newRepo(t, "tools/ods/internal/testsuite/testsuite_test.go")
	cwd := filepath.Join(root, "tools", "ods", "internal", "testsuite")

	suite, rest, err := Resolve(root, cwd, []string{"testsuite_test.go"})
	if err != nil {
		t.Fatalf("Resolve failed: %v", err)
	}
	if suite.Name != "ods" {
		t.Fatalf("suite = %q, want ods", suite.Name)
	}
	if !reflect.DeepEqual(rest, []string{"./internal/testsuite"}) {
		t.Fatalf("args = %v", rest)
	}
}

func TestResolveErrors(t *testing.T) {
	t.Run("no args", func(t *testing.T) {
		root := t.TempDir()
		if _, _, err := Resolve(root, root, nil); !errors.Is(err, ErrNoArgs) {
			t.Fatalf("err = %v, want ErrNoArgs", err)
		}
	})

	t.Run("unknown suite", func(t *testing.T) {
		root := t.TempDir()
		_, _, err := Resolve(root, root, []string{"bogus"})
		if err == nil {
			t.Fatal("expected an error for an unknown suite")
		}
		// The message has to name the alternatives, since that is the only
		// discovery path a mistyped suite gets.
		for _, name := range Names() {
			if !strings.Contains(err.Error(), name) {
				t.Fatalf("error %q does not mention suite %q", err, name)
			}
		}
	})

	t.Run("path outside every suite", func(t *testing.T) {
		root := newRepo(t, "backend/tests/unit/test_foo.py")
		_, _, err := Resolve(root, root, []string{"backend/tests/unit/test_foo.py"})
		if err == nil {
			t.Fatal("expected an error for a path no suite covers")
		}
	})
}

func TestHasTarget(t *testing.T) {
	tests := []struct {
		name string
		args []string
		want bool
	}{
		{name: "no args", args: nil, want: false},
		{name: "flags only", args: []string{"-run", "TestFoo"}, want: false},
		{name: "long flag only", args: []string{"-v"}, want: false},
		{name: "package pattern", args: []string{"./..."}, want: true},
		{name: "package directory", args: []string{"./cmd"}, want: true},
		{name: "run filter after a package", args: []string{"./cmd", "-run", "^TestFoo$"}, want: true},
		{name: "target after a flag", args: []string{"-v", "./internal/testsuite"}, want: true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := HasTarget(tc.args); got != tc.want {
				t.Errorf("HasTarget(%v) = %v, want %v", tc.args, got, tc.want)
			}
		})
	}
}
