package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)


func clearEnvVars(t *testing.T) {
	t.Helper()
	for _, key := range []string{EnvServerURL, EnvAPIKey, EnvAgentID} {
		t.Setenv(key, "")
		os.Unsetenv(key)
	}
}

func TestDefaultConfig(t *testing.T) {
	cfg := DefaultConfig()
	if cfg.ServerURL != "http://localhost:3000" {
		t.Errorf("expected default server URL, got %s", cfg.ServerURL)
	}
	if cfg.APIKey != "" {
		t.Errorf("expected empty API key, got %s", cfg.APIKey)
	}
	if cfg.DefaultAgentID != 0 {
		t.Errorf("expected default agent ID 0, got %d", cfg.DefaultAgentID)
	}
}

func TestIsConfigured(t *testing.T) {
	cfg := DefaultConfig()
	if cfg.IsConfigured() {
		t.Error("empty config should not be configured")
	}
	cfg.APIKey = "some-key"
	if !cfg.IsConfigured() {
		t.Error("config with API key should be configured")
	}
}

func TestLoadDefaults(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)

	cfg := Load()
	if cfg.ServerURL != "http://localhost:3000" {
		t.Errorf("expected default URL, got %s", cfg.ServerURL)
	}
	if cfg.APIKey != "" {
		t.Errorf("expected empty key, got %s", cfg.APIKey)
	}
}

func TestLoadFromFile(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)

	onyxDir := filepath.Join(dir, "onyx-cli")
	os.MkdirAll(onyxDir, 0o755)

	data, _ := json.Marshal(map[string]interface{}{
		"server_url":        "https://my-onyx.example.com",
		"api_key":           "test-key-123",
		"default_persona_id": 5,
	})
	os.WriteFile(filepath.Join(onyxDir, "config.json"), data, 0o644)

	cfg := Load()
	if cfg.ServerURL != "https://my-onyx.example.com" {
		t.Errorf("got %s", cfg.ServerURL)
	}
	if cfg.APIKey != "test-key-123" {
		t.Errorf("got %s", cfg.APIKey)
	}
	if cfg.DefaultAgentID != 5 {
		t.Errorf("got %d", cfg.DefaultAgentID)
	}
}

func TestLoadCorruptFile(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)

	onyxDir := filepath.Join(dir, "onyx-cli")
	os.MkdirAll(onyxDir, 0o755)
	os.WriteFile(filepath.Join(onyxDir, "config.json"), []byte("not valid json {{{"), 0o644)

	cfg := Load()
	if cfg.ServerURL != "http://localhost:3000" {
		t.Errorf("expected default URL on corrupt file, got %s", cfg.ServerURL)
	}
}

func TestEnvOverrideServerURL(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv(EnvServerURL, "https://env-override.com")

	cfg := Load()
	if cfg.ServerURL != "https://env-override.com" {
		t.Errorf("got %s", cfg.ServerURL)
	}
}

func TestEnvOverrideAPIKey(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv(EnvAPIKey, "env-key")

	cfg := Load()
	if cfg.APIKey != "env-key" {
		t.Errorf("got %s", cfg.APIKey)
	}
}

func TestEnvOverrideAgentID(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv(EnvAgentID, "42")

	cfg := Load()
	if cfg.DefaultAgentID != 42 {
		t.Errorf("got %d", cfg.DefaultAgentID)
	}
}

func TestEnvOverrideInvalidAgentID(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv(EnvAgentID, "not-a-number")

	cfg := Load()
	if cfg.DefaultAgentID != 0 {
		t.Errorf("got %d", cfg.DefaultAgentID)
	}
}

func TestEnvOverridesFileValues(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)

	onyxDir := filepath.Join(dir, "onyx-cli")
	os.MkdirAll(onyxDir, 0o755)
	data, _ := json.Marshal(map[string]interface{}{
		"server_url": "https://file-url.com",
		"api_key":    "file-key",
	})
	os.WriteFile(filepath.Join(onyxDir, "config.json"), data, 0o644)

	t.Setenv(EnvServerURL, "https://env-url.com")

	cfg := Load()
	if cfg.ServerURL != "https://env-url.com" {
		t.Errorf("env should override file, got %s", cfg.ServerURL)
	}
	if cfg.APIKey != "file-key" {
		t.Errorf("file value should be kept, got %s", cfg.APIKey)
	}
}

func TestSaveAndReload(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)

	cfg := OnyxCliConfig{
		ServerURL:        "https://saved.example.com",
		APIKey:           "saved-key",
		DefaultAgentID: 10,
	}
	if err := Save(cfg); err != nil {
		t.Fatal(err)
	}

	loaded := Load()
	if loaded.ServerURL != "https://saved.example.com" {
		t.Errorf("got %s", loaded.ServerURL)
	}
	if loaded.APIKey != "saved-key" {
		t.Errorf("got %s", loaded.APIKey)
	}
	if loaded.DefaultAgentID != 10 {
		t.Errorf("got %d", loaded.DefaultAgentID)
	}
}

func TestSaveCreatesParentDirs(t *testing.T) {
	clearEnvVars(t)
	dir := t.TempDir()
	nested := filepath.Join(dir, "deep", "nested")
	t.Setenv("XDG_CONFIG_HOME", nested)

	if err := Save(OnyxCliConfig{APIKey: "test"}); err != nil {
		t.Fatal(err)
	}

	if !ConfigExists() {
		t.Error("config file should exist after save")
	}
}
