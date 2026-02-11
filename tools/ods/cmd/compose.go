package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

var validProfiles = []string{"dev", "multitenant"}

const composeProjectName = "onyx"

// ComposeOptions holds options for the compose command
type ComposeOptions struct {
	Down          bool
	Wait          bool
	ForceRecreate bool
	Tag           string
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
  ods compose --wait=false

  # Force recreate containers
  ods compose --force-recreate

  # Use a specific image tag
  ods compose --tag edge`,
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
	cmd.Flags().BoolVar(&opts.ForceRecreate, "force-recreate", false, "Force recreate containers even if unchanged")
	cmd.Flags().StringVar(&opts.Tag, "tag", "", "Set the IMAGE_TAG for docker compose (e.g. edge, v2.10.4)")

	return cmd
}

// validateProfile checks that the given profile is valid.
func validateProfile(profile string) {
	if profile != "" && profile != "dev" && profile != "multitenant" {
		log.Fatalf("Invalid profile %q. Valid profiles: dev, multitenant", profile)
	}
}

// composeFiles returns the list of docker compose files for the given profile.
func composeFiles(profile string) []string {
	switch profile {
	case "multitenant":
		return []string{"docker-compose.multitenant-dev.yml"}
	case "dev":
		return []string{"docker-compose.yml", "docker-compose.dev.yml"}
	default:
		return []string{"docker-compose.yml"}
	}
}

// baseArgs builds the common "docker compose -p <project> -f ... -f ..." argument prefix.
func baseArgs(profile string) []string {
	args := []string{"compose", "-p", composeProjectName}
	for _, f := range composeFiles(profile) {
		args = append(args, "-f", f)
	}
	return args
}

// profileLabel returns a display label for the profile.
func profileLabel(profile string) string {
	if profile == "" {
		return "default"
	}
	return profile
}

// execDockerCompose runs a docker compose command in the correct directory with
// optional extra environment variables.
func execDockerCompose(args []string, extraEnv []string) {
	gitRoot, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	composeDir := filepath.Join(gitRoot, "deployment", "docker_compose")

	log.Debugf("Running: docker %v", args)

	dockerCmd := exec.Command("docker", args...)
	dockerCmd.Dir = composeDir
	dockerCmd.Stdout = os.Stdout
	dockerCmd.Stderr = os.Stderr
	dockerCmd.Stdin = os.Stdin
	if len(extraEnv) > 0 {
		dockerCmd.Env = append(os.Environ(), extraEnv...)
	}

	if err := dockerCmd.Run(); err != nil {
		log.Fatalf("Docker compose failed: %v", err)
	}
}

// runningServiceNames returns the names of currently running services in the
// compose project by running "docker compose -p onyx ps --services".
// On any error it returns nil (completions will just be empty).
func runningServiceNames() []string {
	gitRoot, err := paths.GitRoot()
	if err != nil {
		return nil
	}
	composeDir := filepath.Join(gitRoot, "deployment", "docker_compose")

	args := []string{"compose", "-p", composeProjectName, "ps", "--services"}

	cmd := exec.Command("docker", args...)
	cmd.Dir = composeDir
	out, err := cmd.Output()
	if err != nil {
		return nil
	}

	var services []string
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line != "" {
			services = append(services, line)
		}
	}
	return services
}

// envForTag returns the environment slice needed to set IMAGE_TAG, or nil.
func envForTag(tag string) []string {
	if tag == "" {
		return nil
	}
	return []string{fmt.Sprintf("IMAGE_TAG=%s", tag)}
}

func runCompose(profile string, opts *ComposeOptions) {
	validateProfile(profile)

	args := baseArgs(profile)

	if opts.Down {
		args = append(args, "down")
	} else {
		args = append(args, "up", "-d")
		if opts.Wait {
			args = append(args, "--wait")
		}
		if opts.ForceRecreate {
			args = append(args, "--force-recreate")
		}
	}

	action := "Starting"
	if opts.Down {
		action = "Stopping"
	}
	log.Infof("%s containers with %s configuration...", action, profileLabel(profile))

	execDockerCompose(args, envForTag(opts.Tag))

	if opts.Down {
		log.Info("Containers stopped successfully")
	} else {
		log.Info("Containers started successfully")
	}
}
