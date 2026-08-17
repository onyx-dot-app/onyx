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
		{"unit", "unit"},
		{"u", "unit"},
		{"external", "external"},
		{"edu", "external"},
		{"ext", "external"},
		{"integration", "integration"},
		{"int", "integration"},
		{"web", "web"},
		{"jest", "web"},
		{"e2e", "e2e"},
		{"playwright", "e2e"},
		{"pw", "e2e"},
		{"mobile", "mobile"},
		{"ods", "ods"},
		{"cli", "cli"},
		{"terraform", "terraform"},
		{"tf", "terraform"},
		{"backend", "backend"},
		{"py", "backend"},
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

func TestResolveByPath(t *testing.T) {
	cases := []struct {
		name       string
		file       string
		arg        string
		wantSuite  string
		wantTarget string
	}{
		{
			name:       "backend unit file",
			file:       "backend/tests/unit/onyx/test_foo.py",
			arg:        "backend/tests/unit/onyx/test_foo.py",
			wantSuite:  "unit",
			wantTarget: "tests/unit/onyx/test_foo.py",
		},
		{
			name:       "backend unit directory",
			file:       "backend/tests/unit/onyx/test_foo.py",
			arg:        "backend/tests/unit",
			wantSuite:  "unit",
			wantTarget: "tests/unit",
		},
		{
			name:       "external dependency unit",
			file:       "backend/tests/external_dependency_unit/db/test_bar.py",
			arg:        "backend/tests/external_dependency_unit/db/test_bar.py",
			wantSuite:  "external",
			wantTarget: "tests/external_dependency_unit/db/test_bar.py",
		},
		{
			name:       "integration",
			file:       "backend/tests/integration/tests/test_baz.py",
			arg:        "backend/tests/integration/tests/test_baz.py",
			wantSuite:  "integration",
			wantTarget: "tests/integration/tests/test_baz.py",
		},
		{
			name:       "other backend path falls back to the backend suite",
			file:       "backend/tests/daily/connectors/test_daily.py",
			arg:        "backend/tests/daily/connectors/test_daily.py",
			wantSuite:  "backend",
			wantTarget: "tests/daily/connectors/test_daily.py",
		},
		{
			name:       "web source test",
			file:       "web/src/lib/foo.test.ts",
			arg:        "web/src/lib/foo.test.ts",
			wantSuite:  "web",
			wantTarget: "src/lib/foo.test.ts",
		},
		{
			// The case a plain prefix map gets wrong: web/tests/e2e is also
			// under web, and the longer prefix has to win.
			name:       "e2e spec beats the web suite",
			file:       "web/tests/e2e/chat.spec.ts",
			arg:        "web/tests/e2e/chat.spec.ts",
			wantSuite:  "e2e",
			wantTarget: "tests/e2e/chat.spec.ts",
		},
		{
			name:       "mobile test",
			file:       "mobile/src/components/__tests__/foo.test.tsx",
			arg:        "mobile/src/components/__tests__/foo.test.tsx",
			wantSuite:  "mobile",
			wantTarget: "src/components/__tests__/foo.test.tsx",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root := newRepo(t, tc.file)
			suite, rest, err := Resolve(root, root, []string{tc.arg})
			if err != nil {
				t.Fatalf("Resolve(%q) failed: %v", tc.arg, err)
			}
			if suite.Name != tc.wantSuite {
				t.Fatalf("suite = %q, want %q", suite.Name, tc.wantSuite)
			}
			if !reflect.DeepEqual(rest, []string{tc.wantTarget}) {
				t.Fatalf("args = %v, want [%q]", rest, tc.wantTarget)
			}
		})
	}
}

func TestResolvePathRelativeToWorkingDirectory(t *testing.T) {
	root := newRepo(t, "backend/tests/unit/onyx/test_foo.py")
	cwd := filepath.Join(root, "backend")

	suite, rest, err := Resolve(root, cwd, []string{"tests/unit/onyx/test_foo.py"})
	if err != nil {
		t.Fatalf("Resolve failed: %v", err)
	}
	if suite.Name != "unit" {
		t.Fatalf("suite = %q, want unit", suite.Name)
	}
	if !reflect.DeepEqual(rest, []string{"tests/unit/onyx/test_foo.py"}) {
		t.Fatalf("args = %v", rest)
	}
}

