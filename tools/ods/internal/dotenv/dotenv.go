// Package dotenv reads and updates KEY=VALUE files such as .vscode/.env.
package dotenv

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

// Load parses a dotenv file into KEY=VALUE entries. Blank lines and comments
// are skipped, a leading "export " is dropped, and surrounding quotes are
// removed from values.
func Load(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer func() { _ = f.Close() }()

	var entries []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimPrefix(line, "export ")
		key, value, ok := strings.Cut(line, "=")
		key = strings.TrimSpace(key)
		if !ok || key == "" {
			continue
		}
		value = strings.TrimSpace(value)
		if len(value) >= 2 && value[0] == value[len(value)-1] && (value[0] == '"' || value[0] == '\'') {
			value = value[1 : len(value)-1]
		}
		entries = append(entries, fmt.Sprintf("%s=%s", key, value))
	}
	return entries, scanner.Err()
}

// Upsert sets each key to its value in the file. An existing "KEY=" line is
// replaced in place; other keys are appended. The file is created when
// missing.
func Upsert(path string, values map[string]string) error {
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("read %s: %w", path, err)
	}

	lines := []string{""}
	if len(data) > 0 {
		lines = strings.Split(string(data), "\n")
	}

	remaining := make(map[string]string, len(values))
	for k, v := range values {
		remaining[k] = v
	}

	for i, line := range lines {
		for key, val := range remaining {
			prefix := key + "="
			if strings.HasPrefix(line, prefix) {
				lines[i] = prefix + val
				delete(remaining, key)
				break
			}
		}
	}

	for key, val := range remaining {
		entry := key + "=" + val
		if lines[len(lines)-1] == "" {
			lines = append(lines[:len(lines)-1], entry, "")
		} else {
			lines = append(lines, entry)
		}
	}

	return os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0o644)
}
