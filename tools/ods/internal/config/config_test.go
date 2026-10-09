package config

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
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

	_, err := Load()
	if err == nil || !strings.HasPrefix(err.Error(), "failed to parse config file "+path+": ") {
		t.Fatalf("expected a parse error naming %s, got %v", path, err)
	}
}

func TestLoad_reportsAnUnreadableFile(t *testing.T) {
	path := useTempConfigHome(t)
	// A directory in place of the file fails with an error other than "not
	// exist", so Load must not treat it as a first run.
	if err := os.MkdirAll(path, 0o755); err != nil {
		t.Fatalf("Failed to create the directory: %v", err)
	}

	cfg, err := Load()

	if err == nil || !strings.HasPrefix(err.Error(), "failed to read config file "+path) {
		t.Fatalf("expected a read error, got config %+v and error %v", cfg, err)
	}
}

func TestSave_reportsFailures(t *testing.T) {
	t.Run("config directory cannot be created", func(t *testing.T) {
		useTempConfigHome(t)
		blocker := filepath.Join(t.TempDir(), "file")
		if err := os.WriteFile(blocker, nil, 0o644); err != nil {
			t.Fatal(err)
		}
		t.Setenv("XDG_CONFIG_HOME", blocker)

		err := Save(&Config{})

		if err == nil || !strings.HasPrefix(err.Error(), "failed to create config directory: ") {
			t.Fatalf("expected a directory error, got %v", err)
		}
	})

	t.Run("config file cannot be written", func(t *testing.T) {
		path := useTempConfigHome(t)
		if err := os.MkdirAll(path, 0o755); err != nil {
			t.Fatalf("Failed to create the directory: %v", err)
		}

		err := Save(&Config{})

		if err == nil || !strings.HasPrefix(err.Error(), "failed to write config file "+path) {
			t.Fatalf("expected a write error, got %v", err)
		}
	})
}
