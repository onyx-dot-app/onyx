package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
)

const (
	EnvServerURL       = "ONYX_SERVER_URL"
	EnvAPIKey          = "ONYX_API_KEY"
	EnvAgentID         = "ONYX_PERSONA_ID"
	EnvSSHHostKey      = "ONYX_SSH_HOST_KEY"
	EnvStreamMarkdown  = "ONYX_STREAM_MARKDOWN"
)

// Features holds experimental feature flags for the CLI.
type Features struct {
	// StreamMarkdown enables progressive markdown rendering during streaming,
	// so output is formatted as it arrives rather than after completion.
	StreamMarkdown bool `json:"stream_markdown,omitempty"`
}

// OnyxCliConfig holds the CLI configuration.
type OnyxCliConfig struct {
	ServerURL      string   `json:"server_url"`
	APIKey         string   `json:"api_key"`
	DefaultAgentID int      `json:"default_persona_id"`
	Features       Features `json:"features,omitzero"`
}

// DefaultConfig returns a config with default values.
func DefaultConfig() OnyxCliConfig {
	return OnyxCliConfig{
		ServerURL:        "https://cloud.onyx.app",
		APIKey:           "",
		DefaultAgentID: 0,
	}
}

// IsConfigured returns true if the config has an API key.
func (c OnyxCliConfig) IsConfigured() bool {
	return c.APIKey != ""
}

// ConfigDir returns ~/.config/onyx-cli
func ConfigDir() string {
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
	return filepath.Join(ConfigDir(), "config.json")
}

// ConfigExists checks if the config file exists on disk.
func ConfigExists() bool {
	_, err := os.Stat(ConfigFilePath())
	return err == nil
}

// LoadFromDisk reads config from the file only, without applying environment
// variable overrides. Use this when you need the persisted config values
// (e.g., to preserve them during a save operation).
func LoadFromDisk() OnyxCliConfig {
	cfg := DefaultConfig()

	data, err := os.ReadFile(ConfigFilePath())
	if err == nil {
		if jsonErr := json.Unmarshal(data, &cfg); jsonErr != nil {
			fmt.Fprintf(os.Stderr, "warning: config file %s is malformed: %v (using defaults)\n", ConfigFilePath(), jsonErr)
		}
	}

	return cfg
}

// Load reads config from file and applies environment variable overrides.
func Load() OnyxCliConfig {
	cfg := LoadFromDisk()

	// Environment overrides
	if v := os.Getenv(EnvServerURL); v != "" {
		cfg.ServerURL = v
	}
	if v := os.Getenv(EnvAPIKey); v != "" {
		cfg.APIKey = v
	}
	if v := os.Getenv(EnvAgentID); v != "" {
		if id, err := strconv.Atoi(v); err == nil {
			cfg.DefaultAgentID = id
		}
	}
	if v := os.Getenv(EnvStreamMarkdown); v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			cfg.Features.StreamMarkdown = b
		} else {
			fmt.Fprintf(os.Stderr, "warning: invalid value %q for %s (expected true/false), ignoring\n", v, EnvStreamMarkdown)
		}
	}

	return cfg
}

// Save writes the config to disk, creating parent directories if needed.
func Save(cfg OnyxCliConfig) error {
	dir := ConfigDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(ConfigFilePath(), data, 0o600)
}