// A bare filename is still a target when it is the suite selector, so it has
// to be anchored even though the same word would be left alone later in the
// argument list.
func TestResolveBareFilenameAsSelector(t *testing.T) {
	root := newRepo(t, "backend/tests/unit/onyx/test_foo.py")
	cwd := filepath.Join(root, "backend", "tests", "unit", "onyx")

	suite, rest, err := Resolve(root, cwd, []string{"test_foo.py"})
	if err != nil {
		t.Fatalf("Resolve failed: %v", err)
	}
	if suite.Name != "unit" {
		t.Fatalf("suite = %q, want unit", suite.Name)
	}
	if !reflect.DeepEqual(rest, []string{"tests/unit/onyx/test_foo.py"}) {
		t.Fatalf("args = %v", rest)
	}
}

func TestResolveKeepsPytestNodeID(t *testing.T) {
	root := newRepo(t, "backend/tests/unit/onyx/test_foo.py")

	suite, rest, err := Resolve(root, root, []string{"backend/tests/unit/onyx/test_foo.py::test_bar"})
	if err != nil {
		t.Fatalf("Resolve failed: %v", err)
	}
	if suite.Name != "unit" {
		t.Fatalf("suite = %q, want unit", suite.Name)
	}
	if !reflect.DeepEqual(rest, []string{"tests/unit/onyx/test_foo.py::test_bar"}) {
		t.Fatalf("args = %v", rest)
	}
}

// A named suite followed by a path is the form most people reach for, and the
// path still has to be rewritten relative to the suite directory or the runner
// cannot find it.
func TestResolveRewritesPathsAfterASuiteName(t *testing.T) {
	root := newRepo(t,
		"backend/tests/unit/onyx/test_foo.py",
		"web/src/lib/foo.test.ts",
	)

	t.Run("pytest", func(t *testing.T) {
		suite, rest, err := Resolve(root, root, []string{"unit", "backend/tests/unit/onyx/test_foo.py"})
		if err != nil {
			t.Fatalf("Resolve failed: %v", err)
		}
		if suite.Name != "unit" {
			t.Fatalf("suite = %q, want unit", suite.Name)
		}
		if !reflect.DeepEqual(rest, []string{"tests/unit/onyx/test_foo.py"}) {
			t.Fatalf("args = %v", rest)
		}
	})

	t.Run("jest", func(t *testing.T) {
		suite, rest, err := Resolve(root, root, []string{"web", "web/src/lib/foo.test.ts"})
		if err != nil {
			t.Fatalf("Resolve failed: %v", err)
		}
		if !reflect.DeepEqual(rest, []string{"src/lib/foo.test.ts"}) {
			t.Fatalf("args = %v", rest)
		}
		_ = suite
	})

	t.Run("flag values are left alone", func(t *testing.T) {
		_, rest, err := Resolve(root, root, []string{"unit", "-k", "web", "--tb=short"})
		if err != nil {
			t.Fatalf("Resolve failed: %v", err)
		}
		// "web" is a suite name and a real directory, but as a -k value it
		// must survive untouched.
		if !reflect.DeepEqual(rest, []string{"-k", "web", "--tb=short"}) {
			t.Fatalf("args = %v", rest)
		}
	})

	t.Run("several paths after a suite name", func(t *testing.T) {
		_, rest, err := Resolve(root, root, []string{
			"unit",
			"backend/tests/unit/onyx/test_foo.py",
			"backend/tests/unit/onyx",
		})
		if err != nil {
			t.Fatalf("Resolve failed: %v", err)
		}
		want := []string{"tests/unit/onyx/test_foo.py", "tests/unit/onyx"}
		if !reflect.DeepEqual(rest, want) {
			t.Fatalf("args = %v, want %v", rest, want)
		}
	})

	t.Run("path outside the suite is left for the runner to report", func(t *testing.T) {
		_, rest, err := Resolve(root, root, []string{"unit", "web/src/lib/foo.test.ts"})
		if err != nil {
			t.Fatalf("Resolve failed: %v", err)
		}
		if !reflect.DeepEqual(rest, []string{"web/src/lib/foo.test.ts"}) {
			t.Fatalf("args = %v", rest)
		}
	})
}

