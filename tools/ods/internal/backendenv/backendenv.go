// Package backendenv handles .vscode/.env, the file the backend and its test
// suites read their credentials from. It creates the file from the template on
// first use, parses it, and merges it under the shell environment.
package backendenv

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
)

// EnsureFile returns the path to .vscode/.env, copying env_template.txt over it
// first if it does not exist yet.
func EnsureFile(root string) (string, error) {
	vscodeDir := filepath.Join(root, ".vscode")
	envFile := filepath.Join(vscodeDir, ".env")
	templateFile := filepath.Join(vscodeDir, "env_template.txt")

	if _, err := os.Stat(envFile); err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			return "", fmt.Errorf("failed to stat env file %s: %w", envFile, err)
		}
	} else {
		log.Debugf("Using existing env file: %s", envFile)
		return envFile, nil
	}

	templateData, err := os.ReadFile(templateFile)
	if err != nil {
		return "", fmt.Errorf("failed to read env template %s: %w", templateFile, err)
	}

	if err := os.MkdirAll(vscodeDir, 0755); err != nil {
		return "", fmt.Errorf("failed to create .vscode directory: %w", err)
	}

	if err := os.WriteFile(envFile, templateData, 0644); err != nil {
		return "", fmt.Errorf("failed to write env file %s: %w", envFile, err)
	}

	log.Infof("Created %s from template (review and fill in <REPLACE THIS> values)", envFile)
	return envFile, nil
}

// Load parses a .env file into KEY=VALUE entries suitable for appending to
// os.Environ(). Blank lines and comments are skipped.
func Load(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("failed to open env file %s: %w", path, err)
	}
	defer func() { _ = f.Close() }()

	var envVars []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if idx := strings.Index(line, "="); idx > 0 {
			key := strings.TrimSpace(line[:idx])
			value := strings.TrimSpace(line[idx+1:])
			value = strings.Trim(value, `"'`)
			envVars = append(envVars, fmt.Sprintf("%s=%s", key, value))
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("failed to read env file %s: %w", path, err)
	}

	return envVars, nil
}

// Merge combines the shell environment with file-based defaults. Shell values
// take precedence — file entries are only added for keys not already present.
func Merge(shellEnv, fileVars []string) []string {
	existing := make(map[string]bool, len(shellEnv))
	for _, entry := range shellEnv {
		if idx := strings.Index(entry, "="); idx > 0 {
			existing[entry[:idx]] = true
		}
	}

	merged := make([]string, len(shellEnv))
	copy(merged, shellEnv)
	for _, entry := range fileVars {
		if idx := strings.Index(entry, "="); idx > 0 {
			key := entry[:idx]
			if !existing[key] {
				merged = append(merged, entry)
			} else {
				log.Debugf("Env var %s already set in shell, skipping .env value", key)
			}
		}
	}
	return merged
}

// EEDefaults returns env entries for Enterprise Edition and license
// enforcement. Callers append them to the file vars, so they act as defaults:
// shell env and .env file values still win through Merge.
func EEDefaults(noEE bool) []string {
	if noEE {
		return []string{
			"ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=false",
		}
	}
	return []string{
		"ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true",
		"LICENSE_ENFORCEMENT_ENABLED=false",
	}
}
