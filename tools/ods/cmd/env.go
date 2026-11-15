package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
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
the corresponding keys in .vscode/.env. S3_LEGACY_ENDPOINT_URL is dropped,
since the dev stack runs the object store only. All other entries are left
untouched.

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
			if err := runEnv(dryRun); err != nil {
				log.Fatal(err)
			}
		},
	}

	cmd.Flags().Bool("dry-run", false, "print env vars without writing to file")

	return cmd
}

func runEnv(dryRun bool) error {
	target, err := resolveRuntimeTarget()
	if err != nil {
		return err
	}
	release, err := lockRuntimeTarget(target, false)
	if err != nil {
		return err
	}
	defer release()
	projName := target.Project

	resolved := queryContainerPorts(projName)
	appEnv := resolved.AppEnv()
	if _, ok := appEnv["POSTGRES_PORT"]; !ok {
		return fmt.Errorf("no running PostgreSQL container with a published port for project %s", projName)
	}

	log.Infof("Project: %s", projName)

	if dryRun {
		for k, v := range appEnv {
			fmt.Printf("%s=%s\n", k, v)
		}
		return nil
	}

	gitRoot, err := paths.GitRoot()
	if err != nil {
		return fatalErrorf("Failed to find git root: %w", err)
	}

	envPath := filepath.Join(gitRoot, ".vscode", ".env")

	if _, err := os.Stat(envPath); os.IsNotExist(err) {
		log.Warnf("%s does not exist. Creating it with port variables only.", envPath)
		log.Warnf("This file normally contains additional settings (API keys, auth config, etc.).")
		log.Warnf("You may want to copy the template from the repo wiki or another developer's setup.")
		if !prompt.Confirm("Continue creating a minimal .vscode/.env? (yes/no): ") {
			log.Info("Aborted.")
			return nil
		}
	}

	if err := devstack.UpsertEnvFile(envPath, appEnv); err != nil {
		return fatalErrorf("Failed to update %s: %w", envPath, err)
	}
	// Dev runs the object store only, so a legacy endpoint left by an earlier
	// ods would only make the app fail over to a MinIO that never starts.
	if err := removeEnvKey(envPath, legacyEndpointVar); err != nil {
		return fatalErrorf("Failed to update %s: %w", envPath, err)
	}

	log.Infof("Updated %s", envPath)
	for k, v := range appEnv {
		log.Debugf("  %s=%s", k, v)
	}
	return nil
}

// queryContainerPorts discovers the actual host ports of running containers by
// calling "docker port" for each port spec in InfraServices. Container names
// follow the Docker Compose convention "<project>-<service>-1". Missing
// containers are excluded.
func queryContainerPorts(projName string) *docker.ResolvedPorts {
	resolved := docker.NewResolvedPorts()

	for _, svc := range docker.InfraServices {
		container := docker.ContainerName(projName, svc.Name)
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

// removeEnvKey drops every "KEY=" line from a dotenv file.
func removeEnvKey(envPath, key string) error {
	data, err := os.ReadFile(envPath)
	if err != nil {
		return fmt.Errorf("read %s: %w", envPath, err)
	}

	prefix := key + "="
	var kept []string
	for _, line := range strings.Split(string(data), "\n") {
		if !strings.HasPrefix(line, prefix) {
			kept = append(kept, line)
		}
	}
	return os.WriteFile(envPath, []byte(strings.Join(kept, "\n")), 0644)
}
