//go:build linux

package files

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestRenameMovesOrSwapsInOneDirectory(t *testing.T) {
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := New(Config{SessionsRoot: filepath.Join(dir, "sessions")})
	if err != nil {
		t.Fatal(err)
	}
	write := func(p, data string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(data), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	read := func(p string) string {
		t.Helper()
		b, err := os.ReadFile(p)
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	skills := dir + "/skills"
	write(skills+"/.copy-1/SKILL.md", "v1")

	// The first copy: a plain rename.
	if err := s.Rename("", skills+"/.copy-1", skills+"/report", false); err != nil {
		t.Fatal(err)
	}
	if got := read(skills + "/report/SKILL.md"); got != "v1" {
		t.Fatalf("report holds %q", got)
	}

	// A new version swaps with the old folder in one step.
	write(skills+"/.copy-2/SKILL.md", "v2")
	if err := s.Rename("", skills+"/.copy-2", skills+"/report", true); err != nil {
		t.Fatal(err)
	}
	if got := read(skills + "/report/SKILL.md"); got != "v2" {
		t.Fatalf("report holds %q after the swap", got)
	}
	if got := read(skills + "/.copy-2/SKILL.md"); got != "v1" {
		t.Fatalf("the old folder holds %q after the swap", got)
	}

	for name, c := range map[string]struct {
		err  error
		call func() error
	}{
		"no replace":         {ErrExists, func() error { return s.Rename("", skills+"/.copy-2", skills+"/report", false) }},
		"exchange, no to":    {ErrNotFound, func() error { return s.Rename("", skills+"/.copy-2", skills+"/gone", true) }},
		"missing from":       {ErrNotFound, func() error { return s.Rename("", skills+"/gone", skills+"/report", true) }},
		"other directory":    {ErrInvalid, func() error { return s.Rename("", skills+"/.copy-2", dir+"/report", false) }},
		"same name":          {ErrInvalid, func() error { return s.Rename("", skills+"/report", skills+"/report", true) }},
		"session":            {ErrInvalid, func() error { return s.Rename(sid, "a", "b", false) }},
		"denied destination": {ErrInvalid, func() error { return s.Rename("", "/proc/x", "/proc/y", false) }},
	} {
		if err := c.call(); !errors.Is(err, c.err) {
			t.Fatalf("%s: %v, want %v", name, err, c.err)
		}
	}
	if got := read(skills + "/report/SKILL.md"); got != "v2" {
		t.Fatalf("a refused rename changed report to %q", got)
	}
}
