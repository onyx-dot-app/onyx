package cmd

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
)

func TestLoadProfile(t *testing.T) {
	moduleDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(moduleDir, "go.mod"), []byte("module example.com/m\n"), 0644); err != nil {
		t.Fatal(err)
	}
	profilePath := filepath.Join(t.TempDir(), "coverage.out")
	profileText := "mode: set\nexample.com/m/pkg/a.go:1.1,2.2 1 1\nexample.com/m/pkg/a.go:3.1,4.2 1 0\n"
	if err := os.WriteFile(profilePath, []byte(profileText), 0644); err != nil {
		t.Fatal(err)
	}

	profile, gotPath, code := loadProfile(moduleDir, profilePath)
	if code != 0 {
		t.Fatalf("loadProfile exited %d", code)
	}
	if gotPath != profilePath {
		t.Errorf("path = %q, want %q", gotPath, profilePath)
	}
	want := coverage.PackageCoverage{Package: "pkg", Covered: 1, Total: 2}
	if len(profile.Packages) != 1 || profile.Packages[0] != want {
		t.Errorf("packages = %+v, want [%+v]", profile.Packages, want)
	}

	if _, _, code := loadProfile(moduleDir, filepath.Join(moduleDir, "missing.out")); code != 1 {
		t.Errorf("a missing profile exited %d, want 1", code)
	}
	if _, _, code := loadProfile(t.TempDir(), profilePath); code != 1 {
		t.Errorf("a directory without go.mod exited %d, want 1", code)
	}
}
