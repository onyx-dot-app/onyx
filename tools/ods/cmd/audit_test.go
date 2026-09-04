package cmd

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// writeAuditBinary drops an executable named ods-audit in dir.
func writeAuditBinary(t *testing.T, dir string) string {
	t.Helper()
	name := auditBinary
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLookupAuditBinary(t *testing.T) {
	t.Run("prefers the binary next to ods", func(t *testing.T) {
		exeDir := t.TempDir()
		want := writeAuditBinary(t, exeDir)
		t.Setenv("PATH", t.TempDir())

		got, err := lookupAuditBinary(exeDir)
		if err != nil {
			t.Fatalf("lookupAuditBinary: %v", err)
		}
		if got != want {
			t.Fatalf("got %q, want %q", got, want)
		}
	})

	t.Run("falls back to PATH", func(t *testing.T) {
		pathDir := t.TempDir()
		want := writeAuditBinary(t, pathDir)
		t.Setenv("PATH", pathDir)

		got, err := lookupAuditBinary(t.TempDir())
		if err != nil {
			t.Fatalf("lookupAuditBinary: %v", err)
		}
		if got != want {
			t.Fatalf("got %q, want %q", got, want)
		}
	})

	t.Run("errors when the audit extra is not installed", func(t *testing.T) {
		t.Setenv("PATH", t.TempDir())

		if got, err := lookupAuditBinary(t.TempDir()); err == nil {
			t.Fatalf("expected an error, got %q", got)
		}
	})
}

func TestWantsHelp(t *testing.T) {
	cases := []struct {
		args []string
		want bool
	}{
		{nil, true},
		{[]string{"--help"}, true},
		{[]string{"ignore", "-h"}, true},
		{[]string{"--python"}, false},
	}
	for _, c := range cases {
		if got := wantsHelp(c.args); got != c.want {
			t.Errorf("wantsHelp(%q) = %v, want %v", c.args, got, c.want)
		}
	}
}
