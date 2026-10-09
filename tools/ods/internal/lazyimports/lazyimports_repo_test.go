package lazyimports

import (
	"os"
	"path/filepath"
	"runtime"
	"slices"
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

func TestCheckLazyImports_scansTheBackend(t *testing.T) {
	newBackendRepo(t, map[string]string{
		"onyx/a.py":           "import openai\nimport nltk\n",
		"onyx/llm/allowed.py": "import openai\nimport nltk\n",
		"onyx/partial.py":     "import nltk\n",
		"onyx/lazy.py":        "def f():\n    import openai\n",
		"tests/test_a.py":     "import openai\n",
		".venv/lib/x.py":      "import openai\n",
	})
	modules := map[string]LazyImportSettings{
		"openai": NewLazyImportSettings("onyx/llm/allowed.py"),
		"nltk":   NewLazyImportSettings("onyx/llm/allowed.py", "onyx/partial.py"),
	}

	violations, violated, err := CheckLazyImports(modules, nil)
	if err != nil {
		t.Fatalf("CheckLazyImports: %v", err)
	}

	if len(violations) != 1 {
		t.Fatalf("expected one file with violations, got %+v", violations)
	}
	v := violations[0]
	if v.RelPath != filepath.Join("onyx", "a.py") {
		t.Fatalf("expected onyx/a.py, got %q", v.RelPath)
	}
	if got := extractLineNumbers(v.ViolationLines); !slices.Equal(got, []int{1, 2}) {
		t.Fatalf("expected lines [1 2], got %v", got)
	}
	if got := FormatViolatedModules(violated); got != "nltk, openai" {
		t.Fatalf("expected nltk and openai, got %q", got)
	}
}

func TestCheckLazyImports_providedPaths(t *testing.T) {
	modules := map[string]LazyImportSettings{"openai": NewLazyImportSettings()}

	t.Run("a clean file has no violations", func(t *testing.T) {
		newBackendRepo(t, map[string]string{"onyx/lazy.py": "def f():\n    import openai\n"})
		violations, violated, err := CheckLazyImports(modules, []string{"onyx/lazy.py"})
		if err != nil || violations != nil || violated == nil || len(violated) != 0 {
			t.Fatalf("expected a scan with no violations, got %v %v %v", violations, violated, err)
		}
	})
	t.Run("paths without python files skip the scan", func(t *testing.T) {
		newBackendRepo(t, map[string]string{"onyx/README.md": "import openai\n"})
		violations, violated, err := CheckLazyImports(modules, []string{"onyx"})
		if err != nil || violations != nil || violated != nil {
			t.Fatalf("expected no scan, got %v %v %v", violations, violated, err)
		}
	})
	t.Run("a missing path is an error", func(t *testing.T) {
		newBackendRepo(t, map[string]string{"onyx/a.py": ""})
		if _, _, err := CheckLazyImports(modules, []string{"onyx/missing.py"}); err == nil {
			t.Fatal("expected an error for a missing path")
		}
	})
	t.Run("an unreadable file is an error", func(t *testing.T) {
		if runtime.GOOS == "windows" {
			t.Skip("creating a symlink needs extra privileges on Windows")
		}
		root := newBackendRepo(t, map[string]string{"onyx/a.py": ""})
		if err := os.Symlink(filepath.Join(root, "gone.py"), filepath.Join(root, "backend", "onyx", "b.py")); err != nil {
			t.Fatal(err)
		}
		if _, _, err := CheckLazyImports(modules, nil); err == nil {
			t.Fatal("expected an error for a dangling link")
		}
	})
	t.Run("outside a repository is an error", func(t *testing.T) {
		t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(t.TempDir()))
		t.Chdir(t.TempDir())
		if _, _, err := CheckLazyImports(modules, nil); err == nil {
			t.Fatal("expected an error outside a repository")
		}
	})
}
