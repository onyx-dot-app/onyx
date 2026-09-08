package backendenv

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestEnsureFile(t *testing.T) {
	t.Run("creates the file from the template", func(t *testing.T) {
		root := t.TempDir()
		writeFile(t, filepath.Join(root, ".vscode", "env_template.txt"), "FOO=<REPLACE THIS>\n")

		path, err := EnsureFile(root)
		if err != nil {
			t.Fatalf("EnsureFile failed: %v", err)
		}
		if want := filepath.Join(root, ".vscode", ".env"); path != want {
			t.Fatalf("path = %q, want %q", path, want)
		}
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if string(data) != "FOO=<REPLACE THIS>\n" {
			t.Fatalf("content = %q, want the template", string(data))
		}
	})

	t.Run("keeps an existing file", func(t *testing.T) {
		root := t.TempDir()
		writeFile(t, filepath.Join(root, ".vscode", "env_template.txt"), "FOO=template\n")
		envPath := filepath.Join(root, ".vscode", ".env")
		writeFile(t, envPath, "FOO=mine\n")

		if _, err := EnsureFile(root); err != nil {
			t.Fatalf("EnsureFile failed: %v", err)
		}
		data, err := os.ReadFile(envPath)
		if err != nil {
			t.Fatal(err)
		}
		if string(data) != "FOO=mine\n" {
			t.Fatalf("content = %q, want the file left alone", string(data))
		}
	})

	t.Run("reports a missing template", func(t *testing.T) {
		if _, err := EnsureFile(t.TempDir()); err == nil {
			t.Fatal("expected an error when the template is missing")
		}
	})
}

func TestLoad(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, ".env")
	writeFile(t, path, `# a comment
FOO=bar

QUOTED="has spaces"
SINGLE='single'
SPACED = padded
EQUALS=a=b
=novalue
`)

	got, err := Load(path)
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}
	want := []string{
		"FOO=bar",
		`QUOTED=has spaces`,
		"SINGLE=single",
		"SPACED=padded",
		"EQUALS=a=b",
	}
	if !slices.Equal(got, want) {
		t.Errorf("Load = %q, want %q", got, want)
	}
}

func TestLoadMissingFile(t *testing.T) {
	if _, err := Load(filepath.Join(t.TempDir(), "nope")); err == nil {
		t.Fatal("expected an error for a missing file")
	}
}

func TestMergeShellWins(t *testing.T) {
	shell := []string{"FOO=from-shell", "BARE"}
	file := []string{"FOO=from-file", "NEW=from-file"}

	got := Merge(shell, file)
	want := []string{"FOO=from-shell", "BARE", "NEW=from-file"}
	if !slices.Equal(got, want) {
		t.Errorf("Merge = %q, want %q", got, want)
	}
}

func TestMergeLeavesTheShellSliceAlone(t *testing.T) {
	shell := []string{"FOO=from-shell"}
	Merge(shell, []string{"NEW=from-file"})
	if len(shell) != 1 || shell[0] != "FOO=from-shell" {
		t.Errorf("shell env was modified: %q", shell)
	}
}

func TestEEDefaults(t *testing.T) {
	on := EEDefaults(false)
	if !slices.Contains(on, "ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true") {
		t.Errorf("EEDefaults(false) = %q, want EE enabled", on)
	}
	if !slices.Contains(on, "LICENSE_ENFORCEMENT_ENABLED=false") {
		t.Errorf("EEDefaults(false) = %q, want license enforcement off", on)
	}

	off := EEDefaults(true)
	if !slices.Equal(off, []string{"ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=false"}) {
		t.Errorf("EEDefaults(true) = %q, want EE disabled only", off)
	}
}
