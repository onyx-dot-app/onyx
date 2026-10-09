// Package deployfilessync mirrors the deployment files that onyx-cli embeds
// (via go:embed in cli/internal/deploy/deployfiles) from their source of truth
// under deployment/. go:embed cannot reference files outside the cli module,
// so byte-identical copies are checked in and kept in sync by
// `ods generate-compose --write` (which renders the compose variants and then
// syncs these copies) and its docker-compose-sync pre-commit hook.
package deployfilessync

import (
	"fmt"
	"os"
	"path/filepath"
)

// RelPaths lists the synced files relative to <repo>/deployment. They are the
// exact set the guided installer ships (base + prod compose files, the
// lite/craft/dev overlays, env templates, nginx config, install-root README)
// and are mirrored at the same relative paths under
// cli/internal/deploy/deployfiles/embedded/.
//
// docker-compose.yml and docker-compose.prod.yml are themselves generated
// from docker-compose.template.yml, which is why the sync runs as the second
// half of `ods generate-compose`.
var RelPaths = []string{
	"docker_compose/docker-compose.yml",
	"docker_compose/docker-compose.onyx-lite.yml",
	"docker_compose/docker-compose.craft.yml",
	"docker_compose/docker-compose.dev.yml",
	"docker_compose/docker-compose.prod.yml",
	"docker_compose/env.template",
	"docker_compose/env.prod.template",
	"docker_compose/env.nginx.template",
	"docker_compose/README.md",
	"data/nginx/app.conf.template",
	"data/nginx/app.conf.template.prod",
	"data/nginx/run-nginx.sh",
}

// SourceDir returns the directory the files are copied from.
func SourceDir(repoRoot string) string {
	return filepath.Join(repoRoot, "deployment")
}

// DestDir returns the directory the files are copied to.
func DestDir(repoRoot string) string {
	return filepath.Join(repoRoot, "cli", "internal", "deploy", "deployfiles", "embedded")
}

// Result describes one synced file.
type Result struct {
	RelPath string
	Stale   bool
	Source  string // content under deployment/ (the source of truth)
	Dest    string // embedded copy content ("" if missing)
}

// Check compares every embedded copy against its source file.
func Check(repoRoot string) ([]Result, error) {
	results := make([]Result, 0, len(RelPaths))
	for _, rel := range RelPaths {
		source, err := os.ReadFile(filepath.Join(SourceDir(repoRoot), filepath.FromSlash(rel)))
		if err != nil {
			return nil, fmt.Errorf("failed to read source %s: %w", rel, err)
		}
		dest, err := os.ReadFile(filepath.Join(DestDir(repoRoot), filepath.FromSlash(rel)))
		if err != nil && !os.IsNotExist(err) {
			return nil, fmt.Errorf("failed to read embedded copy %s: %w", rel, err)
		}
		results = append(results, Result{
			RelPath: rel,
			Stale:   string(source) != string(dest),
			Source:  string(source),
			Dest:    string(dest),
		})
	}
	return results, nil
}

// Write refreshes every stale embedded copy from its source file and returns
// the check results (with Stale reflecting the pre-write state).
func Write(repoRoot string) ([]Result, error) {
	results, err := Check(repoRoot)
	if err != nil {
		return nil, err
	}
	for _, r := range results {
		if !r.Stale {
			continue
		}
		dest := filepath.Join(DestDir(repoRoot), filepath.FromSlash(r.RelPath))
		if err := os.MkdirAll(filepath.Dir(dest), 0755); err != nil {
			return nil, fmt.Errorf("failed to create directory for %s: %w", r.RelPath, err)
		}
		if err := os.WriteFile(dest, []byte(r.Source), 0644); err != nil {
			return nil, fmt.Errorf("failed to write %s: %w", r.RelPath, err)
		}
	}
	return results, nil
}
