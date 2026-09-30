package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

const (
	legacyEndpointVar  = "S3_LEGACY_ENDPOINT_URL"
	minioContainerPort = 9000
)

// minioEnv starts MinIO although the dev stack keeps it at zero replicas, on
// a free host port because a compose .env from an earlier ods may pin it to
// the object store's port.
var minioEnv = []string{"MINIO_REPLICAS=1", "MINIO_API_HOST_PORT=0"}

// NewObjectStoreCommand creates the parent "object-store" command.
func NewObjectStoreCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "object-store",
		Short: "Manage the dev object store (SeaweedFS)",
	}
	cmd.AddCommand(newObjectStoreMigrateCommand())
	return cmd
}

func newObjectStoreMigrateCommand() *cobra.Command {
	var keepMinio bool

	cmd := &cobra.Command{
		Use:   "migrate",
		Short: "Copy a dev MinIO's files into the object store, then stop MinIO",
		Long: `Copy the files a dev MinIO holds into the object store, then stop MinIO.

The dev stack runs the object store only. A checkout that used MinIO before it
still has its files in the minio_data volume, and this command moves them
across once: it starts MinIO, runs the app's legacy copy against it with the
settle window skipped (nothing else writes to a dev MinIO), drops
S3_LEGACY_ENDPOINT_URL from .vscode/.env so the app never writes to both
stores, and stops MinIO. The infra stack must be running. A failed copy leaves
MinIO running and .vscode/.env untouched, so fix the cause and rerun.

Examples:
  ods object-store migrate
  ods object-store migrate --keep-minio`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			if err := runObjectStoreMigrate(keepMinio); err != nil {
				exitBackendService(err)
			}
		},
	}

	cmd.Flags().BoolVar(&keepMinio, "keep-minio", false, "Leave MinIO running afterwards")

	return cmd
}

func runObjectStoreMigrate(keepMinio bool) error {
	root, err := paths.GitRoot()
	if err != nil {
		return fatalErrorf("Failed to find git root: %v", err)
	}
	proj := docker.ProjectName()
	if _, err := runningPort(proj, docker.RelationalDB); err != nil {
		return err
	}
	objectStorePort, err := runningPort(proj, docker.ObjectStore)
	if err != nil {
		return err
	}

	log.Info("Starting MinIO...")
	if err := execDockerCompose(append(baseArgs("dev"), "up", "-d", "--wait", "minio"), minioEnv); err != nil {
		return err
	}
	minioPort, err := docker.GetHostPort(docker.ContainerName(proj, "minio"), minioContainerPort)
	if err != nil {
		return fatalErrorf("MinIO started but publishes no port: %v", err)
	}

	envFile, err := ensureBackendEnvFile(root)
	if err != nil {
		return err
	}
	fileVars, err := loadBackendEnvFile(envFile)
	if err != nil {
		return err
	}
	objectStore := docker.ObjectStore.Ports[0]
	// Nothing else writes to a dev MinIO, so one clean pass is the whole copy.
	overrides := []string{
		objectStore.AppVar + "=" + objectStore.AppValue(objectStorePort),
		fmt.Sprintf("%s=http://localhost:%d", legacyEndpointVar, minioPort),
		"LEGACY_COPY_SETTLE_SECONDS=0",
	}
	env := mergeEnv(overrides, mergeEnv(os.Environ(), fileVars))

	log.Infof("Copying MinIO (localhost:%d) into the object store (localhost:%d)...", minioPort, objectStorePort)
	copyCmd := exec.Command("uv", "run", "python", "-m", "onyx.file_store.legacy_copy")
	copyCmd.Dir = filepath.Join(root, "backend")
	copyCmd.Stdout = os.Stdout
	copyCmd.Stderr = os.Stderr
	copyCmd.Stdin = os.Stdin
	copyCmd.Env = env
	if err := copyCmd.Run(); err != nil {
		return fatalErrorf("Failed to copy MinIO's files: %w", err)
	}

	if err := removeEnvKey(envFile, legacyEndpointVar); err != nil {
		return fatalErrorf("Failed to update %s: %v", envFile, err)
	}
	log.Infof("MinIO's files are in the object store and %s no longer names MinIO.", envFile)
	if keepMinio {
		log.Infof("MinIO is still running on localhost:%d.", minioPort)
		return nil
	}
	if err := execDockerCompose(append(baseArgs("dev"), "stop", "minio"), minioEnv); err != nil {
		return err
	}
	log.Infof("MinIO is stopped; the %s_minio_data volume stays until you remove it.", proj)
	return nil
}

// runningPort is the host port of a project's infra service, or an error
// naming what to start: the copy needs Postgres and the object store.
func runningPort(proj string, svc docker.ServiceSpec) (int, error) {
	port, err := docker.GetHostPort(docker.ContainerName(proj, svc.Name), svc.Ports[0].ContainerPort)
	if err != nil {
		return 0, fatalErrorf("%s is not running (start the infra stack with \"ods compose dev --infra\"): %v", svc.Name, err)
	}
	return port, nil
}
