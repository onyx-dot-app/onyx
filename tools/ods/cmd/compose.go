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
	NoEE          bool
}

// NewComposeCommand creates a new compose command for launching docker containers
func NewComposeCommand() *cobra.Command {
	opts := &ComposeOptions{}

	cmd := &cobra.Command{
		Use:   "compose [profile]",
		Short: "Launch Onyx docker containers",
		Long: `Launch Onyx docker containers using docker compose.

By default, this runs docker compose up -d with the standard docker-compose.yml.
Enterprise Edition features are enabled by default for development.

Available profiles:
  dev          Use dev configuration (exposes service ports for development)
  multitenant  Use multitenant configuration

Examples:
  # Start containers with default configuration (EE enabled)
  ods compose

  # Start containers with dev configuration (exposes service ports)
  ods compose dev

  # Start containers with multitenant configuration
  ods compose multitenant

  # Start containers without Enterprise Edition features
  ods compose --no-ee

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
	cmd.Flags().BoolVar(&opts.NoEE, "no-ee", false, "Disable Enterprise Edition features (enabled by default)")

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
	log.Debugf("Running: docker %v", args)

	dockerCmd := exec.Command("docker", args...)
	dockerCmd.Dir = composeDir()
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

	args := []string{"compose", "-p", composeProjectName, "ps", "--services"}

	cmd := exec.Command("docker", args...)
	cmd.Dir = filepath.Join(gitRoot, "deployment", "docker_compose")
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

// composeDir returns the path to the docker compose directory.
func composeDir() string {
	gitRoot, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	return filepath.Join(gitRoot, "deployment", "docker_compose")
}

// setEnvValue sets a key=value pair in the .env file within the compose
// directory. If the key already exists its value is updated in place;
// otherwise the entry is appended. The file is created if it does not exist.
func setEnvValue(key, value string) {
	envPath := filepath.Join(composeDir(), ".env")

	data, err := os.ReadFile(envPath)
	if err != nil && !os.IsNotExist(err) {
		log.Fatalf("Failed to read %s: %v", envPath, err)
	}

	entry := fmt.Sprintf("%s=%s", key, value)
	prefix := key + "="

	if len(data) == 0 {
		// File missing or empty – create with just this entry.
		if err := os.WriteFile(envPath, []byte(entry+"\n"), 0644); err != nil {
			log.Fatalf("Failed to write %s: %v", envPath, err)
		}
		return
	}

	lines := strings.Split(string(data), "\n")
	found := false
	for i, line := range lines {
		if strings.HasPrefix(line, prefix) {
			lines[i] = entry
			found = true
			break
		}
	}

	if !found {
		// Insert before the trailing empty line (if the file ended with \n)
		// so we don't accumulate blank lines.
		if lines[len(lines)-1] == "" {
			lines = append(lines[:len(lines)-1], entry, "")
		} else {
			lines = append(lines, entry)
		}
	}

	if err := os.WriteFile(envPath, []byte(strings.Join(lines, "\n")), 0644); err != nil {
		log.Fatalf("Failed to write %s: %v", envPath, err)
	}
}

func runCompose(profile string, opts *ComposeOptions) {
	validateProfile(profile)

	if !opts.Down {
		eeValue := "true"
		if opts.NoEE {
			eeValue = "false"
		}
		setEnvValue("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", eeValue)
		if !opts.NoEE {
			setEnvValue("LICENSE_ENFORCEMENT_ENABLED", "false")
		}
	}

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
	if !opts.Down && !opts.NoEE {
		log.Info("Enterprise Edition features enabled (use --no-ee to disable)")
	}

	execDockerCompose(args, envForTag(opts.Tag))

	if opts.Down {
		log.Info("Containers stopped successfully")
	} else {
		log.Info("Containers started successfully")
	}
}
