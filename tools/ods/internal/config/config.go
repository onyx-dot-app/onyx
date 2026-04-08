package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// DeployEdgeConfig holds the persisted settings for `ods deploy edge`.
type DeployEdgeConfig struct {
	TargetRepo     string `json:"target_repo,omitempty"`
	TargetWorkflow string `json:"target_workflow,omitempty"`
}

// Config is the top-level on-disk schema for ~/.config/onyx-dev/config.json.
// New per-command sections should be added as additional fields.
type Config struct {
	DeployEdge DeployEdgeConfig `json:"deploy_edge,omitempty"`
}

// Load reads the config file. Returns a zero-valued Config if the file does
// not exist (a fresh first-run state, not an error).
func Load() (*Config, error) {
	path := paths.ConfigFilePath()
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return &Config{}, nil
		}
		return nil, fmt.Errorf("failed to read config file %s: %w", path, err)
	}
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("failed to parse config file %s: %w", path, err)
	}
	return &cfg, nil
}

// Save persists the config to disk, creating the parent directory if needed.
func Save(cfg *Config) error {
	if err := paths.EnsureConfigDir(); err != nil {
		return fmt.Errorf("failed to create config directory: %w", err)
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}
	path := paths.ConfigFilePath()
	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("failed to write config file %s: %w", path, err)
	}
	return nil
}
