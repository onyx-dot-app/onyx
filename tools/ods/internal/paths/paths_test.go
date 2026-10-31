package paths

import (
	"os"
	"path/filepath"
	"testing"
)

// writeFile creates path with parent directories and dummy content.
func writeFile(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("Failed to create directory: %v", err)
	}
	if err := os.WriteFile(path, []byte("x = 1\n"), 0o644); err != nil {
		t.Fatalf("Failed to write file: %v", err)
	}
}

func TestResolveInBackend(t *testing.T) {
	// Precondition.
	// A repository-shaped tree with files inside and outside the backend
	// directory.
	root := t.TempDir()
	backendDir := filepath.Join(root, "backend")
	inside := filepath.Join(backendDir, "pkg", "a.py")
	outside := filepath.Join(root, "outside.py")
	writeFile(t, inside)
	writeFile(t, outside)
	escapeLink := filepath.Join(backendDir, "link.py")
	if err := os.Symlink(outside, escapeLink); err != nil {
		t.Fatalf("Failed to create symlink: %v", err)
	}
	internalLink := filepath.Join(backendDir, "alias.py")
	if err := os.Symlink(inside, internalLink); err != nil {
		t.Fatalf("Failed to create symlink: %v", err)
	}

	tests := []struct {
		name     string
		selector string
		// want is the expected resolved path; empty means an error is expected.
		want string
	}{
		{name: "backend-relative", selector: filepath.Join("pkg", "a.py"), want: inside},
		{name: "repo-root-relative", selector: filepath.Join("backend", "pkg", "a.py"), want: inside},
		{name: "absolute inside", selector: inside, want: inside},
		{name: "backend directory itself", selector: backendDir, want: backendDir},
		{name: "dotdot escape rejected despite existing target", selector: filepath.Join("..", "outside.py"), want: ""},
		{name: "absolute outside rejected despite existing target", selector: outside, want: ""},
		{name: "symlink escaping the backend rejected", selector: "link.py", want: ""},
		{name: "symlink staying inside the backend accepted", selector: "alias.py", want: internalLink},
		{name: "nonexistent", selector: filepath.Join("nope", "missing.py"), want: ""},
	}

	// Under test and postcondition.
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, info, err := ResolveInBackend(tt.selector, backendDir)
			if tt.want == "" {
				if err == nil {
					t.Fatalf("Expected an error for selector %q, got %q", tt.selector, got)
				}
				return
			}
			if err != nil {
				t.Fatalf("ResolveInBackend(%q) failed: %v", tt.selector, err)
			}
			if got != tt.want || info == nil {
				t.Fatalf("Expected %q with file info, got %q", tt.want, got)
			}
		})
	}
}
