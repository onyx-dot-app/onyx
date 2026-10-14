package pycheck

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// newBackendRepo creates a git repository, writes files under its backend
// directory, and makes the root the working directory.
func newBackendRepo(t *testing.T, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	gittest.Git(t, dir, "init", "-q")
	root, err := filepath.EvalSymlinks(dir)
	if err != nil {
		t.Fatal(err)
	}
	for name, content := range files {
		path := filepath.Join(root, "backend", filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	t.Chdir(root)
	return root
}

func readBackendFile(t *testing.T, root, name string) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(root, "backend", filepath.FromSlash(name)))
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestCheck_scansTheBackend(t *testing.T) {
	newBackendRepo(t, map[string]string{
		"onyx/a.py":      "x = getattr(o, n)\ny = 1\nz = getattr(o, m)\n",
		"onyx/b.py":      "x = o.getattr\n",
		".venv/lib/x.py": "getattr(o, n)\n",
	})

	violations, err := Check(getattrRule, nil)
	if err != nil {
		t.Fatalf("Check: %v", err)
	}

	want := []FileViolation{{
		RelPath: filepath.Join("onyx", "a.py"),
		ViolationLines: []ViolationLine{
			{LineNum: 1, Content: "x = getattr(o, n)"},
			{LineNum: 3, Content: "z = getattr(o, m)"},
		},
	}}
	if !reflect.DeepEqual(violations, want) {
		t.Fatalf("expected %+v, got %+v", want, violations)
	}
}

func TestCheck_onlyScansProvidedPaths(t *testing.T) {
	newBackendRepo(t, map[string]string{
		"onyx/a.py": "x = getattr(o, n)\n",
		"onyx/b.py": "x = 1\n",
	})

	violations, err := Check(getattrRule, []string{"onyx/b.py"})
	if err != nil || violations != nil {
		t.Fatalf("expected no violations, got %+v (%v)", violations, err)
	}
}

func TestAnnotate_marksSafeLinesAndReportsTheRest(t *testing.T) {
	root := newBackendRepo(t, map[string]string{
		"onyx/a.py":      "x = getattr(o, n)\ny = getattr(o, m)\n",
		"onyx/b.py":      "x = 1\n",
		"onyx/manual.py": "s = f\"\"\"{getattr(o, n)}\nrest\"\"\"\n",
	})

	result, err := Annotate(getattrRule, nil)
	if err != nil {
		t.Fatalf("Annotate: %v", err)
	}

	want := AnnotateResult{
		AnnotatedLines: 2,
		AnnotatedFiles: 1,
		ManualFiles: []FileViolation{{
			RelPath:        filepath.Join("onyx", "manual.py"),
			ViolationLines: []ViolationLine{{LineNum: 1, Content: "s = f\"\"\"{getattr(o, n)}"}},
		}},
	}
	if !reflect.DeepEqual(result, want) {
		t.Fatalf("expected %+v, got %+v", want, result)
	}
	if got, want := readBackendFile(t, root, "onyx/a.py"), "x = getattr(o, n)  # ods: ignore[getattr]\ny = getattr(o, m)  # ods: ignore[getattr]\n"; got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
	if got := readBackendFile(t, root, "onyx/b.py"); got != "x = 1\n" {
		t.Fatalf("expected the clean file to be left alone, got %q", got)
	}
}

func TestCheckAndAnnotate_errors(t *testing.T) {
	runners := map[string]func(paths []string) error{
		"check": func(paths []string) error {
			_, err := Check(getattrRule, paths)
			return err
		},
		"annotate": func(paths []string) error {
			_, err := Annotate(getattrRule, paths)
			return err
		},
	}
	for name, run := range runners {
		t.Run(name+" outside a repository", func(t *testing.T) {
			t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(t.TempDir()))
			t.Chdir(t.TempDir())
			if err := run(nil); err == nil {
				t.Fatal("expected an error outside a repository")
			}
		})
		t.Run(name+" with a missing path", func(t *testing.T) {
			newBackendRepo(t, map[string]string{"onyx/a.py": ""})
			if err := run([]string{"onyx/missing.py"}); err == nil {
				t.Fatal("expected an error for a missing path")
			}
		})
	}
}

func TestRelTo_fallsBackToThePath(t *testing.T) {
	if got := relTo("/backend", "onyx/a.py"); got != "onyx/a.py" {
		t.Fatalf("expected the path unchanged, got %q", got)
	}
}
