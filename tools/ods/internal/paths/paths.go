package paths

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	log "github.com/sirupsen/logrus"
)

// GitRoot returns the root directory of the current git repository.
func GitRoot() (string, error) {
	cmd := exec.Command("git", "rev-parse", "--show-toplevel")
	output, err := cmd.Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

// DataDir returns the data directory for onyx-dev tools.
// On Linux/macOS: ~/.local/share/onyx-dev/
// On Windows: %LOCALAPPDATA%/onyx-dev/
func DataDir() string {
	var base string
	if runtime.GOOS == "windows" {
		base = os.Getenv("LOCALAPPDATA")
		if base == "" {
			base = os.Getenv("USERPROFILE")
			if base == "" {
				log.Fatalf("Cannot determine data directory: LOCALAPPDATA and USERPROFILE are not set")
			}
			base = filepath.Join(base, "AppData", "Local")
		}
	} else {
		base = os.Getenv("XDG_DATA_HOME")
		if base == "" {
			home, err := os.UserHomeDir()
			if err != nil || home == "" {
				log.Fatalf("Cannot determine data directory: XDG_DATA_HOME not set and home directory unknown: %v", err)
			}
			base = filepath.Join(home, ".local", "share")
		}
	}
	return filepath.Join(base, "onyx-dev")
}

// ConfigDir returns the per-user config directory for onyx-dev tools.
// On Linux/macOS: ~/.config/onyx-dev/ (respects XDG_CONFIG_HOME)
// On Windows:    %APPDATA%/onyx-dev/
func ConfigDir() string {
	var base string
	if runtime.GOOS == "windows" {
		base = os.Getenv("APPDATA")
		if base == "" {
			base = os.Getenv("USERPROFILE")
			if base == "" {
				log.Fatalf("Cannot determine config directory: APPDATA and USERPROFILE are not set")
			}
			base = filepath.Join(base, "AppData", "Roaming")
		}
	} else {
		base = os.Getenv("XDG_CONFIG_HOME")
		if base == "" {
			home, err := os.UserHomeDir()
			if err != nil || home == "" {
				log.Fatalf("Cannot determine config directory: XDG_CONFIG_HOME not set and home directory unknown: %v", err)
			}
			base = filepath.Join(home, ".config")
		}
	}
	return filepath.Join(base, "onyx-dev")
}

// ConfigFilePath returns the path to the ods config file.
func ConfigFilePath() string {
	return filepath.Join(ConfigDir(), "config.json")
}

// EnsureConfigDir creates the config directory if it doesn't exist.
func EnsureConfigDir() error {
	return os.MkdirAll(ConfigDir(), 0755)
}

// SnapshotsDir returns the directory for database snapshots.
func SnapshotsDir() string {
	return filepath.Join(DataDir(), "snapshots")
}

// EnsureSnapshotsDir creates the snapshots directory if it doesn't exist.
func EnsureSnapshotsDir() error {
	return os.MkdirAll(SnapshotsDir(), 0755)
}

// BackendDir returns the backend directory relative to the git root.
func BackendDir() (string, error) {
	root, err := GitRoot()
	if err != nil {
		return "", err
	}
	return filepath.Join(root, "backend"), nil
}
