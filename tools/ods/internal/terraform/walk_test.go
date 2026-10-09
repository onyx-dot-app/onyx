package terraform

import (
	"os"
	"path/filepath"
	"testing"
)

func writeFile(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("a = 1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestDiscover(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "main.tf"))
	writeFile(t, filepath.Join(dir, "modules", "vpc", "main.tf"))
	writeFile(t, filepath.Join(dir, "modules", "vpc", "README.md"))
	// Vendored providers are not ours to check.
	writeFile(t, filepath.Join(dir, ".terraform", "modules", "vendored.tf"))
	writeFile(t, filepath.Join(dir, "node_modules", "pkg", "fixture.tf"))

	got, err := Discover([]string{dir})
	if err != nil {
		t.Fatal(err)
	}

	want := []string{
		filepath.Join(dir, "main.tf"),
		filepath.Join(dir, "modules", "vpc", "main.tf"),
	}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range got {
		if got[i] != want[i] {
			t.Errorf("entry %d: got %q, want %q", i, got[i], want[i])
		}
	}
}

func TestDiscoverExplicitPaths(t *testing.T) {
	dir := t.TempDir()
	tf := filepath.Join(dir, "main.tf")
	md := filepath.Join(dir, "README.md")
	vendored := filepath.Join(dir, ".terraform", "vendored.tf")
	writeFile(t, tf)
	writeFile(t, md)
	writeFile(t, vendored)

	// A non-Terraform file and a vendored one are dropped even when named
	// explicitly, because pre-commit passes whatever the commit touched.
	got, err := Discover([]string{tf, md, vendored, tf})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0] != tf {
		t.Fatalf("got %v, want [%s]", got, tf)
	}
}

func TestDiscoverNoRoots(t *testing.T) {
	got, err := Discover(nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Fatalf("got %v, want none", got)
	}
}

func TestDiscoverMissingPath(t *testing.T) {
	if _, err := Discover([]string{filepath.Join(t.TempDir(), "absent")}); err == nil {
		t.Fatal("expected an error for a missing path")
	}
}
