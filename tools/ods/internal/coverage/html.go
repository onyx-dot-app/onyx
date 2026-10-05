package coverage

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

// WriteHTML renders a coverage profile as the browsable page produced by
// `go tool cover -html`. It runs in moduleDir so the tool can find the sources
// the profile names.
func WriteHTML(moduleDir, profilePath, htmlPath string) error {
	if err := os.MkdirAll(filepath.Dir(htmlPath), 0755); err != nil {
		return fmt.Errorf("create html directory: %w", err)
	}

	cmd := exec.Command("go", "tool", "cover", "-html="+profilePath, "-o", htmlPath)
	cmd.Dir = moduleDir
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("go tool cover -html: %w: %s", err, out)
	}
	return nil
}
