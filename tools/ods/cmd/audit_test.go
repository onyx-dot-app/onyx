package cmd

import (
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
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

// TestAuditForwardsArgs checks that every argument, root flags included, reaches
// the auditor unchanged.
func TestAuditForwardsArgs(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake auditor is a shell script")
	}
	cases := []struct {
		name string
		argv []string
		want []string
	}{
		{"root flags", []string{"--debug", "audit", "--python"}, []string{"--debug", "--python"}},
		{"subcommand only", []string{"audit", "--python"}, []string{"--python"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			dir := t.TempDir()
			record := filepath.Join(dir, "args")
			script := "#!/bin/sh\nprintf '%s\\n' \"$@\" > " + record + "\n"
			if err := os.WriteFile(filepath.Join(dir, auditBinary), []byte(script), 0o755); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", dir)

			root := NewRootCommand()
			root.SetArgs(c.argv)
			if err := root.Execute(); err != nil {
				t.Fatalf("Execute: %v", err)
			}

			data, err := os.ReadFile(record)
			if err != nil {
				t.Fatal(err)
			}
			if got := strings.Fields(string(data)); !slices.Equal(got, c.want) {
				t.Fatalf("got %q, want %q", got, c.want)
			}
		})
	}
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
