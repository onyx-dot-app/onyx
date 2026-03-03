// Package util provides shared utility functions.
package util

import (
	"os/exec"
	"runtime"
)

// OpenBrowser opens the given URL in the user's default browser.
func OpenBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "linux":
		cmd = exec.Command("xdg-open", url)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	}
	if cmd != nil {
		if err := cmd.Start(); err == nil {
			// Reap the child process to avoid zombies.
			go cmd.Wait()
		}
	}
}
