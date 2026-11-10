package template

import (
	"os"
	"path/filepath"
	"time"
)

// WriteFake makes a sealed template with small placeholder files in
// <storeDir>/<version>. For tests of code that reads templates.
func WriteFake(storeDir, version string, k Key) (Manifest, error) {
	dir := filepath.Join(storeDir, version)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return Manifest{}, err
	}
	for _, f := range Files {
		if err := os.WriteFile(filepath.Join(dir, f), []byte(f), 0o644); err != nil {
			return Manifest{}, err
		}
	}
	m, _, err := Seal(dir, Manifest{Version: version, Key: k, BuiltAt: time.Now().UTC()}, nil)
	return m, err
}
