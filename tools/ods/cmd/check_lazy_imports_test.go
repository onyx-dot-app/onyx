package cmd

import (
	"bytes"
	"path/filepath"
	"strings"
	"testing"
)

func TestRunCheckLazyImports_namesEveryEagerModule(t *testing.T) {
	root := devtoolRepo(t)
	writeFile(t, filepath.Join(root, "backend", "onyx", "llm.py"), "import tiktoken\nfrom openai import OpenAI\n")
	writeFile(t, filepath.Join(root, "backend", "onyx", "chat.py"), "import os\n")

	var stderr bytes.Buffer
	clean, err := runCheckLazyImports(nil, &stderr)
	if err != nil {
		t.Fatalf("runCheckLazyImports: %v", err)
	}

	if clean {
		t.Fatal("expected violations")
	}
	if got, want := stderr.String(), "\nFound eager imports of openai, tiktoken. You must import them only when needed.\n"; got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestRunCheckLazyImports_passesFunctionLevelImports(t *testing.T) {
	root := devtoolRepo(t)
	writeFile(t, filepath.Join(root, "backend", "onyx", "llm.py"), "def f():\n    import openai\n")

	var stderr bytes.Buffer
	clean, err := runCheckLazyImports([]string{"onyx/llm.py"}, &stderr)
	if err != nil {
		t.Fatalf("runCheckLazyImports: %v", err)
	}
	if !clean || stderr.Len() != 0 {
		t.Fatalf("expected a clean run, got clean=%v stderr=%q", clean, stderr.String())
	}
}

func TestRunCheckLazyImports_rejectsUnknownPaths(t *testing.T) {
	root := devtoolRepo(t)
	writeFile(t, filepath.Join(root, "backend", "onyx", "llm.py"), "")

	_, err := runCheckLazyImports([]string{"onyx/missing.py"}, &bytes.Buffer{})
	if err == nil || !strings.HasPrefix(err.Error(), "Error checking lazy imports: ") {
		t.Fatalf("expected a lazy import error, got %v", err)
	}
}
