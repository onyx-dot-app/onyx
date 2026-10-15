package devstack

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/dotenv"
)

var placeholderLine = regexp.MustCompile(`^([A-Z][A-Z0-9_]*)=<REPLACE(?: THIS|_THIS)>$`)

// PrepareEnvFiles makes sure .vscode/.env and .vscode/.env.web exist as
// regular files owned by this worktree. A symlink is replaced by a copy of
// its target so a port update never edits another checkout's file. A missing
// file is created from the tracked template with placeholders blanked.
// Values are never logged.
func PrepareEnvFiles(root string) (created, localized []string, err error) {
	vscode := filepath.Join(root, ".vscode")
	for _, f := range []struct{ name, template string }{
		{".env", "env_template.txt"},
		{".env.web", "env.web_template.txt"},
	} {
		path := filepath.Join(vscode, f.name)
		wasLink, err := localizeSymlink(path)
		if err != nil {
			return created, localized, err
		}
		if wasLink {
			localized = append(localized, path)
		}
		if _, err := os.Lstat(path); err == nil {
			continue
		} else if !errors.Is(err, fs.ErrNotExist) {
			return created, localized, err
		}
		template, err := os.ReadFile(filepath.Join(vscode, f.template))
		if err != nil {
			return created, localized, fmt.Errorf("read env template: %w", err)
		}
		if err := os.MkdirAll(vscode, 0o755); err != nil {
			return created, localized, err
		}
		if err := writeFileAtomic(path, []byte(fillTemplate(string(template), root)), 0o600); err != nil {
			return created, localized, err
		}
		log.Infof("Created %s from %s", path, f.template)
		created = append(created, path)
	}
	return created, localized, nil
}

// fillTemplate blanks the <REPLACE THIS> placeholders, points SAML_CONF_DIR
// at this checkout, and turns tracing off, so the file loads without edits.
func fillTemplate(template, root string) string {
	var out []string
	for _, line := range strings.Split(template, "\n") {
		switch {
		case placeholderLine.MatchString(line):
			out = append(out, placeholderLine.FindStringSubmatch(line)[1]+"=")
		case strings.HasPrefix(line, "SAML_CONF_DIR="):
			out = append(out, "SAML_CONF_DIR="+filepath.Join(root, "backend", "ee", "onyx", "configs", "saml_config"))
		case strings.HasPrefix(line, "LANGSMITH_TRACING="):
			out = append(out, "LANGSMITH_TRACING=false")
		default:
			out = append(out, line)
		}
	}
	return strings.Join(out, "\n")
}

// localizeSymlink replaces a symlink at path with a regular file holding the
// target's content. A dangling symlink is removed.
func localizeSymlink(path string) (bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if info.Mode()&fs.ModeSymlink == 0 {
		return false, nil
	}
	content, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		log.Warnf("Removing dangling symlink %s", path)
		return true, os.Remove(path)
	}
	if err != nil {
		return false, err
	}
	if err := os.Remove(path); err != nil {
		return false, err
	}
	if err := writeFileAtomic(path, content, 0o600); err != nil {
		return false, err
	}
	log.Infof("Converted %s into a worktree-local file", path)
	return true, nil
}

// LoadEnvFile parses a dotenv file. A missing file yields no entries.
func LoadEnvFile(path string) ([]string, error) {
	entries, err := dotenv.Load(path)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	return entries, err
}

// UpsertEnvFile sets values in a dotenv file.
func UpsertEnvFile(path string, values map[string]string) error {
	if len(values) == 0 {
		return nil
	}
	return dotenv.Upsert(path, values)
}

// MergeEnv returns base with overrides applied: an override replaces the
// base entry with the same key.
func MergeEnv(base, overrides []string) []string {
	index := map[string]int{}
	merged := make([]string, 0, len(base)+len(overrides))
	for _, entry := range base {
		key, _, _ := strings.Cut(entry, "=")
		if i, ok := index[key]; ok {
			merged[i] = entry
			continue
		}
		index[key] = len(merged)
		merged = append(merged, entry)
	}
	for _, entry := range overrides {
		key, _, _ := strings.Cut(entry, "=")
		if i, ok := index[key]; ok {
			merged[i] = entry
			continue
		}
		index[key] = len(merged)
		merged = append(merged, entry)
	}
	return merged
}

// EnvValue returns the value of key in env, or "".
func EnvValue(env []string, key string) string {
	for i := len(env) - 1; i >= 0; i-- {
		if v, ok := strings.CutPrefix(env[i], key+"="); ok {
			return v
		}
	}
	return ""
}

func mapToEnv(m map[string]string) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	env := make([]string, 0, len(keys))
	for _, k := range keys {
		env = append(env, k+"="+m[k])
	}
	return env
}

func environ() []string {
	return os.Environ()
}
