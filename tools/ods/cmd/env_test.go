package cmd

import (
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestSetEnvValues_createsFileWhenMissing(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	err := setEnvValues(envPath, map[string]string{
		"FOO": "bar",
		"BAZ": "qux",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "FOO=bar") {
		t.Errorf("expected FOO=bar in output, got:\n%s", content)
	}
	if !strings.Contains(content, "BAZ=qux") {
		t.Errorf("expected BAZ=qux in output, got:\n%s", content)
	}
}

func TestSetEnvValues_upsertsExistingKeys(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	initial := "FOO=old\nOTHER=keep\n"
	if err := os.WriteFile(envPath, []byte(initial), 0644); err != nil {
		t.Fatalf("failed to write initial file: %v", err)
	}

	err := setEnvValues(envPath, map[string]string{
		"FOO": "new",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "FOO=new") {
		t.Errorf("expected FOO=new, got:\n%s", content)
	}
	if strings.Contains(content, "FOO=old") {
		t.Errorf("old value FOO=old should be replaced, got:\n%s", content)
	}
	if !strings.Contains(content, "OTHER=keep") {
		t.Errorf("OTHER=keep should be preserved, got:\n%s", content)
	}
}

func TestSetEnvValues_appendsNewKeys(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	initial := "EXISTING=value\n"
	if err := os.WriteFile(envPath, []byte(initial), 0644); err != nil {
		t.Fatalf("failed to write initial file: %v", err)
	}

	err := setEnvValues(envPath, map[string]string{
		"NEW_KEY": "new_value",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "EXISTING=value") {
		t.Errorf("EXISTING=value should be preserved, got:\n%s", content)
	}
	if !strings.Contains(content, "NEW_KEY=new_value") {
		t.Errorf("expected NEW_KEY=new_value appended, got:\n%s", content)
	}
}

func TestSetEnvValues_doesNotDuplicateOnRepeatedCalls(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	values := map[string]string{
		"PORT": "5432",
	}

	for i := 0; i < 5; i++ {
		if err := setEnvValues(envPath, values); err != nil {
			t.Fatalf("call %d: unexpected error: %v", i, err)
		}
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	count := strings.Count(string(data), "PORT=5432")
	if count != 1 {
		t.Errorf("expected exactly 1 occurrence of PORT=5432 after 5 calls, got %d:\n%s", count, string(data))
	}
}

func TestSetEnvValues_doesNotMatchCommentedOutKeys(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	initial := "# FOO=old_commented\nBAR=keep\n"
	if err := os.WriteFile(envPath, []byte(initial), 0644); err != nil {
		t.Fatalf("failed to write initial file: %v", err)
	}

	err := setEnvValues(envPath, map[string]string{
		"FOO": "new",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "# FOO=old_commented") {
		t.Errorf("comment line should be preserved, got:\n%s", content)
	}
	if !strings.Contains(content, "FOO=new") {
		t.Errorf("expected FOO=new appended, got:\n%s", content)
	}
}

func TestSetEnvValues_overwritesWithNewValue(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	if err := setEnvValues(envPath, map[string]string{"PORT": "5432"}); err != nil {
		t.Fatalf("first call: %v", err)
	}
	if err := setEnvValues(envPath, map[string]string{"PORT": "15432"}); err != nil {
		t.Fatalf("second call: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if strings.Contains(content, "PORT=5432") {
		t.Errorf("old value PORT=5432 should be gone, got:\n%s", content)
	}
	if !strings.Contains(content, "PORT=15432") {
		t.Errorf("expected PORT=15432, got:\n%s", content)
	}
	if strings.Count(content, "PORT=") != 1 {
		t.Errorf("expected exactly 1 PORT= line, got:\n%s", content)
	}
}

func TestQueryContainerPorts_usesRunningContainersOnly(t *testing.T) {
	bin := composeFakeBin(t)
	composeFakeTool(t, bin, "docker", `case "$2" in *-relational_db-1|*-minio-1) echo "0.0.0.0:3$3" ;; *) exit 1 ;; esac`)
	logs := composeCaptureLog(t)

	resolved := queryContainerPorts("proj")

	wantEnv := map[string]string{
		"POSTGRES_HOST_PORT":      "35432",
		"MINIO_API_HOST_PORT":     "39000",
		"MINIO_CONSOLE_HOST_PORT": "39001",
	}
	if got := resolved.ComposeEnv(); !maps.Equal(got, wantEnv) {
		t.Fatalf("expected %v, got %v", wantEnv, got)
	}
	wantCalls := []string{
		"port proj-relational_db-1 5432",
		"port proj-cache-1 6379",
		"port proj-opensearch-1 9200",
		"port proj-inference_model_server-1 9000",
		"port proj-minio-1 9000",
		"port proj-minio-1 9001",
		"port proj-code-interpreter-1 8000",
	}
	if got := composeCalls(t, bin, "docker"); !slices.Equal(got, wantCalls) {
		t.Fatalf("expected %q, got %q", wantCalls, got)
	}
	wantLogs := "level=warning msg=cache: container not running, skipping getting its port.\n" +
		"level=warning msg=opensearch: container not running, skipping getting its port.\n" +
		"level=warning msg=inference_model_server: container not running, skipping getting its port.\n" +
		"level=warning msg=code-interpreter: container not running, skipping getting its port.\n"
	if logs.String() != wantLogs {
		t.Fatalf("expected logs %q, got %q", wantLogs, logs.String())
	}
}

// composeAppEnv is the .vscode/.env content for containers whose host ports
// are the container ports prefixed with 1.
var composeAppEnv = map[string]string{
	"POSTGRES_PORT":             "15432",
	"REDIS_PORT":                "16379",
	"OPENSEARCH_REST_API_PORT":  "19200",
	"MODEL_SERVER_PORT":         "19000",
	"S3_ENDPOINT_URL":           "http://localhost:19000",
	"CODE_INTERPRETER_BASE_URL": "http://localhost:18000",
}

func composeEnvDocker(t *testing.T) string {
	t.Helper()
	bin := composeFakeBin(t)
	composeFakeTool(t, bin, "docker", `echo "0.0.0.0:1$3"`)
	return bin
}

func TestEnvCommand_updatesVSCodeEnvInPlace(t *testing.T) {
	bin := composeEnvDocker(t)
	root := composeRepo(t)
	envPath := filepath.Join(root, ".vscode", ".env")
	writeFile(t, envPath, "CUSTOM_SETTING=x\nPOSTGRES_PORT=1\n")

	command := NewEnvCommand()
	command.SetArgs([]string{})
	if err := command.Execute(); err != nil {
		t.Fatal(err)
	}

	content := composeReadFile(t, envPath)
	if !strings.HasPrefix(content, "CUSTOM_SETTING=x\nPOSTGRES_PORT=15432\n") {
		t.Fatalf("expected existing lines to stay in place, got %q", content)
	}
	want := maps.Clone(composeAppEnv)
	want["CUSTOM_SETTING"] = "x"
	if got := composeEnvFile(t, content); !maps.Equal(got, want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
	if got := composeCalls(t, bin, "docker"); len(got) != 7 || got[0] != "port ods-proj-relational_db-1 5432" {
		t.Fatalf("expected port queries for project ods-proj, got %q", got)
	}
}

func TestRunEnv_dryRunPrintsWithoutWriting(t *testing.T) {
	composeEnvDocker(t)
	root := composeRepo(t)

	var err error
	stdout := composeCapture(t, &os.Stdout, func() { err = runEnv(true) })

	if err != nil {
		t.Fatal(err)
	}
	if got := composeEnvFile(t, stdout); !maps.Equal(got, composeAppEnv) {
		t.Fatalf("expected %v, got %v", composeAppEnv, got)
	}
	if _, statErr := os.Stat(filepath.Join(root, ".vscode")); !os.IsNotExist(statErr) {
		t.Fatalf("expected no .vscode directory, got %v", statErr)
	}
}

func TestRunEnv_errors(t *testing.T) {
	t.Run("env file is a directory", func(t *testing.T) {
		composeEnvDocker(t)
		root := composeRepo(t)
		envPath := filepath.Join(root, ".vscode", ".env")
		if err := os.MkdirAll(envPath, 0o755); err != nil {
			t.Fatal(err)
		}
		err := runEnv(false)
		want := "Failed to update " + envPath + ": read " + envPath + ": "
		if err == nil || !strings.HasPrefix(err.Error(), want) {
			t.Fatalf("expected error starting with %q, got %v", want, err)
		}
	})

	t.Run("outside a git repo", func(t *testing.T) {
		composeEnvDocker(t)
		composeRepo(t)
		composeNoRepo(t)
		err := runEnv(false)
		if err == nil || !strings.HasPrefix(err.Error(), "Failed to find git root: ") {
			t.Fatalf("expected a git root error, got %v", err)
		}
	})
}
