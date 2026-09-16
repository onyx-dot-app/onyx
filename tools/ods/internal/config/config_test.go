package config

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// useTempConfigHome points the config file at a temporary directory and
// returns its path, so a test never reads or writes the developer's own
// config.
func useTempConfigHome(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("ConfigDir reads APPDATA on Windows, not XDG_CONFIG_HOME")
	}
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	return paths.ConfigFilePath()
}

func TestLoad_missingFileIsAFreshConfig(t *testing.T) {
	path := useTempConfigHome(t)

	cfg, err := Load()

	if err != nil {
		t.Fatalf("Load failed on a missing file: %v", err)
	}
	if *cfg != (Config{}) {
		t.Fatalf("expected a zero-valued config, got %+v", *cfg)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("Load must not create %s", path)
	}
}

func TestSaveAndLoad_roundTrip(t *testing.T) {
	path := useTempConfigHome(t)
	original := &Config{
		Deploy:     DeployConfig{TargetRepo: "onyx-dot-app/onyx"},
		DeployEdge: DeployCommandConfig{TargetWorkflow: "deploy-edge.yml"},
		DeployWiki: DeployCommandConfig{TargetWorkflow: "deploy-wiki.yml"},
	}

	// Save creates the config directory, which the temporary home lacks.
	if err := Save(original); err != nil {
		t.Fatalf("Save failed: %v", err)
	}

	if _, err := os.Stat(path); err != nil {
		t.Fatalf("expected the config at %s: %v", path, err)
	}
	loaded, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}
	if *loaded != *original {
		t.Fatalf("expected %+v, got %+v", *original, *loaded)
	}
}

func TestLoad_reportsInvalidJSON(t *testing.T) {
	path := useTempConfigHome(t)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("Failed to create the config directory: %v", err)
	}
	if err := os.WriteFile(path, []byte("{not json"), 0o644); err != nil {
		t.Fatalf("Failed to write the config file: %v", err)
	}

	if _, err := Load(); err == nil {
		t.Fatal("expected an error for a malformed config file")
	}
}
