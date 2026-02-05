package cmd

import (
	"os"
	"os/exec"
	"path/filepath"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

var validProfiles = []string{"dev", "multitenant"}

// ComposeOptions holds options for the compose command
type ComposeOptions struct {
	Down bool
	Wait bool
}

// NewComposeCommand creates a new compose command for launching docker containers
func NewComposeCommand() *cobra.Command {
	opts := &ComposeOptions{}

	cmd := &cobra.Command{
		Use:   "compose [profile]",
		Short: "Launch Onyx docker containers",
		Long: `Launch Onyx docker containers using docker compose.

By default, this runs docker compose up -d with the standard docker-compose.yml.

Available profiles:
  dev          Use dev configuration (exposes service ports for development)
  multitenant  Use multitenant configuration

Examples:
  # Start containers with default configuration
  ods compose

  # Start containers with dev configuration (exposes service ports)
  ods compose dev

  # Start containers with multitenant configuration
  ods compose multitenant

  # Stop running containers
  ods compose --down
  ods compose dev --down

  # Start without waiting for services to be healthy
  ods compose --wait=false`,
		Args:      cobra.MaximumNArgs(1),
		ValidArgs: validProfiles,
		Run: func(cmd *cobra.Command, args []string) {
			profile := ""
			if len(args) > 0 {
				profile = args[0]
			}
			runCompose(profile, opts)
		},
	}

	cmd.Flags().BoolVar(&opts.Down, "down", false, "Stop running containers instead of starting them")
	cmd.Flags().BoolVar(&opts.Wait, "wait", true, "Wait for services to be healthy before returning")

	return cmd
}

func runCompose(profile string, opts *ComposeOptions) {
	// Validate profile
	if profile != "" && profile != "dev" && profile != "multitenant" {
		log.Fatalf("Invalid profile %q. Valid profiles: dev, multitenant", profile)
	}

	// Get the docker compose directory
	gitRoot, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	composeDir := filepath.Join(gitRoot, "deployment", "docker_compose")

	// Build the docker compose command
	var composeFiles []string
	switch profile {
	case "multitenant":
		composeFiles = []string{"docker-compose.multitenant-dev.yml"}
	case "dev":
		composeFiles = []string{"docker-compose.yml", "docker-compose.dev.yml"}
	default:
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
		if opts.Wait {
			args = append(args, "--wait")
		}
	}

	// Log what we're doing
	action := "Starting"
	if opts.Down {
		action = "Stopping"
	}
	config := profile
	if config == "" {
		config = "default"
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
