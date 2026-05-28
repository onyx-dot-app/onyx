package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

// NewEnvCommand creates the env command for writing infrastructure connection
// vars to .vscode/.env.
func NewEnvCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "env",
		Short: "Write infrastructure port env vars to .vscode/.env",
		Long: `Write infrastructure connection variables to .vscode/.env so that
locally-launched services (API server, Celery workers, etc.) connect to the
correct Docker Compose infrastructure for the current project/worktree.

Queries running containers for their actual host port mappings, then upserts
the corresponding keys in .vscode/.env. All other entries are left untouched.

Examples:
  # Write env vars for the current project (auto-detected from directory)
  ods env

  # Write env vars for a specific project
  ods env --project my-worktree

  # Show what would be written without modifying the file
  ods env --dry-run`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			dryRun, _ := cmd.Flags().GetBool("dry-run")
			runEnv(dryRun)
		},
	}

	cmd.Flags().Bool("dry-run", false, "print env vars without writing to file")

	return cmd
}

func runEnv(dryRun bool) {
	projName := docker.ProjectName()

	resolved := queryContainerPorts(projName)
	appEnv := resolved.AppEnv()

	log.Infof("Project: %s", projName)

	if dryRun {
		for k, v := range appEnv {
			fmt.Printf("%s=%s\n", k, v)
		}
		return
	}

	gitRoot, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	envPath := filepath.Join(gitRoot, ".vscode", ".env")

	if _, err := os.Stat(envPath); os.IsNotExist(err) {
		log.Warnf("%s does not exist. Creating it with port variables only.", envPath)
		log.Warnf("This file normally contains additional settings (API keys, auth config, etc.).")
		log.Warnf("You may want to copy the template from the repo wiki or another developer's setup.")
		if !prompt.Confirm("Continue creating a minimal .vscode/.env? (yes/no): ") {
			log.Info("Aborted.")
			return
		}
	}

	if err := setEnvValues(envPath, appEnv); err != nil {
		log.Fatalf("Failed to update %s: %v", envPath, err)
	}

	log.Infof("Updated %s", envPath)
	for k, v := range appEnv {
		log.Debugf("  %s=%s", k, v)
	}
}

// queryContainerPorts discovers the actual host ports of running containers by
// calling "docker port" for each port spec in InfraServices. Container names
// follow the Docker Compose convention "<project>-<service>-1". If a container
// is not running, the default host port from the spec is used instead.
func queryContainerPorts(projName string) *docker.ResolvedPorts {
	resolved := docker.NewResolvedPorts()

	for _, svc := range docker.InfraServices {
		container := fmt.Sprintf("%s-%s-1", projName, svc.Name)
		for _, spec := range svc.Ports {
			port, err := docker.GetHostPort(container, spec.ContainerPort)
			if err != nil {
				log.Warnf("%s: container not running, skipping getting its port.", svc.Name)
				continue
			}
			resolved.Append(port, spec)
		}
	}

	return resolved
}

// setEnvValues upserts multiple key=value pairs in a dotenv file. For each key,
// it scans existing lines for a matching "KEY=" prefix and replaces the line in
// place. Keys not already present are appended at the end. The file is created
// if it does not exist.
func setEnvValues(envPath string, values map[string]string) error {
	data, err := os.ReadFile(envPath)
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("read %s: %w", envPath, err)
	}

	lines := []string{""}
	if len(data) > 0 {
		lines = strings.Split(string(data), "\n")
	}

	remaining := make(map[string]string, len(values))
	for k, v := range values {
		remaining[k] = v
	}

	for i, line := range lines {
		for key, val := range remaining {
			prefix := key + "="
			if strings.HasPrefix(line, prefix) {
				lines[i] = prefix + val
				delete(remaining, key)
				break
			}
		}
	}

	for key, val := range remaining {
		entry := key + "=" + val
		if lines[len(lines)-1] == "" {
			lines = append(lines[:len(lines)-1], entry, "")
		} else {
			lines = append(lines, entry)
		}
	}

	return os.WriteFile(envPath, []byte(strings.Join(lines, "\n")), 0644)
}
