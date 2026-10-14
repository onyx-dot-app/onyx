package cmd

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

// objectStoreRepo is a compose repo with a backend directory and a docker fake
// that answers "docker port" for Postgres, the object store and MinIO and
// records the MinIO env of every compose call in <bin>/docker.env.
func objectStoreRepo(t *testing.T, bin string) string {
	t.Helper()
	root := composeRepo(t)
	if err := os.MkdirAll(filepath.Join(root, "backend"), 0o755); err != nil {
		t.Fatal(err)
	}
	composeFakeTool(t, bin, "docker", `case "$1" in
port) case "$2" in *-relational_db-1) echo "0.0.0.0:5432" ;; *-object-store-1) echo "0.0.0.0:9004" ;; *-minio-1) echo "0.0.0.0:9005" ;; *) exit 1 ;; esac ;;
compose) echo "${MINIO_REPLICAS-unset} ${MINIO_API_HOST_PORT-unset}" >> "`+filepath.Join(bin, "docker.env")+`" ;;
esac`)
	return root
}

func TestObjectStoreMigrate_copiesThenStopsMinio(t *testing.T) {
	bin := composeFakeBin(t)
	root := objectStoreRepo(t, bin)
	uvEnv := filepath.Join(bin, "uv.env")
	composeFakeTool(t, bin, "uv", `echo "$S3_ENDPOINT_URL $S3_LEGACY_ENDPOINT_URL $LEGACY_COPY_ALL_OBJECTS" > "`+uvEnv+`"`)
	envPath := filepath.Join(root, ".vscode", ".env")
	writeFile(t, envPath, "POSTGRES_PORT=1\nS3_ENDPOINT_URL=http://localhost:9\nS3_LEGACY_ENDPOINT_URL=http://localhost:8\n")

	command := NewObjectStoreCommand()
	command.SetArgs([]string{"migrate"})
	if err := command.Execute(); err != nil {
		t.Fatal(err)
	}

	compose := "compose -p ods-proj -f docker-compose.yml -f docker-compose.dev.yml --profile s3-filestore "
	wantDocker := []string{
		"port ods-proj-relational_db-1 5432",
		"port ods-proj-object-store-1 8333",
		compose + "up -d --wait minio",
		"port ods-proj-minio-1 9000",
		compose + "stop minio",
	}
	if got := composeCalls(t, bin, "docker"); !slices.Equal(got, wantDocker) {
		t.Fatalf("expected docker calls %q, got %q", wantDocker, got)
	}
	// MinIO starts despite the dev stack's zero replicas, on a free host port.
	if got := composeReadFile(t, filepath.Join(bin, "docker.env")); got != "1 0\n1 0\n" {
		t.Fatalf("expected the MinIO env on both compose calls, got %q", got)
	}
	if got := composeCalls(t, bin, "uv"); !slices.Equal(got, []string{"run python -m onyx.file_store.legacy_copy --retire"}) {
		t.Fatalf("expected the legacy copy in retire mode, got %q", got)
	}
	// The discovered ports beat the .env file, and every object is copied.
	if got := composeReadFile(t, uvEnv); got != "http://localhost:9004 http://localhost:9005 true\n" {
		t.Fatalf("copy ran with env %q", got)
	}
	if got := composeReadFile(t, envPath); got != "POSTGRES_PORT=1\nS3_ENDPOINT_URL=http://localhost:9\n" {
		t.Fatalf("expected the legacy endpoint dropped from .env, got %q", got)
	}
}

func TestObjectStoreMigrate_keepMinioSkipsTheStop(t *testing.T) {
	bin := composeFakeBin(t)
	root := objectStoreRepo(t, bin)
	composeFakeTool(t, bin, "uv", "")
	writeFile(t, filepath.Join(root, ".vscode", ".env"), "POSTGRES_PORT=1\n")

	command := NewObjectStoreCommand()
	command.SetArgs([]string{"migrate", "--keep-minio"})
	if err := command.Execute(); err != nil {
		t.Fatal(err)
	}

	for _, call := range composeCalls(t, bin, "docker") {
		if strings.HasSuffix(call, "stop minio") {
			t.Fatalf("MinIO was stopped despite --keep-minio: %q", call)
		}
	}
}

func TestObjectStoreMigrate_failedCopyKeepsEnvAndMinio(t *testing.T) {
	bin := composeFakeBin(t)
	root := objectStoreRepo(t, bin)
	composeFakeTool(t, bin, "uv", "exit 3")
	envPath := filepath.Join(root, ".vscode", ".env")
	writeFile(t, envPath, "S3_LEGACY_ENDPOINT_URL=http://localhost:8\n")

	err := runObjectStoreMigrate(false)

	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 3 {
		t.Fatalf("expected the copy's exit code, got %v", err)
	}
	if got := composeReadFile(t, envPath); got != "S3_LEGACY_ENDPOINT_URL=http://localhost:8\n" {
		t.Fatalf("expected .env untouched, got %q", got)
	}
	for _, call := range composeCalls(t, bin, "docker") {
		if strings.HasSuffix(call, "stop minio") {
			t.Fatalf("MinIO was stopped after a failed copy: %q", call)
		}
	}
}

func TestObjectStoreMigrate_needsTheInfraStack(t *testing.T) {
	bin := composeFakeBin(t)
	composeRepo(t)
	composeFakeTool(t, bin, "docker", "exit 1")

	err := runObjectStoreMigrate(false)
	if err == nil || !strings.Contains(err.Error(), "relational_db is not running") {
		t.Fatalf("expected the missing service error, got %v", err)
	}
	if got := composeCalls(t, bin, "docker"); !slices.Equal(got, []string{"port ods-proj-relational_db-1 5432"}) {
		t.Fatalf("expected no compose call before the check, got %q", got)
	}
}

func TestRemoveEnvKey(t *testing.T) {
	envPath := filepath.Join(t.TempDir(), ".env")
	writeFile(t, envPath, "A=1\nS3_LEGACY_ENDPOINT_URL=x\nB=2\n")

	if err := removeEnvKey(envPath, "S3_LEGACY_ENDPOINT_URL"); err != nil {
		t.Fatal(err)
	}
	if got := composeReadFile(t, envPath); got != "A=1\nB=2\n" {
		t.Fatalf("expected the key dropped, got %q", got)
	}
}
