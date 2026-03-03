package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
)

const (
	EnvServerURL    = "ONYX_SERVER_URL"
	EnvAPIKey       = "ONYX_API_KEY"
	EnvAPIKeyLegacy = "DANSWER_API_KEY"
	EnvAgentID    = "ONYX_PERSONA_ID"
)

// OnyxCliConfig holds the CLI configuration.
type OnyxCliConfig struct {
	ServerURL        string `json:"server_url"`
	APIKey           string `json:"api_key"`
	DefaultAgentID int    `json:"default_persona_id"`
}

// DefaultConfig returns a config with default values.
func DefaultConfig() OnyxCliConfig {
	return OnyxCliConfig{
		ServerURL:        "http://localhost:3000",
		APIKey:           "",
		DefaultAgentID: 0,
	}
}

// IsConfigured returns true if the config has an API key.
func (c OnyxCliConfig) IsConfigured() bool {
	return c.APIKey != ""
}

// configDir returns ~/.config/onyx-cli
func configDir() string {
	if xdg := os.Getenv("XDG_CONFIG_HOME"); xdg != "" {
		return filepath.Join(xdg, "onyx-cli")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(".", ".config", "onyx-cli")
	}
	return filepath.Join(home, ".config", "onyx-cli")
}

// ConfigFilePath returns the full path to the config file.
func ConfigFilePath() string {
	return filepath.Join(configDir(), "config.json")
}

// ConfigExists checks if the config file exists on disk.
func ConfigExists() bool {
	_, err := os.Stat(ConfigFilePath())
	return err == nil
}

// Load reads config from file and applies environment variable overrides.
func Load() OnyxCliConfig {
	cfg := DefaultConfig()

	data, err := os.ReadFile(ConfigFilePath())
	if err == nil {
		// Ignore JSON errors - fall back to defaults
		_ = json.Unmarshal(data, &cfg)
	}

	// Environment overrides
	if v := os.Getenv(EnvServerURL); v != "" {
		cfg.ServerURL = v
	}
	if v := os.Getenv(EnvAPIKey); v != "" {
		cfg.APIKey = v
	} else if v := os.Getenv(EnvAPIKeyLegacy); v != "" {
		cfg.APIKey = v
	}
	if v := os.Getenv(EnvAgentID); v != "" {
		if id, err := strconv.Atoi(v); err == nil {
			cfg.DefaultAgentID = id
		}
	}

	return cfg
}

// Save writes the config to disk, creating parent directories if needed.
func Save(cfg OnyxCliConfig) error {
	dir := configDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(ConfigFilePath(), data, 0o644)
}
