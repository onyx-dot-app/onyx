package template

import (
	"os"
	"path/filepath"
	"time"
)

// WriteFake makes a sealed template with small placeholder files in
// <storeDir>/<version>. For tests of code that reads templates.
func WriteFake(storeDir, version string, k Key) (Manifest, error) {
	return WriteFakeLayout(storeDir, version, k, LayoutVersion)
}

// WriteFakeLayout is WriteFake for an older layout.
func WriteFakeLayout(storeDir, version string, k Key, layout int) (Manifest, error) {
	dir := filepath.Join(storeDir, version)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return Manifest{}, err
	}
	k.LayoutVersion = layout
	for _, f := range FilesFor(layout) {
		if err := os.WriteFile(filepath.Join(dir, f), []byte(f), 0o644); err != nil {
			return Manifest{}, err
		}
	}
	m := Manifest{Version: version, Key: k, BuiltAt: time.Now().UTC()}
	for _, md := range ManagedMountDrives {
		m.GuestMounts = append(m.GuestMounts, md.Mount)
	}
	m, _, err := Seal(dir, m, nil)
	return m, err
}