func TestResolvePassesThroughRemainingArgs(t *testing.T) {
	root := t.TempDir()

	suite, rest, err := Resolve(root, root, []string{"unit", "-k", "some_name", "--count=3"})
	if err != nil {
		t.Fatalf("Resolve failed: %v", err)
	}
	if suite.Name != "unit" {
		t.Fatalf("suite = %q, want unit", suite.Name)
	}
	if !reflect.DeepEqual(rest, []string{"-k", "some_name", "--count=3"}) {
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
		root := newRepo(t, "docs/readme.md")
		_, _, err := Resolve(root, root, []string{"docs/readme.md"})
		if err == nil {
			t.Fatal("expected an error for a path no suite covers")
		}
	})
}

func TestSuitePrefixes(t *testing.T) {
	want := map[string]string{
		"unit":        "backend/tests/unit",
		"external":    "backend/tests/external_dependency_unit",
		"integration": "backend/tests/integration",
		"web":         "web",
		"e2e":         "web/tests/e2e",
		"mobile":      "mobile",
		"ods":         "tools/ods",
		"cli":         "cli",
		"terraform":   "terraform-provider-onyx",
		"backend":     "backend/tests",
	}
	for _, suite := range All() {
		if got := suite.Prefix(); got != want[suite.Name] {
			t.Fatalf("%s prefix = %q, want %q", suite.Name, got, want[suite.Name])
		}
	}
}

// go test takes packages, not files, so a Go suite shapes its targets
// differently from the path-based runners.
func TestResolveGoTargets(t *testing.T) {
	root := newRepo(t,
		"tools/ods/main.go",
		"tools/ods/cmd/web_test.go",
		"tools/ods/internal/testsuite/testsuite_test.go",
		"cli/internal/tui/tui_test.go",
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
			args:      []string{"tools/ods/cmd/web_test.go::TestWebDir"},
			wantSuite: "ods",
			want:      []string{"./cmd", "-run", "^TestWebDir$"},
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
			name:      "flags pass through",
			args:      []string{"ods", "-run", "TestResolve", "-v"},
			wantSuite: "ods",
			want:      []string{"-run", "TestResolve", "-v"},
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

func TestHasTarget(t *testing.T) {
	tests := []struct {
		name string
		args []string
		want bool
	}{
		{name: "no args", args: nil, want: false},
		{name: "flags only", args: []string{"-k", "web"}, want: false},
		{name: "long flag only", args: []string{"--collect-only"}, want: false},
		{name: "directory", args: []string{"tests/unit/onyx"}, want: true},
		{name: "file", args: []string{"tests/unit/onyx/test_foo.py"}, want: true},
		{name: "node id", args: []string{"tests/unit/test_foo.py::test_bar"}, want: true},
		{name: "target after a flag", args: []string{"-x", "tests/unit/onyx"}, want: true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := HasTarget(tc.args); got != tc.want {
				t.Errorf("HasTarget(%v) = %v, want %v", tc.args, got, tc.want)
			}
		})
	}
}

func TestSuiteDefaultTargets(t *testing.T) {
	want := map[string]string{
		"unit":     "tests/unit",
		"external": "tests/external_dependency_unit",
		// Narrower than the prefix: the sibling directories under
		// tests/integration need a setup a plain run does not provide.
		"integration": "tests/integration/tests",
		"web":         "",
		"e2e":         "tests/e2e",
		"mobile":      "",
		"ods":         "./...",
		"cli":         "./...",
		"terraform":   "./...",
		"backend":     "tests",
	}
	for _, suite := range All() {
		if got := suite.DefaultTarget(); got != want[suite.Name] {
			t.Errorf("%s default target = %q, want %q", suite.Name, got, want[suite.Name])
		}
	}
}

// A narrowed default must not narrow inference: a path under a sibling
// directory still resolves to the suite that owns it.
func TestResolveReachesPathsOutsideTheDefaultTarget(t *testing.T) {
	root := newRepo(t, "backend/tests/integration/multitenant_tests/test_tenant.py")

	suite, args, err := Resolve(root, root, []string{"backend/tests/integration/multitenant_tests/test_tenant.py"})
	if err != nil {
		t.Fatalf("Resolve returned error: %v", err)
	}
	if suite.Name != "integration" {
		t.Fatalf("suite = %q, want integration", suite.Name)
	}
	want := []string{"tests/integration/multitenant_tests/test_tenant.py"}
	if len(args) != 1 || args[0] != want[0] {
		t.Errorf("args = %v, want %v", args, want)
	}
}
