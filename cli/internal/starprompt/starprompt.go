// Package starprompt implements a one-time GitHub star prompt shown before the TUI.
// Skipped when stdin/stdout is not a TTY, when gh CLI is not installed,
// or when the user has already been prompted. State is stored in the
// config directory so it shows at most once per user.
package starprompt

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"golang.org/x/term"
)

const repo = "onyx-dot-app/onyx"

func statePath() string {
	return filepath.Join(config.ConfigDir(), ".star-prompted")
}

func hasBeenPrompted() bool {
	_, err := os.Stat(statePath())
	return err == nil
}

func markPrompted() {
	_ = os.MkdirAll(config.ConfigDir(), 0o755)
	f, err := os.Create(statePath())
	if err == nil {
		_ = f.Close()
	}
}

func isGHInstalled() bool {
	_, err := exec.LookPath("gh")
	return err == nil
}

// MaybePrompt shows a one-time star prompt if conditions are met.
// It is safe to call unconditionally — it no-ops when not appropriate.
func MaybePrompt() {
	if !term.IsTerminal(int(os.Stdin.Fd())) || !term.IsTerminal(int(os.Stdout.Fd())) {
		return
	}
	if hasBeenPrompted() {
		return
	}
	if !isGHInstalled() {
		return
	}

	// Mark before asking so Ctrl+C won't cause a re-prompt.
	markPrompted()

	fmt.Print("Enjoying Onyx? Star the repo on GitHub? [Y/n] ")
	reader := bufio.NewReader(os.Stdin)
	answer, _ := reader.ReadString('\n')
	answer = strings.TrimSpace(strings.ToLower(answer))

	if answer == "n" || answer == "no" {
		return
	}

	cmd := exec.Command("gh", "api", "-X", "PUT", "/user/starred/"+repo)
	cmd.Env = append(os.Environ(), "GH_PAGER=")
	if devnull, err := os.Open(os.DevNull); err == nil {
		defer func() { _ = devnull.Close() }()
		cmd.Stdin = devnull
		cmd.Stdout = devnull
		cmd.Stderr = devnull
	}
	if err := cmd.Run(); err != nil {
		fmt.Println("Star us at: https://github.com/" + repo)
	} else {
		fmt.Println("Thanks for the star!")
		time.Sleep(500 * time.Millisecond)
	}
}
