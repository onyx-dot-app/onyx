// Package paths resolves where an Onyx docker compose deployment lives on
// disk. New installs default to ~/.config/onyx (XDG-style, matching the CLI's
// own config dir convention); legacy installs created by install.sh in
// ./onyx_data are detected and managed in place.
package paths

import (
	"os"
	"path/filepath"
)

// Source records how the install root was chosen.
type Source string

const (
	// SourceFlag: the --dir flag.
	SourceFlag Source = "--dir flag"
	// SourceEnvDeploymentDir: the ONYX_DEPLOYMENT_DIR environment variable.
	SourceEnvDeploymentDir Source = "ONYX_DEPLOYMENT_DIR"
	// SourceEnvInstallPrefix: the legacy INSTALL_PREFIX environment variable
	// honored by install.sh.
	SourceEnvInstallPrefix Source = "INSTALL_PREFIX"
	// SourceLegacyCwd: an existing ./onyx_data install relative to the
	// working directory (the location install.sh used).
	SourceLegacyCwd Source = "legacy ./onyx_data"
	// SourceDefault: the XDG-style default for new installs.
	SourceDefault Source = "default"
)

// legacyDirName is the cwd-relative install directory install.sh created.
const legacyDirName = "onyx_data"

// InstallRoot is a resolved deployment location.
type InstallRoot struct {
	Dir    string
	Source Source
	// Ambiguous lists other existing installs that were NOT chosen. Only
	// populated for implicit resolution (no flag/env override) when more
	// than one candidate contains an install.
	Ambiguous []string
}

// DefaultDir returns the XDG-style default install root: $XDG_CONFIG_HOME/onyx
// or ~/.config/onyx. Mirrors config.ConfigDir()'s algorithm (which resolves
// the CLI's own ~/.config/onyx-cli on every OS, including Windows) so the two
// directories are siblings everywhere.
func DefaultDir() string {
	if xdg := os.Getenv("XDG_CONFIG_HOME"); xdg != "" {
		return filepath.Join(xdg, "onyx")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(".", ".config", "onyx")
	}
	return filepath.Join(home, ".config", "onyx")
}

// IsInstall reports whether dir contains an Onyx deployment: either the
// compose file or a .env under deployment/ (the markers install.sh itself
// checks before operating on a directory).
func IsInstall(dir string) bool {
	for _, marker := range []string{
		filepath.Join(dir, "deployment", "docker-compose.yml"),
		filepath.Join(dir, "deployment", ".env"),
	} {
		if _, err := os.Stat(marker); err == nil {
			return true
		}
	}
	return false
}

// Resolve picks the install root. Precedence: --dir flag, ONYX_DEPLOYMENT_DIR,
// legacy INSTALL_PREFIX, an existing legacy ./onyx_data install, then the
// XDG-style default (which need not exist yet — it is the target for fresh
// installs).
func Resolve(dirFlag string) InstallRoot {
	if dirFlag != "" {
		return InstallRoot{Dir: dirFlag, Source: SourceFlag}
	}
	if dir := os.Getenv("ONYX_DEPLOYMENT_DIR"); dir != "" {
		return InstallRoot{Dir: dir, Source: SourceEnvDeploymentDir}
	}
	if dir := os.Getenv("INSTALL_PREFIX"); dir != "" {
		return InstallRoot{Dir: dir, Source: SourceEnvInstallPrefix}
	}

	defaultDir := DefaultDir()
	if IsInstall(legacyDirName) {
		root := InstallRoot{Dir: legacyDirName, Source: SourceLegacyCwd}
		if IsInstall(defaultDir) {
			root.Ambiguous = []string{defaultDir}
		}
		return root
	}
	return InstallRoot{Dir: defaultDir, Source: SourceDefault}
}
