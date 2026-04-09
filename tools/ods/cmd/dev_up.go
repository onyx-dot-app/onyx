package cmd

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

func newDevUpCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "up",
		Short: "Start the devcontainer",
		Long: `Start the devcontainer, pulling the image if needed.

Examples:
  ods dev up`,
		Run: func(cmd *cobra.Command, args []string) {
			runDevcontainer("up", nil)
		},
	}

	return cmd
}

// devcontainerImage reads the image field from .devcontainer/devcontainer.json.
func devcontainerImage() string {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(root, ".devcontainer", "devcontainer.json"))
	if err != nil {
		log.Fatalf("Failed to read devcontainer.json: %v", err)
	}

	var cfg struct {
		Image string `json:"image"`
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		log.Fatalf("Failed to parse devcontainer.json: %v", err)
	}
	if cfg.Image == "" {
		log.Fatal("No image field in devcontainer.json")
	}
	return cfg.Image
}

// checkDevcontainerCLI ensures the devcontainer CLI is installed.
func checkDevcontainerCLI() {
	if _, err := exec.LookPath("devcontainer"); err != nil {
		log.Fatal("devcontainer CLI is not installed. Install it with: npm install -g @devcontainers/cli")
	}
}

// runDevcontainer executes "devcontainer <action> --workspace-folder <root> [extraArgs...]".
func runDevcontainer(action string, extraArgs []string) {
	checkDevcontainerCLI()

	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	args := []string{action, "--workspace-folder", root}
	args = append(args, extraArgs...)

	log.Debugf("Running: devcontainer %v", args)

	c := exec.Command("devcontainer", args...)
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	c.Stdin = os.Stdin

	if err := c.Run(); err != nil {
		log.Fatalf("devcontainer %s failed: %v", action, err)
	}
}
