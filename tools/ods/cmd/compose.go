package cmd

import (
	"os"
	"os/exec"
	"path/filepath"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// ComposeOptions holds options for the compose command
type ComposeOptions struct {
	Dev         bool
	Multitenant bool
	Down        bool
}

// NewComposeCommand creates a new compose command for launching docker containers
func NewComposeCommand() *cobra.Command {
	opts := &ComposeOptions{}

	cmd := &cobra.Command{
		Use:   "compose",
		Short: "Launch Onyx docker containers",
		Long: `Launch Onyx docker containers using docker compose.

By default, this runs docker compose up -d with the standard docker-compose.yml.

Examples:
  # Start containers with default configuration
  ods compose

  # Start containers with dev configuration (exposes service ports)
  ods compose --dev

  # Start containers with multitenant configuration
  ods compose --multitenant

  # Stop running containers
  ods compose --down`,
		Run: func(cmd *cobra.Command, args []string) {
			runCompose(opts)
		},
	}

	cmd.Flags().BoolVar(&opts.Dev, "dev", false, "Use dev configuration (exposes service ports for development)")
	cmd.Flags().BoolVar(&opts.Multitenant, "multitenant", false, "Use multitenant configuration")
	cmd.Flags().BoolVar(&opts.Down, "down", false, "Stop running containers instead of starting them")

	return cmd
}

func runCompose(opts *ComposeOptions) {
	if opts.Dev && opts.Multitenant {
		log.Fatal("Cannot use both --dev and --multitenant flags together")
	}

	// Get the docker compose directory
	gitRoot, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	composeDir := filepath.Join(gitRoot, "deployment", "docker_compose")

	// Build the docker compose command
	var composeFiles []string
	if opts.Multitenant {
		composeFiles = []string{"docker-compose.multitenant-dev.yml"}
	} else if opts.Dev {
		composeFiles = []string{"docker-compose.yml", "docker-compose.dev.yml"}
	} else {
		composeFiles = []string{"docker-compose.yml"}
	}

	// Build the command arguments
	args := []string{"compose"}
	for _, f := range composeFiles {
		args = append(args, "-f", f)
	}

	if opts.Down {
		args = append(args, "down")
	} else {
		args = append(args, "up", "-d")
	}

	// Log what we're doing
	action := "Starting"
	if opts.Down {
		action = "Stopping"
	}
	config := "default"
	if opts.Multitenant {
		config = "multitenant"
	} else if opts.Dev {
		config = "dev"
	}
	log.Infof("%s containers with %s configuration...", action, config)
	log.Debugf("Running: docker %v", args)

	// Execute docker compose
	dockerCmd := exec.Command("docker", args...)
	dockerCmd.Dir = composeDir
	dockerCmd.Stdout = os.Stdout
	dockerCmd.Stderr = os.Stderr
	dockerCmd.Stdin = os.Stdin

	if err := dockerCmd.Run(); err != nil {
		log.Fatalf("Docker compose failed: %v", err)
	}

	if opts.Down {
		log.Info("Containers stopped successfully")
	} else {
		log.Info("Containers started successfully")
	}
}
